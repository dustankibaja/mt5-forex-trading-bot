from pathlib import Path
from types import SimpleNamespace

from src.product.onboarding import discover_terminals, inspect_existing_demo


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, *, mode=0, connected=True, quote=True):
        self.mode = mode
        self.connected = connected
        self.quote = quote
        self.initialized_path = None
        self.shutdown_called = False

    def initialize(self, *, path):
        self.initialized_path = path
        return True

    def shutdown(self):
        self.shutdown_called = True

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected, trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode, trade_allowed=True,
                               login=12345678, server="Broker-Demo")

    def symbol_info(self, symbol):
        return SimpleNamespace(visible=True)

    def symbol_select(self, symbol, selected):
        return True

    def symbol_info_tick(self, symbol):
        if not self.quote:
            return None
        return SimpleNamespace(bid=1.1, ask=1.1001, time=1_000)


def test_detects_only_bounded_terminal_executables(tmp_path):
    common = tmp_path / "MetaTrader 5" / "terminal64.exe"
    common.parent.mkdir()
    common.write_bytes(b"")
    local = tmp_path / "local" / "Programs" / "Broker MT5" / "terminal64.exe"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"")
    assert discover_terminals(candidates=[common], local_app_data=tmp_path / "local") == sorted(
        [str(common.resolve()), str(local.resolve())], key=str.lower
    )


def test_verifies_existing_demo_but_keeps_execution_locked(tmp_path):
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"")
    api = FakeMT5()
    result = inspect_existing_demo(api, terminal, now_s=1_001)
    assert result["account_verified"] is True
    assert result["demo_only"] is True
    assert result["execution_allowed"] is False
    assert len(result["account_fingerprint"]) == 64
    assert result["account_label"].startswith("DEMO-")
    assert result["account_label"] == "DEMO-" + result["account_fingerprint"][:8].upper()
    assert result["quote"]["clock_certified"] is False
    assert {item["name"] for item in result["checks"]} >= {
        "Risk qualification", "Broker reconciliation"
    }
    assert "login" not in result
    assert api.shutdown_called


def test_rejects_live_account_and_missing_quote(tmp_path):
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"")
    result = inspect_existing_demo(FakeMT5(mode=2, quote=False), terminal)
    assert result["account_verified"] is False
    assert result["execution_allowed"] is False
    details = {item["name"]: item for item in result["checks"]}
    assert details["Account type"]["passed"] is False
    assert details["Live quote"]["passed"] is False


def test_rejects_untrusted_terminal_path(tmp_path):
    result = inspect_existing_demo(FakeMT5(), Path(tmp_path / "not-terminal.exe"))
    assert result["account_verified"] is False
    assert result["checks"] == []
