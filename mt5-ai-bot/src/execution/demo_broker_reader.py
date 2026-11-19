"""Internal observations from an already attached MT5 session. No login or trading."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import time

import MetaTrader5 as mt5

from src.execution.demo_account_binding import verify_local_binding
from src.execution.demo_intent_journal import IntentBlocked


@dataclass(frozen=True)
class Exposure:
    ticket: int
    symbol: str
    trade_type: int
    volume: float
    state: int | None


@dataclass(frozen=True)
class AccountObservation:
    binding: str
    received: datetime
    monotonic_ns: int
    equity: float
    balance: float
    positions: tuple[Exposure, ...]
    pending: tuple[Exposure, ...]


def _exposure(rows, *, pending=False):
    if rows is None:
        raise IntentBlocked("Broker exposure unavailable")
    records = {}
    for row in rows:
        ticket = getattr(row, "ticket", None)
        symbol = getattr(row, "symbol", None)
        kind = getattr(row, "type", None)
        volume = getattr(row, "volume_current" if pending else "volume", None)
        state = getattr(row, "state", None) if pending else None
        if (type(ticket) is not int or ticket <= 0 or ticket in records
                or not isinstance(symbol, str) or not symbol.strip()
                or type(kind) is not int or kind not in (range(2, 8) if pending else (0, 1))
                or type(volume) not in (float, int) or not math.isfinite(volume) or volume <= 0
                or pending and (type(state) is not int or state not in
                                (mt5.ORDER_STATE_PLACED, mt5.ORDER_STATE_PARTIAL))):
            raise IntentBlocked("Incomplete or ambiguous broker exposure")
        records[ticket] = Exposure(ticket, symbol, kind, volume, state)
    return tuple(records[key] for key in sorted(records))


class PinnedBrokerReader:
    def __init__(self, binding_path: Path):
        self.binding_path = binding_path

    def _identity(self):
        binding = verify_local_binding(mt5, self.binding_path)
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            raise IntentBlocked("Terminal disconnected")
        return binding["binding_id"]

    def observe(self) -> AccountObservation:
        start = time.monotonic_ns()
        identity = self._identity()
        positions = _exposure(mt5.positions_get())
        orders = _exposure(mt5.orders_get(), pending=True)
        account = mt5.account_info()
        if account is None or account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise IntentBlocked("Authenticated DEMO account unavailable")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
               for v in (account.balance, account.equity)):
            raise IntentBlocked("Broker equity or balance unavailable")
        if positions != _exposure(mt5.positions_get()) or orders != _exposure(mt5.orders_get(), pending=True):
            raise IntentBlocked("Exposure changed during observation")
        if identity != self._identity():
            raise IntentBlocked("Session changed during observation")
        end = time.monotonic_ns()
        if end - start > 2_000_000_000:
            raise IntentBlocked("Broker observation exceeded two seconds")
        return AccountObservation(identity, datetime.now(timezone.utc), end, account.equity,
                                  account.balance, positions, orders)

    def record_equity(self, journal):
        """Serialize capture with ledger updates. Baselines start at first observation."""
        db = journal.db
        db.execute("BEGIN IMMEDIATE")
        try:
            observation = self.observe()
            # A broker balance operation can be a deposit, withdrawal or reset.
            # Never infer opening equity from the first post-operation sample.
            day_start = observation.received.replace(hour=0, minute=0, second=0, microsecond=0)
            history = mt5.history_deals_get(day_start, observation.received)
            reason = "Opening equity and continuous drawdown history unverified"
            if history is None:
                reason = "Broker deal history unavailable"
            elif any(getattr(row, "type", None) not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL)
                     for row in history):
                reason = "Account balance adjustment or unclassified deal needs review"
            if self._identity() != observation.binding or time.monotonic_ns() - observation.monotonic_ns > 2_000_000_000:
                raise IntentBlocked("Session or history observation expired")
            db.execute("""CREATE TABLE IF NOT EXISTS risk_coverage(
                binding TEXT NOT NULL, utc_day TEXT NOT NULL, reason TEXT NOT NULL,
                PRIMARY KEY(binding, utc_day))""")
            db.execute("INSERT OR REPLACE INTO risk_coverage VALUES(?,?,?)",
                       (observation.binding, day_start.date().isoformat(), reason))
            db.execute("""CREATE TABLE IF NOT EXISTS observed_equity(
                binding TEXT NOT NULL, utc_day TEXT NOT NULL, first_utc TEXT NOT NULL,
                first_equity REAL NOT NULL, peak_equity REAL NOT NULL,
                PRIMARY KEY(binding, utc_day))""")
            db.execute("""INSERT INTO observed_equity VALUES(?,?,?,?,?)
                ON CONFLICT(binding,utc_day) DO UPDATE SET
                peak_equity=max(peak_equity,excluded.peak_equity)""",
                       (observation.binding, observation.received.date().isoformat(),
                        observation.received.isoformat(), observation.equity, observation.equity))
            db.execute("COMMIT")
        except BaseException:
            db.rollback()
            raise
        return observation
