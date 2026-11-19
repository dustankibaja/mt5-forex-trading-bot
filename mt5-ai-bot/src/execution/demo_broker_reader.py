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
class AccountObservation:
    binding: str
    received: datetime
    monotonic_ns: int
    equity: float
    balance: float
    position_ids: tuple[int, ...]
    pending_ids: tuple[int, ...]


def _tickets(rows):
    if rows is None:
        raise IntentBlocked("Broker exposure unavailable")
    result = tuple(sorted(row.ticket for row in rows))
    if any(type(ticket) is not int or ticket <= 0 for ticket in result) or len(set(result)) != len(result):
        raise IntentBlocked("Inconsistent broker ticket list")
    return result


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
        positions = _tickets(mt5.positions_get())
        orders = _tickets(mt5.orders_get())
        account = mt5.account_info()
        if account is None or account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise IntentBlocked("Authenticated DEMO account unavailable")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
               for v in (account.balance, account.equity)):
            raise IntentBlocked("Broker equity or balance unavailable")
        if positions != _tickets(mt5.positions_get()) or orders != _tickets(mt5.orders_get()):
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
