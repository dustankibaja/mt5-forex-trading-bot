"""Read-only status contract tests, no MT5 terminal or credentials."""
import json
from datetime import datetime, timedelta, timezone
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from scripts.serve_status import build_handler, token_valid
from src.monitoring.status_snapshot import publish_status, public_snapshot


def test_status_snapshot_is_sanitized_and_nontrading(tmp_path):
    path = tmp_path / "runtime" / "status.json"
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    publish_status(path, state="running", dry_run=True, symbols=["EURUSD"], now=now)
    data = public_snapshot(path, now=now)
    assert data["stale"] is False
    assert data["trading_enabled"] is False
    assert data["mode"] == "dry_run"
    assert data["symbols"] == ["EURUSD"]

    # No broker/account PII can escape through the strict allowlist.
    original = json.loads(path.read_text())
    original["mt5_password"] = "NEVER-RETURN-THIS"
    path.write_text(json.dumps(original))
    assert "mt5_password" not in public_snapshot(path, now=now)

    old = now + timedelta(seconds=31)
    stale = public_snapshot(path, now=old)
    assert stale["state"] == "offline"
    assert stale["stale"] is True
    assert stale["trading_enabled"] is False


def test_missing_status_is_offline(tmp_path):
    assert public_snapshot(tmp_path / "missing.json")["state"] == "offline"


def test_authorization_requires_strong_token():
    secret = "a" * 40
    assert token_valid("Bearer " + secret, secret)
    assert not token_valid("Bearer wrong", secret)
    assert not token_valid("Basic " + secret, secret)
    assert not token_valid("Bearer short", "short")


def test_endpoint_never_accepts_post_and_requires_bearer(tmp_path):
    secret = "m" * 40
    path = tmp_path / "status.json"
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(secret, path))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/status"
        try:
            urlopen(url, timeout=3)
            assert False, "unauthenticated GET unexpectedly succeeded"
        except HTTPError as ex:
            assert ex.code == 401

        with urlopen(
            Request(url, headers={"Authorization": "Bearer " + secret}), timeout=3
        ) as resp:
            assert json.load(resp)["state"] == "offline"

        try:
            urlopen(
                Request(url, data=b"{}", method="POST", headers={"Authorization": "Bearer " + secret}), timeout=3
            )
            assert False, "trade-capable POST unexpectedly succeeded"
        except HTTPError as ex:
            assert ex.code == 405
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
