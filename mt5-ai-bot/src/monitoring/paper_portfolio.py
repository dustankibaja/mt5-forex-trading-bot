"""Fixture-only event replay and an atomic SQLite paper journal."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext


ZERO = Decimal(0)
MAX_QUOTE_AGE_MS = 60_000


@dataclass(frozen=True)
class PaperRules:
    strategy: str
    execution: str
    start_ms: int
    opening_cash: Decimal
    risk_fraction: Decimal
    leverage: Decimal
    max_positions: int
    max_units: int
    max_gap_ms: int
    max_hold_ms: int
    max_spread: Decimal
    slippage: Decimal
    round_trip_commission: Decimal


@dataclass(frozen=True)
class Decision:
    event_id: str
    at_ms: int
    direction: int
    stop: Decimal
    target: Decimal


@dataclass(frozen=True)
class Quote:
    event_id: str
    at_ms: int
    generated_ms: int
    bid: Decimal
    ask: Decimal


@dataclass(frozen=True)
class Gap:
    event_id: str
    at_ms: int
    reason: str


@dataclass(frozen=True)
class Financing:
    event_id: str
    at_ms: int
    debit_per_unit: Decimal


EVENT_TYPES = {kind.__name__: kind for kind in (Decision, Quote, Gap, Financing)}


def _encode(value):
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _payload(event):
    if type(event) not in EVENT_TYPES.values():
        raise ValueError("Expected a synthetic paper event")
    return _encode({"kind": type(event).__name__, **asdict(event)})


def _decode(payload):
    row = json.loads(payload)
    kind = EVENT_TYPES[row.pop("kind")]
    for key, field in kind.__dataclass_fields__.items():
        if field.type == "Decimal":
            row[key] = Decimal(row[key])
    return kind(**row)


def _money(value):
    return isinstance(value, Decimal) and value.is_finite()


class _Portfolio:
    def __init__(self, rules):
        positive = (rules.opening_cash, rules.risk_fraction, rules.leverage, rules.max_spread)
        costs = (rules.slippage, rules.round_trip_commission)
        if (not rules.strategy or not rules.execution
                or any(not _money(x) or x <= ZERO for x in positive)
                or any(not _money(x) or x < ZERO for x in costs)
                or rules.risk_fraction > Decimal(".0025") or rules.leverage < 1
                or any(type(x) is not int or x <= 0 for x in
                       (rules.max_positions, rules.max_units, rules.max_gap_ms, rules.max_hold_ms))
                or type(rules.start_ms) is not int or rules.start_ms < 0):
            raise ValueError("Invalid frozen paper rules")
        self.rules = rules
        self.cash = self.peak = rules.opening_cash
        self.drawdown = self.drawdown_fraction = ZERO
        self.at = rules.start_ms
        self.last_quote = None
        self.gap = False
        self.pending = {}
        self.positions = {}
        self.decisions = {}
        self.trades = []
        self.transactions = []
        self.discontinuities = []

    def apply(self, event):
        if (not isinstance(event.event_id, str) or not event.event_id
                or type(event.at_ms) is not int or event.at_ms < self.at):
            raise ValueError("Paper events must have IDs and chronological observation times")
        self.at = event.at_ms
        if isinstance(event, Decision):
            if (type(event.direction) is not int or event.direction not in (-1, 0, 1)
                    or any(not _money(x) or x <= ZERO for x in (event.stop, event.target))):
                raise ValueError("Invalid paper decision")
            self.decisions[event.event_id] = {
                "direction": event.direction,
                "at_ms": event.at_ms,
                "status": "neutral" if event.direction == 0 else "gap" if self.gap else "pending",
            }
            if event.direction and not self.gap:
                self.pending[event.event_id] = event
        elif isinstance(event, Gap):
            self._interrupt(event, event.reason)
        elif isinstance(event, Financing):
            if not _money(event.debit_per_unit):
                raise ValueError("Invalid financing")
            for key, position in self.positions.items():
                debit = event.debit_per_unit * position["units"]
                position["swap"] += debit
                self._book(key, event, "financing", -debit)
            self._mark()
        else:
            self._quote(event)

    def _interrupt(self, event, reason):
        self.gap = True
        self.discontinuities.append({"event_id": event.event_id, "reason": reason})
        for key in self.pending:
            self.decisions[key]["status"] = "gap"
        self.pending.clear()
        for position in self.positions.values():
            position["gap_exposed"] = True

    def _book(self, key, event, kind, amount, **details):
        self.cash += amount
        self.transactions.append({"decision_id": key, "event_id": event.event_id,
                                  "at_ms": event.at_ms, "kind": kind, "cash_delta": amount,
                                  **details})

    def _balances(self):
        unrealized = exposure = ZERO
        if self.last_quote:
            for position in self.positions.values():
                quote = self.last_quote
                side = quote.bid if position["direction"] > 0 else quote.ask
                liquidation = self._liquidation(side, position["direction"])
                unrealized += (liquidation - position["entry"]) * position["direction"] * position["units"]
                exposure += side * position["units"]
        margin = exposure / self.rules.leverage
        return unrealized, exposure, margin, self.cash + unrealized

    def _mark(self):
        _, _, _, equity = self._balances()
        self.peak = max(self.peak, equity)
        drawdown = self.peak - equity
        self.drawdown = max(self.drawdown, drawdown)
        self.drawdown_fraction = max(self.drawdown_fraction, drawdown / self.peak)

    def _liquidation(self, side, direction):
        price = side - direction * self.rules.slippage
        if price <= ZERO:
            raise ValueError("Nonpositive synthetic liquidation price")
        return price

    def _quote(self, quote):
        if (type(quote.generated_ms) is not int or quote.generated_ms < 0
                or any(not _money(x) for x in (quote.bid, quote.ask))
                or not ZERO < quote.bid <= quote.ask
                or self.last_quote and quote.at_ms <= self.last_quote.at_ms):
            raise ValueError("Invalid or out-of-order synthetic bid/ask quote")
        if not 0 <= quote.at_ms - quote.generated_ms <= MAX_QUOTE_AGE_MS:
            self._interrupt(quote, "uncertain_quote_age")
            return
        if self.last_quote and quote.generated_ms <= self.last_quote.generated_ms:
            raise ValueError("Out-of-order quote generation time")
        if self.last_quote and quote.at_ms - self.last_quote.at_ms > self.rules.max_gap_ms:
            self._interrupt(quote, "missing_quote_interval")
        self.gap = False
        self.last_quote = quote
        for key, position in list(self.positions.items()):
            self._exit(key, position, quote)
        self._mark()
        for key, intent in list(self.pending.items()):
            if quote.at_ms <= intent.at_ms or quote.generated_ms <= intent.at_ms:
                continue
            self.decisions[key]["status"] = self._enter(key, intent, quote)
            del self.pending[key]
        self._mark()

    def _enter(self, key, intent, quote):
        rules = self.rules
        if quote.at_ms - intent.at_ms > rules.max_gap_ms:
            return "expired"
        if len(self.positions) >= rules.max_positions:
            return "position_limit"
        spread = quote.ask - quote.bid
        if spread > rules.max_spread:
            return "spread_limit"
        direction = intent.direction
        entry = (quote.ask if direction > 0 else quote.bid) + direction * rules.slippage
        stop = entry - direction * intent.stop
        target = entry + direction * intent.target
        if min(entry, stop, target) <= ZERO or intent.stop <= spread + rules.slippage:
            return "invalid_protection"
        _, _, margin, equity = self._balances()
        commission = rules.round_trip_commission
        per_unit_risk = intent.stop + rules.slippage
        budget = equity * rules.risk_fraction - commission
        units = min(rules.max_units, int(max(ZERO, budget) // per_unit_risk))
        if units == 0:
            return "insufficient_risk_budget"
        new_mark = quote.bid if direction > 0 else quote.ask
        mark_cost = direction * (entry - self._liquidation(new_mark, direction)) * units
        if equity - margin - commission - mark_cost < new_mark * units / rules.leverage:
            return "insufficient_margin"
        self.positions[key] = {"entry": entry, "entry_ms": quote.at_ms, "direction": direction,
                               "units": units, "stop": stop, "target": target,
                               "risk": per_unit_risk * units + commission, "commission": commission,
                               "swap": ZERO, "gap_exposed": False}
        self._book(key, quote, "entry", -commission, price=entry, units=units)
        return "filled"

    def _exit(self, key, position, quote):
        direction = position["direction"]
        side = quote.bid if direction > 0 else quote.ask
        if direction * (side - position["stop"]) <= ZERO:
            reason = "stop"
        elif position["gap_exposed"]:
            return
        elif direction * (side - position["target"]) >= ZERO:
            reason = "target"
            side = position["target"]
        elif quote.at_ms - position["entry_ms"] >= self.rules.max_hold_ms:
            reason = "time"
        else:
            return
        price = self._liquidation(side, direction)
        gross = (price - position["entry"]) * direction * position["units"]
        net = gross - position["commission"] - position["swap"]
        self._book(key, quote, "exit", gross, price=price, units=position["units"], reason=reason)
        self.trades.append({"decision_id": key, **position, "exit": price, "exit_ms": quote.at_ms,
                            "exit_reason": reason, "gross": gross, "net": net,
                            "net_r": net / position["risk"]})
        del self.positions[key]

    def snapshot(self):
        unrealized, exposure, margin, equity = self._balances()
        count = len(self.trades)
        wins = [trade["net"] for trade in self.trades if trade["net"] > ZERO]
        losses = -sum((trade["net"] for trade in self.trades if trade["net"] < ZERO), ZERO)
        return {
            "mode": "synthetic_fixture_only", "rules": asdict(self.rules),
            "as_of_ms": self.at, "cash": self.cash,
            "realized_cash_change": self.cash - self.rules.opening_cash,
            "unrealized": unrealized, "equity": equity, "margin": margin,
            "free_margin": equity - margin, "gross_exposure": exposure,
            "mark_current": bool(self.last_quote and not self.gap
                                 and 0 <= self.at - self.last_quote.generated_ms <= MAX_QUOTE_AGE_MS),
            "max_drawdown": self.drawdown, "max_drawdown_fraction": self.drawdown_fraction,
            "profit_factor": sum(wins, ZERO) / losses if losses else None,
            "win_rate": Decimal(len(wins)) / count if count else None,
            "expectancy_r": sum((trade["net_r"] for trade in self.trades), ZERO) / count if count else None,
            "decisions": self.decisions, "open_positions": self.positions, "closed_trades": self.trades,
            "transactions": self.transactions, "discontinuities": self.discontinuities,
        }


def append_fixture_events(path, rules: PaperRules, events=()):
    """Commit event IDs and the resulting projection together, or roll back both.

    Recover by deterministic full replay. Identical IDs are idempotent and
    conflicting payloads are rejected. Use a dedicated synthetic database.
    """
    frozen = _encode(asdict(rules))
    with localcontext() as context, closing(sqlite3.connect(path)) as db, db:
        context.prec = 34
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and tables != {"paper_events", "paper_state"}:
            raise ValueError("Expected a dedicated synthetic paper database")
        db.execute("CREATE TABLE IF NOT EXISTS paper_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS paper_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), rules TEXT NOT NULL, projection TEXT NOT NULL)""")
        saved = db.execute("SELECT rules, projection FROM paper_state WHERE singleton=1").fetchone()
        if saved is None and db.execute("SELECT 1 FROM paper_events LIMIT 1").fetchone():
            raise ValueError("Paper events have no saved execution freeze")
        if saved and saved[0] != frozen:
            raise ValueError("Paper strategy or execution freeze changed")
        book = _Portfolio(rules)
        for event_id, payload in db.execute("SELECT id, payload FROM paper_events ORDER BY rowid"):
            event = _decode(payload)
            if event.event_id != event_id:
                raise ValueError("Paper event ID does not match its payload")
            book.apply(event)
        if saved and _encode(book.snapshot()) != saved[1]:
            raise ValueError("Paper projection does not reconcile with events")
        for event in events:
            payload = _payload(event)
            prior = db.execute("SELECT payload FROM paper_events WHERE id=?",
                               (event.event_id,)).fetchone()
            if prior is not None:
                if prior[0] != payload:
                    raise ValueError("Conflicting paper event ID")
                continue
            book.apply(event)
            db.execute("INSERT INTO paper_events VALUES (?, ?)", (event.event_id, payload))
        projection = _encode(book.snapshot())
        db.execute("""INSERT INTO paper_state VALUES (1, ?, ?)
                      ON CONFLICT(singleton) DO UPDATE SET projection=excluded.projection""",
                   (frozen, projection))
    return json.loads(projection)
