"""Pre-registered regime signals. Fixed rules, zero parameter tuning."""
from __future__ import annotations

import pandas as pd
from src.research.signals import enrich

CANDIDATES = ("session_breakout", "trend_pullback", "compression_release")


def indicators(side_bars: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=side_bars.index)
    for field in ("open", "high", "low", "close"):
        df[field] = (side_bars["bid_" + field] + side_bars["ask_" + field]) / 2
    return price_indicators(df)


def price_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = enrich(df)
    df["ema200"] = df.close.ewm(span=200, adjust=False).mean()
    df["atr60_median_prior"] = df.atr14.rolling(60).median().shift(1)
    df["range12_hi_prior"] = df.high.rolling(12).max().shift(1)
    df["range12_lo_prior"] = df.low.rolling(12).min().shift(1)
    return df


def signal(frame: pd.DataFrame, i: int, name: str) -> int:
    """i is the completed bar; a trade is never sent before i+1 open."""
    if name not in CANDIDATES:
        raise ValueError(f"Unknown hypothesis {name}")
    if i < 210:
        return 0
    row, previous = frame.iloc[i], frame.iloc[i - 1]
    hour = frame.index[i].hour
    if not 7 <= hour <= 17:
        return 0

    if name == "session_breakout":
        if row.atr14 <= row.atr60_median_prior:
            return 0
        if row.close > row.prior20_high and row.ema50 > previous.ema50:
            return 1
        if row.close < row.prior20_low and row.ema50 < previous.ema50:
            return -1

    elif name == "trend_pullback":
        if (
            row.ema20 > row.ema50 > row.ema200
            and previous.close <= previous.ema20
            and row.close > row.ema20
            and 45 <= row.rsi14 <= 65
        ):
            return 1
        if (
            row.ema20 < row.ema50 < row.ema200
            and previous.close >= previous.ema20
            and row.close < row.ema20
            and 35 <= row.rsi14 <= 55
        ):
            return -1

    elif name == "compression_release":
        compressed = (
            row.range12_hi_prior - row.range12_lo_prior
            < 2.5 * previous.atr14
        )
        if compressed and row.close > row.range12_hi_prior and row.ema50 > row.ema200:
            return 1
        if compressed and row.close < row.range12_lo_prior and row.ema50 < row.ema200:
            return -1
    return 0
