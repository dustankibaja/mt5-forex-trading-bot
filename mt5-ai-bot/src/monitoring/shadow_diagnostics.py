"""Read-only DEMO forward observations while quote time is uncertified."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing

import pandas as pd
import numpy as np

from src.execution.demo_quote_time import quote_time_blocker
from src.research.regime_signals import price_indicators, signal

SYMBOL = "EURUSD"
STRATEGY = "compression_release_bid_proxy_v1"


def observe(api, journal):
    account = api.account_info()
    terminal = api.terminal_info()
    if not terminal or not terminal.connected or not account or account.trade_mode != api.ACCOUNT_TRADE_MODE_DEMO:
        raise RuntimeError("Connected DEMO terminal required")
    # MT5 index zero is the active bar. Only request completed bars.
    rates = api.copy_rates_from_pos(SYMBOL, api.TIMEFRAME_H1, 1, 512)
    tick = api.symbol_info_tick(SYMBOL)
    now = time.time()
    if rates is None or len(rates) < 211:
        raise RuntimeError("Insufficient completed DEMO candles")
    current = api.account_info()
    terminal = api.terminal_info()
    if (not terminal or not terminal.connected or not current
            or current.trade_mode != api.ACCOUNT_TRADE_MODE_DEMO
            or (current.login, current.server) != (account.login, account.server)):
        raise RuntimeError("DEMO session changed during observation")
    frame = pd.DataFrame(rates)
    raw = frame.pop("time")
    if (raw.isna().any() or (raw <= 0).any()
            or not raw.is_monotonic_increasing or raw.duplicated().any()):
        raise RuntimeError("Invalid completed bar sequence")
    frame.index = pd.to_datetime(raw, unit="s", utc=True)
    prices = frame[["open", "high", "low", "close"]]
    if (not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any()
            or (frame.high < prices.max(axis=1)).any()
            or (frame.low > prices.min(axis=1)).any()):
        raise RuntimeError("Invalid completed bar prices")
    blocker = quote_time_blocker(tick, now)
    row = {
        "symbol": SYMBOL, "strategy": STRATEGY, "mode": "diagnostics_only",
        "bar_raw_time": int(raw.iloc[-1]), "observed_host_epoch": now,
        "tick_raw_time": getattr(tick, "time", None),
        "tick_raw_time_msc": getattr(tick, "time_msc", None),
        "quote_blocker": blocker or "Broker clock basis uncertified",
        # Broker-hour labels can be shifted. This signal is a diagnostic on
        # observed chart bars, not the qualified bid/ask strategy or a fill.
        "raw_broker_hour_signal": signal(price_indicators(prices), len(prices) - 1, "compression_release"),
    }
    journal.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(journal)) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS observations (
            symbol TEXT, strategy TEXT, bar INTEGER, payload TEXT NOT NULL,
            PRIMARY KEY(symbol, strategy, bar))""")
        db.execute("INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?)",
                   (SYMBOL, STRATEGY, row["bar_raw_time"], json.dumps(row, allow_nan=False)))
    return row


def export(journal):
    with closing(sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM observations ORDER BY bar, symbol, strategy"
        )]
