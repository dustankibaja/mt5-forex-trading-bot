from dataclasses import replace
from decimal import Decimal as D

import pytest

from src.monitoring.synthetic_performance import SyntheticIntent, SyntheticQuote, replay_synthetic


INTENT = SyntheticIntent("fixture-1", "frozen-fixture", 100, 1, 1000,
                         D(".002"), D(".004"), D(".0001"), D(".10"), D("100"))


def q(time, bid, ask):
    return SyntheticQuote(time, D(bid), D(ask))


def test_stop_gap_includes_spread_slippage_commission_and_swap():
    quotes = (q(99, "1.0000", "1.0001"), q(100, "1.0000", "1.0001"),
              q(101, "1.1000", "1.1002"), q(103, "1.0960", "1.0962"),
              q(104, "1.1200", "1.1202"))
    fees = ((102, D(".20")), (104, D("5")))
    result = replay_synthetic(INTENT, quotes, swap_debits=fees)
    assert (result.entry_utc_ms, result.entry) == (101, D("1.1003"))
    assert (result.exit_reason, result.exit_utc_ms, result.exit) == ("stop", 103, D("1.0959"))
    assert result.gross_pnl == D("-4.40")
    assert result.net_pnl == D("-4.70")
    assert result.max_equity_drawdown == D("4.70")
    assert result.nominal_net_r == D("-2.35")
    assert replay_synthetic(INTENT, quotes[:4], swap_debits=fees) == result
    assert replay_synthetic(INTENT, quotes[:3], swap_debits=fees).net_pnl is None


def test_short_target_uses_ask_and_caps_favorable_gap():
    intent = replace(INTENT, direction=-1)
    quotes = (q(101, "1.1000", "1.1002"), q(102, "1.0940", "1.0942"))
    result = replay_synthetic(intent, quotes)
    assert (result.exit_reason, result.exit) == ("target", D("1.0960"))
    assert result.net_pnl == D("3.80")
    assert replay_synthetic(replace(intent, direction=0), quotes) is None


def test_rejects_ohlc_or_out_of_order_prices():
    first = q(101, "1.1000", "1.1002")
    with pytest.raises(ValueError, match="chronological"):
        replay_synthetic(INTENT, (first, first))
    with pytest.raises(ValueError, match="synthetic bid/ask"):
        replay_synthetic(INTENT, ({"open": D("1.1"), "high": D("1.2"), "low": D("1.0")},))
