"""Crash-safe journal for future DEMO order intents.

This module never calls a broker. Every mutation is transactional, audited,
and constrained by an explicit lifecycle graph. Uncertain outcomes cannot be
reused or retried automatically.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Mapping


class IntentBlocked(RuntimeError):
    pass


ALLOWED_TRANSITIONS = {
    "RESERVED": frozenset({"CHECKED", "REJECTED", "CANCELLED"}),
    "CHECKED": frozenset({"SEND_STARTED", "REJECTED", "CANCELLED"}),
    "SEND_STARTED": frozenset({"UNKNOWN", "PARTIAL", "ACCEPTED", "REJECTED"}),
    "UNKNOWN": frozenset({"PARTIAL", "ACCEPTED", "REJECTED"}),
    "PARTIAL": frozenset({"ACCEPTED", "CLOSED_RECONCILED"}),
    "ACCEPTED": frozenset({"CLOSED_RECONCILED"}),
    "REJECTED": frozenset(), "CANCELLED": frozenset(), "CLOSED_RECONCILED": frozenset(),
}
UNRECONCILED = frozenset({"RESERVED", "CHECKED", "SEND_STARTED", "UNKNOWN", "PARTIAL", "ACCEPTED"})
FINAL = frozenset({"REJECTED", "CANCELLED", "CLOSED_RECONCILED"})
BROKER_EVIDENCE_STATES = frozenset({"CHECKED", "REJECTED", "UNKNOWN", "PARTIAL", "ACCEPTED", "CLOSED_RECONCILED"})


def canonical_intent_id(intent: Mapping[str, Any]) -> str:
    allowed = {key: intent.get(key) for key in ("binding_id", "symbol", "side", "volume", "sl", "tp", "strategy_hash", "signal_id")}
    return hashlib.sha256(json.dumps(allowed, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _finite(value: Any) -> float:
    if isinstance(value, bool): raise IntentBlocked("Risk state is invalid")
    try: number = float(value)
    except (TypeError, ValueError, OverflowError) as error: raise IntentBlocked("Risk state is invalid") from error
    if not math.isfinite(number): raise IntentBlocked("Risk state is invalid")
    return number


def _risk_snapshot(evidence: Mapping[str, Any]) -> tuple[float, int, int]:
    required = {"source", "captured_utc", "balance", "equity", "daily_start_balance", "high_water_equity", "open_positions", "pending_orders"}
    if not isinstance(evidence, Mapping) or set(evidence) != required:
        raise IntentBlocked("Verifiable account risk evidence is required")
    if evidence["source"] not in {"mt5-account-snapshot", "deterministic-broker-fixture"}:
        raise IntentBlocked("Untrusted account risk evidence source")
    if not isinstance(evidence["captured_utc"], str) or not evidence["captured_utc"]:
        raise IntentBlocked("Risk evidence timestamp is required")
    balance, equity = _finite(evidence["balance"]), _finite(evidence["equity"])
    daily_start, high_water = _finite(evidence["daily_start_balance"]), _finite(evidence["high_water_equity"])
    positions, orders = evidence["open_positions"], evidence["pending_orders"]
    if min(balance, equity, daily_start, high_water) <= 0: raise IntentBlocked("Risk state is invalid")
    if type(positions) is not int or type(orders) is not int or min(positions, orders) < 0:
        raise IntentBlocked("Account exposure evidence is invalid")
    daily_loss_pct = max(0.0, (daily_start - equity) / daily_start * 100)
    drawdown_pct = max(0.0, (high_water - equity) / high_water * 100)
    if daily_loss_pct >= 2 or drawdown_pct >= 5:
        raise IntentBlocked("Daily loss or drawdown circuit breaker is active")
    return daily_loss_pct, positions, orders


class DemoIntentJournal:
    def __init__(self, path: Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        # Preserve the database's existing journal mode. Switching modes while
        # another process opens the database can fail before reservation begins.
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS intents(
          intent_id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,created_utc TEXT NOT NULL,
          payload TEXT NOT NULL,status TEXT NOT NULL,broker_order INTEGER,broker_deal INTEGER,
          note TEXT NOT NULL DEFAULT '')""")
        self.db.execute("CREATE TABLE IF NOT EXISTS controls(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS intent_audit(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,intent_id TEXT NOT NULL,
          from_status TEXT,to_status TEXT NOT NULL,recorded_utc TEXT NOT NULL,
          evidence_source TEXT NOT NULL,evidence TEXT NOT NULL,note TEXT NOT NULL,
          FOREIGN KEY(intent_id) REFERENCES intents(intent_id))""")

    def close(self) -> None: self.db.close()

    def set_emergency_stop(self, active: bool, *, recorded_utc: str = "unspecified") -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO controls VALUES('emergency_stop',?)", ("1" if active else "0",))
            self.db.execute("INSERT OR REPLACE INTO controls VALUES('emergency_stop_changed_utc',?)", (recorded_utc,))

    def emergency_stop(self) -> bool:
        row = self.db.execute("SELECT value FROM controls WHERE key='emergency_stop'").fetchone()
        return row is not None and row[0] == "1"

    def reserve(self, intent: Mapping[str, Any], *, created_utc: str, risk_pct: float,
                risk_evidence: Mapping[str, Any], max_account_exposure: int = 1) -> str:
        if not isinstance(created_utc, str) or not created_utc: raise IntentBlocked("Intent timestamp is required")
        risk = _finite(risk_pct)
        if not 0 < risk <= .25: raise IntentBlocked("Nominal risk exceeds 0.25%")
        if type(max_account_exposure) is not int or max_account_exposure < 1: raise IntentBlocked("Account exposure limit is invalid")
        _, open_positions, pending_orders = _risk_snapshot(risk_evidence)
        if intent.get("side") not in {"buy", "sell"} or intent.get("symbol") != "EURUSD": raise IntentBlocked("Unsupported intent")
        if not isinstance(intent.get("binding_id"), str) or not intent["binding_id"]: raise IntentBlocked("Verified account binding is required")
        for key in ("volume", "sl", "tp"):
            if key not in intent or _finite(intent[key]) <= 0: raise IntentBlocked("Protective stops and volume are required")
        intent_id = canonical_intent_id(intent)
        payload = json.dumps(intent, sort_keys=True, separators=(",", ":"), allow_nan=False)
        evidence_json = json.dumps(dict(risk_evidence), sort_keys=True, separators=(",", ":"), allow_nan=False)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if self.emergency_stop(): raise IntentBlocked("Emergency stop is active")
            active = self.db.execute("SELECT COUNT(*) FROM intents WHERE status IN (?,?,?,?,?,?)", tuple(UNRECONCILED)).fetchone()[0]
            if open_positions + pending_orders + active >= max_account_exposure: raise IntentBlocked("Account-wide exposure limit reached")
            self.db.execute("INSERT INTO intents(intent_id,binding_id,created_utc,payload,status) VALUES(?,?,?,?,?)", (intent_id, intent["binding_id"], created_utc, payload, "RESERVED"))
            self.db.execute("""INSERT INTO intent_audit(intent_id,from_status,to_status,recorded_utc,evidence_source,evidence,note)
                               VALUES(?,?,?,?,?,?,?)""", (intent_id, None, "RESERVED", created_utc, risk_evidence["source"], evidence_json, ""))
            self.db.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            if self.db.in_transaction: self.db.execute("ROLLBACK")
            raise IntentBlocked("Duplicate order intent") from error
        except Exception:
            if self.db.in_transaction: self.db.execute("ROLLBACK")
            raise
        return intent_id

    def transition(self, intent_id: str, status: str, *, recorded_utc: str,
                   evidence_source: str, evidence: Mapping[str, Any] | None = None,
                   expected_binding_id: str | None = None, broker_order: int | None = None,
                   broker_deal: int | None = None, note: str = "") -> None:
        if status not in ALLOWED_TRANSITIONS: raise ValueError("Unsupported journal state")
        if not recorded_utc or not evidence_source: raise IntentBlocked("Auditable transition evidence is required")
        broker_evidence = dict(evidence or {})
        if status in BROKER_EVIDENCE_STATES:
            if evidence_source not in {"mt5-order-check", "mt5-broker-history", "deterministic-broker-fixture"} or not broker_evidence:
                raise IntentBlocked("Broker evidence is required for this transition")
        if status in {"PARTIAL", "ACCEPTED", "CLOSED_RECONCILED"} and not any(type(value) is int and value > 0 for value in (broker_order, broker_deal)):
            raise IntentBlocked("Broker order or deal identity is required")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT status,binding_id FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
            if row is None: raise IntentBlocked("Intent does not exist")
            current, binding_id = row
            if expected_binding_id is not None and expected_binding_id != binding_id: raise IntentBlocked("Account binding changed")
            if status not in ALLOWED_TRANSITIONS[current]: raise IntentBlocked(f"Invalid intent transition {current} -> {status}")
            if self.emergency_stop() and status in {"CHECKED", "SEND_STARTED"}: raise IntentBlocked("Emergency stop is active")
            evidence_json = json.dumps(broker_evidence, sort_keys=True, separators=(",", ":"), allow_nan=False)
            self.db.execute("UPDATE intents SET status=?,broker_order=?,broker_deal=?,note=? WHERE intent_id=? AND status=?", (status, broker_order, broker_deal, note, intent_id, current))
            if self.db.execute("SELECT changes()").fetchone()[0] != 1: raise IntentBlocked("Concurrent intent transition rejected")
            self.db.execute("""INSERT INTO intent_audit(intent_id,from_status,to_status,recorded_utc,evidence_source,evidence,note)
                               VALUES(?,?,?,?,?,?,?)""", (intent_id, current, status, recorded_utc, evidence_source, evidence_json, note))
            self.db.execute("COMMIT")
        except Exception:
            if self.db.in_transaction: self.db.execute("ROLLBACK")
            raise

    def unreconciled(self) -> list[dict[str, Any]]:
        rows = self.db.execute("""SELECT intent_id,binding_id,created_utc,status,broker_order,broker_deal,note
                                  FROM intents WHERE status NOT IN ('REJECTED','CANCELLED','CLOSED_RECONCILED') ORDER BY created_utc""").fetchall()
        keys = ("intent_id", "binding_id", "created_utc", "status", "broker_order", "broker_deal", "note")
        return [dict(zip(keys, row)) for row in rows]

    def audit(self, intent_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("""SELECT sequence,from_status,to_status,recorded_utc,evidence_source,evidence,note
                                  FROM intent_audit WHERE intent_id=? ORDER BY sequence""", (intent_id,)).fetchall()
        keys = ("sequence", "from_status", "to_status", "recorded_utc", "evidence_source", "evidence", "note")
        return [dict(zip(keys, row)) for row in rows]
