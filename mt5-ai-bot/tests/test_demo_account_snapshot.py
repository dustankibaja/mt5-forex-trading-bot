"""Synthetic DEMO account feed tests: NEVER connect to MT5 or place orders."""
import json
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.serve_status import build_handler
from src.monitoring.demo_account_snapshot import (
    capture_demo_snapshot, invalidate_demo_snapshot, public_demo_snapshot
)
from src.monitoring.status_snapshot import publish_status


NOW = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)
EPOCH = int(NOW.timestamp())


class DemoBroker:
    ACCOUNT_TRADE_MODE_DEMO = 0
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3

    def __init__(self, *, mode=0, connected=True, positions=None, deals=None):
        self.mode = mode
        self.connected = connected
        self._positions = positions if positions is not None else []
        self._deals = deals if deals is not None else []
        self.order_calls = 0

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)

    def account_info(self):
        return SimpleNamespace(
            trade_mode=self.mode, currency="USD", balance=10000.12,
            equity=10120.34, profit=120.22, margin_free=9540.55,
            login=987654321, name="PRIVATE", server="PRIVATE-SERVER",
            password="NEVER-EXPORT"
        )

    def positions_get(self):
        return self._positions

    def history_deals_get(self, start, end):
        assert end == NOW and start == NOW - timedelta(days=7)
        return self._deals

    def order_send(self, request):
        self.order_calls += 1
        raise AssertionError("Read-only snapshot cannot place orders")


def _position():
    return SimpleNamespace(
        time=EPOCH, type=0, symbol="EURUSD", volume=0.01,
        price_open=1.12111, price_current=1.12122, profit=1.65,
        ticket=99999999, comment="DO-NOT-LEAK"
    )


def _deal(entry=1):
    return SimpleNamespace(
        time=EPOCH, type=1, entry=entry, symbol="EURUSD", volume=0.01,
        profit=7.0, commission=-0.7, swap=-0.1, fee=0,
        ticket=33333, comment="HIDDEN"
    )


def test_demo_readback_strips_account_ids_and_no_orders(tmp_path):
    path = tmp_path / "account.json"
    broker = DemoBroker(positions=[_position()], deals=[_deal(), _deal(entry=0)])
    assert capture_demo_snapshot(broker, path, now=NOW)
    data = public_demo_snapshot(path, now=NOW)
    assert data["available"] is True
    assert data["account_type"] == "demo"
    assert data["balance"] == 10000.12
    assert data["equity"] == 10120.34
    assert data["floating_pnl"] == 120.22
    assert len(data["positions"]) == 1
    assert data["recent_closing_deals"][0]["net_pnl"] == 6.2
    assert len(data["recent_closing_deals"]) == 1
    assert broker.order_calls == 0
    serialized = json.dumps(data)
    assert "987654321" not in serialized
    assert "PRIVATE" not in serialized
    assert "DO-NOT-LEAK" not in serialized
    assert "ticket" not in serialized
    raw = json.loads(path.read_text())
    raw["broker_password"] = "DONT-SHOW"
    path.write_text(json.dumps(raw))
    assert "broker_password" not in public_demo_snapshot(path, now=NOW)


def test_funded_account_clears_all_demo_values(tmp_path):
    path = tmp_path / "account.json"
    assert capture_demo_snapshot(DemoBroker(), path, now=NOW)
    assert not capture_demo_snapshot(DemoBroker(mode=2), path, now=NOW)
    value = public_demo_snapshot(path, now=NOW)
    assert value["available"] is False
    assert value["balance"] is None
    assert value["positions"] == []


def test_disconnected_broker_and_missing_history_fail_closed(tmp_path):
    path = tmp_path / "account.json"
    assert not capture_demo_snapshot(DemoBroker(connected=False), path, now=NOW)
    assert not public_demo_snapshot(path, now=NOW)["available"]
    broker = DemoBroker()
    broker._deals = None
    assert not capture_demo_snapshot(broker, path, now=NOW)
    assert public_demo_snapshot(path, now=NOW)["positions"] == []


def test_stale_or_invalidated_snapshot_never_displays_funds(tmp_path):
    path = tmp_path / "account.json"
    assert capture_demo_snapshot(DemoBroker(), path, now=NOW)
    value = public_demo_snapshot(path, now=NOW + timedelta(seconds=36))
    assert value["available"] is False
    assert value["balance"] is None
    invalidate_demo_snapshot(path, now=NOW)
    assert not public_demo_snapshot(path, now=NOW)["available"]


def test_demo_endpoint_requires_authorization_and_fresh_dry_run(tmp_path):
    secret = "a" * 40
    status_path = tmp_path / "status.json"
    demo_path = tmp_path / "account.json"
    # Use actual wall time here because endpoint does not accept an injected clock.
    now = datetime.now(timezone.utc)
    publish_status(status_path, state="running", dry_run=True, symbols=["EURUSD"], now=now)
    assert capture_demo_snapshot(DemoBroker(), demo_path, now=now)

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), build_handler(secret, status_path, demo_path)
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/v1/demo-account"
    try:
        try:
            urlopen(url, timeout=3)
            assert False, "Should demand authentication"
        except HTTPError as e:
            assert e.code == 401
        with urlopen(Request(url, headers={"Authorization": "Bearer " + secret}), timeout=3) as res:
            data = json.load(res)
            assert data["available"] is True
            assert data["account_type"] == "demo"

        # No funded/live-mode engine may expose demo account values.
        publish_status(status_path, state="running", dry_run=False, symbols=["EURUSD"], now=now)
        try:
            urlopen(Request(url, headers={"Authorization": "Bearer " + secret}), timeout=3)
            assert False, "Live-config worker must never export the demo account feed"
        except HTTPError as e:
            assert e.code == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
