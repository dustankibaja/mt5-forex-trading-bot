"""Tests for demo-only account safety, no real broker connection."""
from types import SimpleNamespace

from scripts.demo_preflight import validate_demo_environment
from scripts.run_live import demo_account_connected


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, *, initialized=True, connected=True, mode=0):
        self.initialized = initialized
        self.connected = connected
        self.mode = mode
        self.closed = False

    def initialize(self):
        return self.initialized

    def shutdown(self):
        self.closed = True

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode)


def test_connected_demo_account_is_accepted():
    fake = FakeMT5()
    ok, message = validate_demo_environment(fake)
    assert ok is True
    assert fake.closed is True
    assert "DEMO" in message


def test_live_account_is_rejected():
    fake = FakeMT5(mode=2)
    ok, message = validate_demo_environment(fake)
    assert ok is False
    assert fake.closed is True
    assert "NOT" in message


def test_terminal_disconnected_is_rejected():
    fake = FakeMT5(connected=False)
    ok, _ = validate_demo_environment(fake)
    assert not ok
    assert fake.closed


def test_initialize_failure_is_rejected():
    fake = FakeMT5(initialized=False)
    ok, _ = validate_demo_environment(fake)
    assert not ok


def test_worker_checks_demo_identity(monkeypatch):
    import scripts.run_live as live

    monkeypatch.setattr(live.mt5, "terminal_info", lambda: SimpleNamespace(connected=True))
    monkeypatch.setattr(live.mt5, "account_info", lambda: SimpleNamespace(trade_mode=2))
    assert not demo_account_connected()
    monkeypatch.setattr(
        live.mt5, "account_info",
        lambda: SimpleNamespace(trade_mode=live.mt5.ACCOUNT_TRADE_MODE_DEMO),
    )
    assert demo_account_connected()
