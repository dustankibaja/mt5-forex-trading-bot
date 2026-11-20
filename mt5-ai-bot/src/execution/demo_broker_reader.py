"""Internal observations from an already attached MT5 session. No login or trading."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import time
from uuid import uuid4

import MetaTrader5 as mt5

from src.execution.demo_account_binding import verify_local_binding
from src.execution.demo_intent_journal import IntentBlocked
from src.execution.quote_time_certification import UtcEvidence, _is_verified_utc_evidence


@dataclass(frozen=True)
class Exposure:
    ticket: int
    identifier: int | None
    symbol: str
    trade_type: int
    volume: float
    state: int | None
    stop_loss: float
    take_profit: float


@dataclass(frozen=True)
class AccountObservation:
    binding: str
    received: datetime
    monotonic_ns: int
    equity: float
    balance: float
    positions: tuple[Exposure, ...]
    pending: tuple[Exposure, ...]


@dataclass(frozen=True)
class Reconciliation:
    binding: str
    received: datetime
    order_ticket: int
    deal_tickets: tuple[int, ...]
    filled_volume: float
    current_position_volume: float
    status: str
    raw_order_time_msc: int
    raw_deal_time_msc: tuple[int, ...]
    position_protection: tuple[tuple[int, float, float], ...]
    position_tickets: tuple[int, ...]
    timestamp_semantics: str


def _exposure(rows, *, pending=False):
    if rows is None:
        raise IntentBlocked("Broker exposure unavailable")
    records = {}
    for row in rows:
        ticket = getattr(row, "ticket", None)
        identifier = None if pending else getattr(row, "identifier", None)
        symbol = getattr(row, "symbol", None)
        kind = getattr(row, "type", None)
        volume = getattr(row, "volume_current" if pending else "volume", None)
        state = getattr(row, "state", None) if pending else None
        stop_loss = getattr(row, "sl", 0.0)
        take_profit = getattr(row, "tp", 0.0)
        if (type(ticket) is not int or ticket <= 0 or ticket in records
                or not pending and (type(identifier) is not int or identifier <= 0)
                or not isinstance(symbol, str) or not symbol.strip()
                or type(kind) is not int or kind not in (range(2, 8) if pending else (0, 1))
                or type(volume) not in (float, int) or not math.isfinite(volume) or volume <= 0
                or type(stop_loss) not in (float, int) or not math.isfinite(stop_loss) or stop_loss < 0
                or type(take_profit) not in (float, int) or not math.isfinite(take_profit) or take_profit < 0
                or pending and (type(state) is not int or state not in
                                (mt5.ORDER_STATE_PLACED, mt5.ORDER_STATE_PARTIAL))):
            raise IntentBlocked("Incomplete or ambiguous broker exposure")
        records[ticket] = Exposure(ticket, identifier, symbol, kind, volume, state,
                                   float(stop_loss), float(take_profit))
    return tuple(records[key] for key in sorted(records))


def _next_risk_status(prior, observation, session: str, trusted_utc: bool, reason: str):
    """Return a fail-closed risk transition; QUALIFIED is intentionally absent."""
    status = "INCOMPLETE"
    if prior and prior[0] != observation.binding:
        return "INVALIDATED", "Pinned identity changed"
    if not prior or prior[1] != observation.received.date().isoformat():
        return status, reason
    if prior[5] == "INVALIDATED":
        return prior[5], prior[6]
    if not trusted_utc:
        if prior[5] == "OBSERVING":
            return "INVALIDATED", "UTC evidence continuity lost"
        return "INCOMPLETE", "Independently certified UTC evidence unavailable"
    elapsed = (observation.received - datetime.fromisoformat(prior[3])).total_seconds()
    monotonic_elapsed = (observation.monotonic_ns - prior[4]) / 1e9
    if (prior[2] != session or not 0 < elapsed <= 2
            or not 0 < monotonic_elapsed <= 2 or abs(monotonic_elapsed - elapsed) > .25):
        return "INVALIDATED", "Observation continuity lost"
    return "OBSERVING", reason


class PinnedBrokerReader:
    def __init__(self, binding_path: Path):
        self.binding_path = binding_path
        self._session = uuid4().hex

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

    def record_equity(self, journal, *, utc_evidence: UtcEvidence | None = None):
        """Serialize capture using controlled UTC evidence when available.

        A missing or expired attestation deliberately leaves the daily baseline
        incomplete.  It must never be replaced by the host wall clock.
        """
        db = journal.db
        db.execute("BEGIN IMMEDIATE")
        try:
            observation = self.observe()
            trusted_utc = (
                _is_verified_utc_evidence(utc_evidence)
                and utc_evidence.account_binding == observation.binding
                and time.monotonic_ns() <= utc_evidence.expires_monotonic_ns
            )
            if trusted_utc:
                observation = AccountObservation(
                    observation.binding,
                    datetime.fromtimestamp(utc_evidence.utc_seconds, timezone.utc),
                    observation.monotonic_ns,
                    observation.equity,
                    observation.balance,
                    observation.positions,
                    observation.pending,
                )
            # A broker balance operation can be a deposit, withdrawal or reset.
            # Never infer opening equity from the first post-operation sample.
            day_start = observation.received.replace(hour=0, minute=0, second=0, microsecond=0)
            history = mt5.history_deals_get(day_start, observation.received)
            reason = ("Opening equity and continuous drawdown history unverified"
                      if trusted_utc else
                      "Independently certified UTC evidence unavailable; opening equity and continuous drawdown history unverified")
            if history is None:
                reason = "Broker deal history unavailable"
            elif any(getattr(row, "type", None) not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL)
                     for row in history):
                reason = "Account balance adjustment or unclassified deal needs review"
            elif history:
                reason = "Unattributed trading activity in broker history"
            if self._identity() != observation.binding or time.monotonic_ns() - observation.monotonic_ns > 2_000_000_000:
                raise IntentBlocked("Session or history observation expired")
            db.execute("""CREATE TABLE IF NOT EXISTS risk_coverage(
                binding TEXT NOT NULL, utc_day TEXT NOT NULL, reason TEXT NOT NULL,
                PRIMARY KEY(binding, utc_day))""")
            db.execute("INSERT OR REPLACE INTO risk_coverage VALUES(?,?,?)",
                       (observation.binding, day_start.date().isoformat(), reason))
            db.execute("""CREATE TABLE IF NOT EXISTS risk_samples(
                id INTEGER PRIMARY KEY, binding TEXT NOT NULL, day TEXT NOT NULL,
                session TEXT NOT NULL, received TEXT NOT NULL, mono INTEGER NOT NULL,
                equity REAL NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL)""")
            day = day_start.date().isoformat()
            prior = db.execute("""SELECT binding,day,session,received,mono,status,reason
                                  FROM risk_samples ORDER BY id DESC LIMIT 1""").fetchone()
            status, reason = _next_risk_status(
                prior, observation, self._session, trusted_utc, reason,
            )
            if history is None or history or observation.positions or observation.pending:
                status = "INVALIDATED"
                if observation.positions or observation.pending:
                    reason = "Account exposure requires attributed broker history"
            db.execute("""INSERT INTO risk_samples(binding,day,session,received,mono,equity,status,reason)
                          VALUES(?,?,?,?,?,?,?,?)""",
                       (observation.binding, day, self._session, observation.received.isoformat(),
                        observation.monotonic_ns, observation.equity, status, reason))
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
            # A failed read breaks continuity even when the next read is prompt.
            self._session = uuid4().hex
            raise
        return observation

    def reconcile_order(self, *, order_ticket: int, symbol: str, side: int,
                        requested_volume: float, since_utc: datetime) -> Reconciliation:
        """Read authenticated broker history for one local intent. Never mutates MT5."""
        if type(order_ticket) is not int or order_ticket <= 0 or side not in (0, 1):
            raise IntentBlocked("Invalid reconciliation identifier")
        if not isinstance(symbol, str) or not symbol or not math.isfinite(requested_volume) or requested_volume <= 0:
            raise IntentBlocked("Invalid reconciliation expectation")
        if since_utc.tzinfo is None or since_utc.utcoffset() != timedelta(0):
            raise IntentBlocked("Reconciliation start must be explicitly UTC")
        start = time.monotonic_ns()
        binding = self._identity()
        received = datetime.now(timezone.utc)
        orders = mt5.history_orders_get(since_utc, received)
        deals = mt5.history_deals_get(since_utc, received)
        if orders is None or deals is None:
            raise IntentBlocked("Broker history unavailable")
        matching_orders = [row for row in orders if getattr(row, "ticket", None) == order_ticket]
        if len(matching_orders) != 1:
            raise IntentBlocked("Expected broker order record is missing or ambiguous")
        order = matching_orders[0]
        if (getattr(order, "symbol", None) != symbol or getattr(order, "type", None) != side
                or not math.isclose(float(getattr(order, "volume_initial", 0)), requested_volume, rel_tol=0, abs_tol=1e-9)):
            raise IntentBlocked("Broker order does not match local intent")
        raw_order_time = getattr(order, "time_setup_msc", None)
        if type(raw_order_time) is not int or raw_order_time <= 0:
            raise IntentBlocked("Broker order timestamp is unavailable")
        order_position_id = getattr(order, "position_id", 0)
        if type(order_position_id) is not int or order_position_id < 0:
            raise IntentBlocked("Broker order position identifier is invalid")
        linked = [row for row in deals if getattr(row, "order", None) == order_ticket]
        if any(type(getattr(row, "ticket", None)) is not int or getattr(row, "ticket") <= 0
               or getattr(row, "symbol", None) != symbol or getattr(row, "type", None) not in (0, 1)
               or getattr(row, "position_id", None) is None or type(getattr(row, "position_id")) is not int
               or getattr(row, "position_id") <= 0
               or type(getattr(row, "time_msc", None)) is not int or getattr(row, "time_msc") <= 0
               for row in linked):
            raise IntentBlocked("Broker deal records are incomplete or mismatched")
        if any(getattr(row, "entry", None) != getattr(mt5, "DEAL_ENTRY_IN", 0) for row in linked):
            raise IntentBlocked("Broker opening deals have an unexpected entry state")
        position_ids = {row.position_id for row in linked}
        if len(position_ids) > 1 or order_position_id and position_ids and order_position_id not in position_ids:
            raise IntentBlocked("Broker order and deal position identifiers disagree")
        filled = sum(float(getattr(row, "volume", 0)) for row in linked if getattr(row, "type", None) == side)
        if not math.isfinite(filled) or filled < 0 or filled > requested_volume + 1e-9:
            raise IntentBlocked("Broker filled volume is inconsistent")
        positions = _exposure(mt5.positions_get())
        matching_positions = tuple(row for row in positions if row.identifier in position_ids)
        if any(row.symbol != symbol for row in matching_positions):
            raise IntentBlocked("Broker position identifier has a mismatched symbol")
        same_side_positions = tuple(row for row in matching_positions if row.trade_type == side)
        position_volume = sum(row.volume for row in same_side_positions)
        if position_volume > filled + 1e-9:
            raise IntentBlocked("Current position exceeds authenticated filled volume")
        if binding != self._identity() or time.monotonic_ns() - start > 2_000_000_000:
            raise IntentBlocked("Session changed during reconciliation")
        if not linked:
            status = "UNKNOWN"
        elif filled < requested_volume - 1e-9:
            status = "PARTIAL"
        elif position_volume > 0:
            status = "OPEN"
        else:
            # Empty positions alone never proves closure. A closing deal must reference
            # the same position identifier and account for the filled volume.
            closing = [row for row in deals if getattr(row, "position_id", None) in position_ids
                       and getattr(row, "entry", None) == getattr(mt5, "DEAL_ENTRY_OUT", -1)]
            if (not closing or any(getattr(row, "symbol", None) != symbol
                                   or getattr(row, "type", None) == side
                                   or type(getattr(row, "time_msc", None)) is not int
                                   or getattr(row, "time_msc") <= 0
                                   for row in closing)
                    or sum(float(getattr(row, "volume", 0)) for row in closing) + 1e-9 < filled):
                raise IntentBlocked("Closure has no sufficient authenticated deal evidence")
            status = "CLOSED"
        return Reconciliation(binding, received, order_ticket,
                              tuple(sorted(row.ticket for row in linked)), filled, position_volume,
                              status, raw_order_time, tuple(row.time_msc for row in linked),
                              tuple((row.ticket, row.stop_loss, row.take_profit)
                                    for row in matching_positions),
                              tuple(row.ticket for row in matching_positions),
                              "UNVERIFIED_PROVIDER_CLOCK")
