"""Research pipeline safety checks; no broker or network required."""
import io

import pandas as pd
import pytest

from scripts.validate_strategies import load_data
from src.research.signals import enrich, signal
from src.research.backtest import simulate


def prices(count=300):
    t = pd.date_range("2020-01-01", periods=count, freq="h", tz="UTC")
    close = [1.1] * count
    return pd.DataFrame({
        "open": close,
        "high": [1.1001] * count,
        "low": [1.0999] * count,
        "close": close,
    }, index=t)


def test_constant_prices_cannot_generate_breakout():
    bars = enrich(prices())
    assert signal(bars, 220, "donchian") == 0
    assert signal(bars, 220, "atr_breakout") == 0
    result = simulate(bars, "donchian", "2020-01-01", "2020-01-20")
    assert result["trades"] == 0
    assert result["net_return_pct"] == 0


def test_future_candles_do_not_change_historical_signal():
    bars = prices()
    for i in range(200, 230):
        bars.iloc[i, :] = [1.1020, 1.1025, 1.1015, 1.1020]
    frame = enrich(bars)
    before = signal(frame, 215, "donchian")
    bars.iloc[240, :] = [1.2, 1.21, 1.19, 1.2]
    changed = signal(enrich(bars), 215, "donchian")
    assert before == changed


def test_invalid_candle_rejected():
    csv = "Date,open,high,low,close\n2020-01-01 00:00:00,110000,109000,109500,110100\n"
    with pytest.raises(ValueError, match="Invalid OHLC"):
        load_data(csv.encode(), 100000)


def test_duplicate_timestamps_rejected():
    csv = ("Date,open,high,low,close\n"
           "2020-01-01 00:00:00,110000,110100,109900,110010\n"
           "2020-01-01 00:00:00,110000,110100,109900,110010\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_data(csv.encode(), 100000)


def test_simulation_is_deterministic():
    bars = enrich(prices())
    a = simulate(bars, "ema_cross", "2020-01-01", "2020-01-10")
    b = simulate(bars, "ema_cross", "2020-01-01", "2020-01-10")
    assert a == b


def test_intrabar_exit_cannot_reopen_at_the_same_bar_open(monkeypatch):
    bars = prices()
    bars["atr14"] = 0.001
    bars.iloc[202, bars.columns.get_loc("low")] = 1.097
    monkeypatch.setattr(
        "src.research.backtest.signal", lambda frame, i, name: int(i in (200, 201))
    )
    result = simulate(bars, "donchian", "2020-01-01", "2020-01-20")
    assert result["trades"] == 1
