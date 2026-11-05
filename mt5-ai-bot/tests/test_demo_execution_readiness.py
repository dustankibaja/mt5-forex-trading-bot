"""Contract tests: readiness probe is read-only and rejects funded accounts."""
from types import SimpleNamespace

from src.execution.demo_readiness import inspect_demo_execution_conditions


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    SYMBOL_TRADE_MODE_FULL = 4
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1

    def __init__(self, *, mode=0, connected=True, balance=10000,
                 min_lot=0.01, spread=1.0, trade_allowed=True):
        self.mode = mode
        self.connected = connected
        self.balance = balance
        self.min_lot = min_lot
        self.spread = spread
        self.allowed = trade_allowed
        self.order_calls = 0

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected, trade_allowed=self.allowed)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode,
                               trade_allowed=self.allowed, trade_expert=self.allowed,
                               balance=self.balance, margin_free=self.balance * 0.95,
                               currency="USD", login=5058422626,
                               password="NEVER_EXPORT")

    def symbol_info(self, symbol):
        assert symbol == "EURUSD"
        return SimpleNamespace(visible=True, trade_mode=4, point=0.00001,
                               digits=5, volume_min=self.min_lot,
                               volume_max=100.0, volume_step=0.01,
                               trade_stops_level=10)

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(ask=1.14000 + self.spread * 0.0001,
                               bid=1.14000, time=1793875200)

    def order_calc_profit(self, side, symbol, volume, entry, exit):
        # Standard EURUSD 100,000 notional per full lot.
        return (exit - entry) * volume * 100000 * (1 if side == 0 else -1)

    def order_calc_margin(self, side, symbol, volume, entry):
        return 12.0 * volume / 0.01

    def order_send(self, request):
        self.order_calls += 1
        raise AssertionError("Readiness must not place any orders")


NOW = 1793875200


def test_healthy_demo_allows_mechanical_review_without_orders():
    api = FakeMT5()
    result = inspect_demo_execution_conditions(api, now_s=NOW)
    assert result.ready_for_mechanical_review is True
    assert result.min_lot == 0.01
    assert result.estimated_min_lot_stop_loss == 2.0
    assert api.order_calls == 0
    visible = str(result.public_report())
    assert "5058422626" not in visible
    assert "NEVER_EXPORT" not in visible
    assert result.public_report()["order_execution_enabled"] is False


def test_live_account_blocked_even_if_all_other_conditions_good():
    result = inspect_demo_execution_conditions(FakeMT5(mode=2), now_s=NOW)
    assert result.ready_for_mechanical_review is False
    assert any("not verified DEMO" in x for x in result.blockers)


def test_disconnected_or_trading_disabled_is_blocked():
    for api in (FakeMT5(connected=False), FakeMT5(trade_allowed=False)):
        result = inspect_demo_execution_conditions(api, now_s=NOW)
        assert not result.ready_for_mechanical_review


def test_broker_minimum_lot_risk_too_large_rejected():
    api = FakeMT5(balance=1000, min_lot=0.1)
    result = inspect_demo_execution_conditions(api, now_s=NOW)
    assert not result.ready_for_mechanical_review
    assert "Broker minimum lot exceeds per-trade risk budget" in result.blockers


def test_stale_tick_and_wide_spread_blocked():
    api = FakeMT5(spread=3.0)
    result = inspect_demo_execution_conditions(api, now_s=NOW + 500)
    assert not result.ready_for_mechanical_review
    assert "Broker tick is stale" in result.blockers
    assert "Broker spread exceeds demo trial limit" in result.blockers
