"""Tests that require no network, account, or MetaTrader."""
import lzma
import struct

import pandas as pd
import pytest

from src.research.duka_bidask import parse_month, download_month
from src.research.regime_signals import CANDIDATES, indicators, signal
from src.research.bidask_backtest import simulate
from scripts.run_bidask_study import qualified


def month_bytes():
    fmt = struct.Struct(">IIIIIf")
    raw = b"".join(
        fmt.pack(i * 3600, 110000+i, 110005+i, 109990+i, 110010+i, 100.0)
        for i in range(3)
    )
    return lzma.compress(raw)


def test_decode_bi5_hourly_month():
    frame = parse_month(month_bytes(), 2025, 1, "bid")
    assert len(frame) == 3
    assert frame.index[0] == pd.Timestamp("2025-01-01T00:00:00Z")
    assert frame.bid_high.iloc[0] == pytest.approx(1.10010)


def test_malformed_hourly_record_rejected():
    with pytest.raises(ValueError, match="Truncated"):
        parse_month(lzma.compress(b"123"), 2025, 1, "ask")


def fixed_side(count=350):
    idx = pd.date_range("2025-01-01", periods=count, freq="h", tz="UTC")
    return pd.DataFrame({
        "bid_open": [1.1000]*count, "bid_high": [1.1001]*count,
        "bid_low": [1.0999]*count, "bid_close": [1.1000]*count,
        "ask_open": [1.1001]*count, "ask_high": [1.1002]*count,
        "ask_low": [1.1000]*count, "ask_close": [1.1001]*count,
    }, index=idx)


def test_flat_market_never_trades_and_result_deterministic():
    side = fixed_side()
    mid = indicators(side)
    for name in CANDIDATES:
        assert signal(mid, 300, name) == 0
        a = simulate(side, mid, name, "2025-01-01", "2025-01-15")
        b = simulate(side, mid, name, "2025-01-01", "2025-01-15")
        assert a == b
        assert a["trades"] == 0


def test_signal_cannot_see_future_data():
    side = fixed_side()
    baseline = indicators(side)
    signals = {n: signal(baseline, 280, n) for n in CANDIDATES}
    side.loc[side.index[310], "bid_close"] = 1.1005
    updated = indicators(side)
    assert signals == {n: signal(updated, 280, n) for n in CANDIDATES}


def test_qualification_requires_real_trade_sample_and_positive_net():
    base = {
        "trades": 100, "net_return_pct": 3,
        "profit_factor": 1.2, "max_marked_drawdown_pct": 9,
    }
    assert qualified(base)
    assert not qualified({**base, "trades": 5})
    assert not qualified({**base, "net_return_pct": -0.01})
    assert not qualified({**base, "profit_factor": 0.99})

def test_cached_bidask_file_is_reused_without_network(monkeypatch, tmp_path):
    cached = tmp_path / "EURUSD-2025-01-bid.bi5"
    cached.write_bytes(month_bytes())

    def forbidden_network(*args, **kwargs):
        raise AssertionError("Valid cache should not access network")

    from src.research import duka_bidask
    monkeypatch.setattr(duka_bidask.urllib.request, "urlopen", forbidden_network)
    raw, url = download_month(2025, 1, "bid", cache_dir=tmp_path)
    assert raw == cached.read_bytes()
    assert "BID_candles_hour_1.bi5" in url


def test_intrabar_exit_does_not_reenter_at_same_bar_open(monkeypatch):
    """An exit during bar 214 cannot allow a backdated entry at its open."""
    from src.research import bidask_backtest

    side = fixed_side(count=300)
    # Trigger stop on bar 214 after the original position was carried over.
    side.loc[side.index[214], "bid_low"] = 1.09850
    mid = indicators(side)
    calls = []

    def synthetic_signal(frame, completed_bar_index, candidate):
        calls.append(completed_bar_index)
        # First trade: signal on close of bar 211, enter open 212.
        # Second signal would have been used to illegitimately re-enter
        # at open 214 AFTER observing the exit inside bar 214.
        return 1 if completed_bar_index in (211, 213) else 0

    monkeypatch.setattr(bidask_backtest, "signal", synthetic_signal)
    result = simulate(side, mid, "session_breakout", "2025-01-01", "2025-01-13")
    assert result["trades"] == 1
    assert 211 in calls
    assert 213 not in calls
