from datetime import datetime, timezone
from types import SimpleNamespace

import MetaTrader5 as mt5

from scripts.run_live import refresh_account_risk
from src.execution.risk_manager import RiskLimits, RiskManager
from src.execution.safeguards import stops_level_ok


def manager():
    return RiskManager(
        limits=RiskLimits(
            risk_per_trade_pct=0.5,
            daily_loss_limit_pct=2.0,
            max_trades_per_day=3,
            max_concurrent_positions_per_symbol=1,
        )
    )


def test_broker_rebuilds_daily_loss_and_trade_count(monkeypatch):
    buy = SimpleNamespace(
        type=mt5.DEAL_TYPE_BUY, entry=mt5.DEAL_ENTRY_IN, magic=123456,
        position_id=51, profit=0, commission=-1, swap=0, fee=0,
    )
    sell = SimpleNamespace(
        type=mt5.DEAL_TYPE_SELL, entry=mt5.DEAL_ENTRY_OUT, magic=123456,
        position_id=51, profit=-250, commission=-1, swap=0, fee=0,
    )
    monkeypatch.setattr(mt5, "history_deals_get", lambda start, end: (buy, sell))
    monkeypatch.setattr(mt5, "positions_get", lambda: ())
    rm = manager()
    now = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)
    rm.reset_if_new_day(now)
    assert refresh_account_risk(now, rm)
    assert rm.state.trades_today == 1
    assert rm.can_trade(10000.0) == (False, "daily_loss_limit")


def test_missing_broker_history_fails_closed(monkeypatch):
    monkeypatch.setattr(mt5, "history_deals_get", lambda start, end: None)
    monkeypatch.setattr(mt5, "positions_get", lambda: ())
    assert not refresh_account_risk(datetime.now(timezone.utc), manager())


def test_trade_stops_level_matches_meta_trader_symbol_field():
    symbol = SimpleNamespace(trade_stops_level=10, point=0.0001)
    ok, distance = stops_level_ok(symbol, 1.097, 1.103, 1.1)
    assert ok
    assert distance > 0
    too_close, _ = stops_level_ok(symbol, 1.0995, 1.1005, 1.1)
    assert not too_close
