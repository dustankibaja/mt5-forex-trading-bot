"""Read-only DEMO forward observations while quote time is uncertified."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import uuid
from contextlib import closing

import pandas as pd
import numpy as np

from src.execution.demo_quote_time import quote_time_blocker
from src.research.regime_signals import price_indicators, signal

SYMBOL = "EURUSD"
STRATEGY = "compression_release_bid_proxy_v1"
POLL_CONTINUITY_SECONDS = 45


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


class ProspectiveJournal:
    """Observe a bar close only when this process sees its rollover."""

    def __init__(self, path):
        self.path = path
        self.session = uuid.uuid4().hex
        self.identity = None

    def poll(self, api):
        account = api.account_info()
        terminal = api.terminal_info()
        if not terminal or not terminal.connected or not account or account.trade_mode != api.ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError("Connected DEMO terminal required")
        identity = (account.login, account.server)
        if self.identity is not None and identity != self.identity:
            raise RuntimeError("DEMO session changed between observations")
        before = time.time()
        rates = api.copy_rates_from_pos(SYMBOL, api.TIMEFRAME_H1, 0, 513)
        tick = api.symbol_info_tick(SYMBOL)
        now = time.time()
        monotonic = time.monotonic()
        terminal = api.terminal_info()
        current = api.account_info()
        if (not terminal or not terminal.connected or not current
                or current.trade_mode != api.ACCOUNT_TRADE_MODE_DEMO
                or (current.login, current.server) != identity):
            raise RuntimeError("DEMO session changed during observation")
        self.identity = identity
        if rates is None or len(rates) < 212:
            raise RuntimeError("Insufficient DEMO candles")
        frame = pd.DataFrame(rates)
        raw = frame.pop("time")
        if (not pd.api.types.is_integer_dtype(raw) or (raw <= 0).any()
                or not raw.is_monotonic_increasing or raw.duplicated().any()):
            raise RuntimeError("Invalid bar sequence")
        active, completed = map(int, raw.iloc[-2:][::-1])
        prices = frame[["open", "high", "low", "close"]].iloc[:-1].copy()
        if (not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any()
                or (prices.high < prices.max(axis=1)).any()
                or (prices.low > prices.min(axis=1)).any()):
            raise RuntimeError("Invalid completed bar prices")
        prices.index = pd.to_datetime(raw.iloc[:-1], unit="s", utc=True)
        bid, ask = getattr(tick, "bid", None), getattr(tick, "ask", None)
        valid_prices = (isinstance(bid, (int, float)) and isinstance(ask, (int, float))
                        and math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask)
        blocker = quote_time_blocker(tick, now)
        row = {
            "schema": 2, "session": self.session, "source": "mt5_demo_eurusd_h1_chart_bid",
            "model": STRATEGY, "mode": "diagnostics_only", "clock_certified": False,
            "host_utc_before": before, "host_utc_after": now, "host_monotonic": monotonic,
            "active_raw_time": active, "latest_completed_raw_time": completed,
            "tick_raw_time": getattr(tick, "time", None),
            "tick_raw_time_msc": getattr(tick, "time_msc", None),
            "bid": bid if valid_prices else None, "ask": ask if valid_prices else None,
            "reason": blocker or ("Broker clock basis uncertified" if valid_prices else "Invalid bid/ask"),
            "context_bars": len(prices), "context_role": "indicator_warmup_only",
        }
        return self._persist(row, prices)

    def _persist(self, row, prices):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS forward_source (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), salt TEXT, digest TEXT)""")
            binding = db.execute("SELECT salt, digest FROM forward_source WHERE singleton=1").fetchone()
            salt = binding[0] if binding else uuid.uuid4().hex
            identity = json.dumps(self.identity, separators=(",", ":"))
            digest = hashlib.sha256((salt + identity).encode()).hexdigest()
            if binding and digest != binding[1]:
                raise RuntimeError("Forward journal belongs to a different DEMO source")
            if not binding:
                db.execute("INSERT INTO forward_source VALUES (1, ?, ?)", (salt, digest))
            db.execute("""CREATE TABLE IF NOT EXISTS forward_polls (
                seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS forward_bars (
                model TEXT, bar INTEGER, poll INTEGER NOT NULL,
                PRIMARY KEY(model, bar))""")
            record = db.execute("SELECT payload FROM forward_polls ORDER BY seq DESC LIMIT 1").fetchone()
            previous = json.loads(record[0]) if record else None
            active = row["active_raw_time"]
            completed = row["latest_completed_raw_time"]
            row["classification"] = "historical_context"
            row["raw_broker_hour_signal"] = None
            row["tick_changed"] = None
            row["seconds_since_observed_change"] = None
            row["last_observed_change_monotonic"] = (
                row["host_monotonic"] if row["tick_raw_time_msc"] is not None else None)
            if previous:
                previous_active = previous["active_raw_time"]
                elapsed = row["host_monotonic"] - previous["host_monotonic"]
                wall_elapsed = row["host_utc_after"] - previous["host_utc_after"]
                continuous = (previous["session"] == self.session
                              and 0 < elapsed <= POLL_CONTINUITY_SECONDS
                              and abs(elapsed - wall_elapsed) <= 2)
                row["gap_reason"] = (
                    "restart_or_poll_gap" if not continuous else
                    "raw_bar_gap_or_clock_change" if active != previous_active
                    and (active != previous_active + 3600 or completed != previous_active)
                    else None
                )
                if row["gap_reason"]:
                    row["gap_from_active_raw_time"] = previous_active
                    row["unobserved_raw_hours"] = max(0, (active - previous_active) // 3600)
                elif active != previous_active:
                    seen = db.execute("SELECT 1 FROM forward_bars WHERE model=? AND bar=?",
                                      (STRATEGY, completed)).fetchone()
                    if seen is None:
                        row["classification"] = "observed_rollover"
                        row["raw_broker_hour_signal"] = signal(
                            price_indicators(prices), len(prices) - 1, "compression_release")
                        row["completed_ohlc"] = prices.iloc[-1].to_dict()
                else:
                    row["classification"] = "same_active_bar"
                row["tick_changed"] = any(
                    row[key] != previous[key] for key in ("tick_raw_time_msc", "bid", "ask"))
                if continuous and row["tick_raw_time_msc"] is not None:
                    changed = (row["host_monotonic"] if row["tick_changed"]
                               else previous.get("last_observed_change_monotonic"))
                    row["last_observed_change_monotonic"] = changed
                    if changed is not None:
                        row["seconds_since_observed_change"] = row["host_monotonic"] - changed
                        row["stream_stalled"] = row["seconds_since_observed_change"] > 60
            cursor = db.execute("INSERT INTO forward_polls(payload) VALUES (?)",
                                (json.dumps(row, allow_nan=False),))
            if row["classification"] == "observed_rollover":
                db.execute("INSERT INTO forward_bars VALUES (?, ?, ?)",
                           (STRATEGY, completed, cursor.lastrowid))
        return row


def export_forward(journal):
    with closing(sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            "legacy": [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM observations ORDER BY bar, symbol, strategy")] if "observations" in tables else [],
            "forward": [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM forward_polls ORDER BY seq")] if "forward_polls" in tables else [],
        }
