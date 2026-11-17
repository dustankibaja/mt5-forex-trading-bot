"""Backward-looking candidate signals. RESEARCH ONLY; no MT5 access."""
from __future__ import annotations

import numpy as np
import pandas as pd

STRATEGIES = ("atr_breakout", "donchian", "ema_cross", "rsi_revert")


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    df["ema20"] = df.close.ewm(span=20, adjust=False).mean()
    df["ema50"] = df.close.ewm(span=50, adjust=False).mean()
    prev = df.close.shift(1)
    true_range = pd.concat([
        df.high - df.low,
        (df.high - prev).abs(),
        (df.low - prev).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    df["prior20_high"] = df.high.rolling(20).max().shift(1)
    df["prior20_low"] = df.low.rolling(20).min().shift(1)

    delta = df.close.diff().to_numpy()
    rsi = np.full(len(df), np.nan)
    if len(df) >= 15:
        gain = np.maximum(delta[1:15], 0).mean()
        loss = np.maximum(-delta[1:15], 0).mean()
        for i in range(14, len(df)):
            if i > 14:
                gain = (13 * gain + max(delta[i], 0)) / 14
                loss = (13 * loss + max(-delta[i], 0)) / 14
            rsi[i] = 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    df["rsi14"] = rsi
    return df


def signal(df: pd.DataFrame, i: int, strategy: str) -> int:
    """Decide at completed bar i; execute no earlier than bar i+1."""
    if i < 200:
        return 0
    row, before = df.iloc[i], df.iloc[i - 1]
    if strategy in ("atr_breakout", "donchian"):
        if strategy == "atr_breakout" and row.atr14 < 0.0007:
            return 0
        direction = int(row.close > row.prior20_high) - int(row.close < row.prior20_low)
        if strategy == "atr_breakout":
            if direction > 0 and row.ema50 <= before.ema50:
                return 0
            if direction < 0 and row.ema50 >= before.ema50:
                return 0
        return direction
    if strategy == "ema_cross":
        if row.ema20 > row.ema50 and before.ema20 <= before.ema50:
            return 1
        if row.ema20 < row.ema50 and before.ema20 >= before.ema50:
            return -1
        return 0
    if strategy == "rsi_revert":
        if row.rsi14 < 30 <= before.rsi14:
            return 1
        if row.rsi14 > 70 >= before.rsi14:
            return -1
        return 0
    raise ValueError(f"Unknown strategy: {strategy}")
