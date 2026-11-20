"""Append-only evidence and deterministic qualification boundary.

This module has no MT5 or network calls.  Production evidence is accepted only
from the internal UTC/broker adapters; fixtures use the same private boundary
but must never be described as broker observations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math

from src.execution.quote_time_certification import UtcEvidence, _is_verified_utc_evidence


_HISTORY_ISSUER = object()


@dataclass(frozen=True)
class BrokerHistoryEvidence:
    binding: str
    host_identity: str
    synchronization_epoch: str
    complete: bool
    flat: bool
    no_external_activity: bool
    no_cash_movements: bool
    connected_continuously: bool
    _issuer: object | None = field(default=None, repr=False, compare=False)


def _verified_broker_history_evidence(**values) -> BrokerHistoryEvidence:
    """Internal adapter/fixture factory; never expose as an API payload."""
    return BrokerHistoryEvidence(**values, _issuer=_HISTORY_ISSUER)


@dataclass(frozen=True)
class QualificationDecision:
    status: str
    reason: str


class DurableCertificationEvidence:
    """Stores raw evidence once; no update or replacement operation exists."""

    def __init__(self, db):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS certification_observations(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            binding TEXT NOT NULL, host_identity TEXT NOT NULL,
            authority TEXT NOT NULL, source_identity TEXT NOT NULL,
            synchronization_epoch TEXT NOT NULL, utc_seconds REAL NOT NULL,
            uncertainty_seconds REAL NOT NULL, receipt_monotonic_ns INTEGER NOT NULL,
            expires_monotonic_ns INTEGER NOT NULL, utc_sequence INTEGER NOT NULL,
            raw_mt5_time INTEGER, raw_mt5_time_msc INTEGER, bid REAL, ask REAL,
            invalidation_reason TEXT NOT NULL, recorded_utc TEXT NOT NULL,
            UNIQUE(binding,host_identity,synchronization_epoch,utc_sequence))""")
        db.execute("""CREATE TABLE IF NOT EXISTS certification_audit(
            sequence INTEGER PRIMARY KEY, observation_sequence INTEGER NOT NULL,
            prior_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE,
            audit_recorded_utc TEXT NOT NULL,
            FOREIGN KEY(observation_sequence) REFERENCES certification_observations(sequence))""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS certification_observations_no_update
            BEFORE UPDATE ON certification_observations BEGIN SELECT RAISE(ABORT, 'certification evidence is append-only'); END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS certification_observations_no_delete
            BEFORE DELETE ON certification_observations BEGIN SELECT RAISE(ABORT, 'certification evidence is append-only'); END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS certification_audit_no_update
            BEFORE UPDATE ON certification_audit BEGIN SELECT RAISE(ABORT, 'certification audit is append-only'); END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS certification_audit_no_delete
            BEFORE DELETE ON certification_audit BEGIN SELECT RAISE(ABORT, 'certification audit is append-only'); END""")

    @staticmethod
    def _hash_record(prior_hash: str, values: tuple) -> str:
        payload = json.dumps(values, separators=(",", ":"), allow_nan=False, default=str).encode()
        return hashlib.sha256(prior_hash.encode() + payload).hexdigest()

    def append(self, *, binding: str, utc: UtcEvidence,
               raw_mt5_time: int | None = None, raw_mt5_time_msc: int | None = None,
               bid: float | None = None, ask: float | None = None,
               invalidation_reason: str = "") -> int:
        if (not _is_verified_utc_evidence(utc) or utc.account_binding != binding
                or not all(isinstance(value, str) and value for value in
                           (binding, utc.host_identity, utc.source, utc.source_identity,
                            utc.sync_epoch))):
            raise ValueError("verified account-bound UTC evidence is required")
        if (type(utc.monotonic_ns) is not int or type(utc.expires_monotonic_ns) is not int
                or utc.expires_monotonic_ns <= utc.monotonic_ns
                or type(utc.observation_sequence) is not int or utc.observation_sequence <= 0
                or not all(isinstance(value, (int, float)) and math.isfinite(value)
                           for value in (utc.utc_seconds, utc.uncertainty_seconds))):
            raise ValueError("UTC evidence fields are invalid")
        if (raw_mt5_time is not None or raw_mt5_time_msc is not None) and (
                type(raw_mt5_time) is not int or type(raw_mt5_time_msc) is not int
                or raw_mt5_time_msc // 1000 != raw_mt5_time):
            raise ValueError("raw MT5 timestamps are inconsistent")
        if (bid is not None or ask is not None) and (not all(isinstance(value, (int, float))
                and math.isfinite(value) and value > 0 for value in (bid, ask)) or ask < bid):
            raise ValueError("raw bid/ask fields are invalid")
        recorded = datetime.now(timezone.utc).isoformat()  # audit time, not certified UTC
        values = (
            binding, utc.host_identity, utc.source, utc.source_identity, utc.sync_epoch,
            utc.utc_seconds, utc.uncertainty_seconds, utc.monotonic_ns,
            utc.expires_monotonic_ns, utc.observation_sequence, raw_mt5_time,
            raw_mt5_time_msc, bid, ask, invalidation_reason, recorded)
        own_transaction = not self.db.in_transaction
        if own_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.db.execute("""INSERT INTO certification_observations(
            binding,host_identity,authority,source_identity,synchronization_epoch,
            utc_seconds,uncertainty_seconds,receipt_monotonic_ns,expires_monotonic_ns,
            utc_sequence,raw_mt5_time,raw_mt5_time_msc,bid,ask,invalidation_reason,recorded_utc)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            prior = self.db.execute("SELECT record_hash FROM certification_audit ORDER BY sequence DESC LIMIT 1").fetchone()
            prior_hash = prior[0] if prior else "GENESIS"
            record_hash = self._hash_record(prior_hash, values)
            self.db.execute("""INSERT INTO certification_audit(observation_sequence,prior_hash,record_hash,audit_recorded_utc)
                             VALUES(?,?,?,?)""", (cursor.lastrowid, prior_hash, record_hash, recorded))
            if own_transaction:
                self.db.execute("COMMIT")
            return cursor.lastrowid
        except BaseException:
            if own_transaction and self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def verify_audit_chain(self) -> bool:
        rows = self.db.execute("""SELECT a.sequence,o.binding,o.host_identity,o.authority,o.source_identity,
            o.synchronization_epoch,o.utc_seconds,o.uncertainty_seconds,o.receipt_monotonic_ns,
            o.expires_monotonic_ns,o.utc_sequence,o.raw_mt5_time,o.raw_mt5_time_msc,o.bid,o.ask,
            o.invalidation_reason,o.recorded_utc,a.prior_hash,a.record_hash
            FROM certification_observations o JOIN certification_audit a ON a.observation_sequence=o.sequence
            ORDER BY o.sequence""").fetchall()
        prior_hash = "GENESIS"
        for expected_sequence, row in enumerate(rows, start=1):
            sequence, values, saved_prior, saved_hash = row[0], row[1:-2], row[-2], row[-1]
            if (sequence != expected_sequence or saved_prior != prior_hash
                    or saved_hash != self._hash_record(prior_hash, values)):
                return False
            prior_hash = saved_hash
        return True

    def rows(self, binding: str):
        return self.db.execute("""SELECT binding,host_identity,authority,source_identity,
            synchronization_epoch,utc_seconds,uncertainty_seconds,receipt_monotonic_ns,
            expires_monotonic_ns,utc_sequence,raw_mt5_time,raw_mt5_time_msc,bid,ask,
            invalidation_reason,recorded_utc FROM certification_observations
            WHERE binding=? ORDER BY sequence""", (binding,)).fetchall()


class RiskQualificationEvaluator:
    """Explains why durable evidence cannot, or can someday, qualify a flat DEMO."""

    def evaluate(self, *, binding: str, rows, history: BrokerHistoryEvidence | None,
                 audit_valid: bool = False) -> QualificationDecision:
        if not audit_valid:
            return QualificationDecision("INCOMPLETE", "Tamper-evident audit chain is unavailable or invalid")
        if not isinstance(history, BrokerHistoryEvidence) or history._issuer is not _HISTORY_ISSUER:
            return QualificationDecision("INCOMPLETE", "Authenticated broker-history evidence is unavailable")
        if (history.binding != binding or not history.complete or not history.flat
                or not history.no_external_activity or not history.no_cash_movements
                or not history.connected_continuously):
            return QualificationDecision("INCOMPLETE", "Broker history, flat exposure, cash activity, or continuity is incomplete")
        if len(rows) < 2:
            return QualificationDecision("OBSERVING", "A verified UTC-midnight boundary has not been bracketed")
        if any(row[0] != binding or row[1] != history.host_identity or row[4] != history.synchronization_epoch
               or row[14] for row in rows):
            return QualificationDecision("INCOMPLETE", "Evidence binding, host, epoch, or continuity is invalid")
        for previous, current in zip(rows, rows[1:]):
            if (current[9] != previous[9] + 1 or current[7] <= previous[7]
                    or current[7] - previous[7] > 2_000_000_000
                    or current[5] <= previous[5]):
                return QualificationDecision("INCOMPLETE", "UTC observation sequence is interrupted")
            if current[7] > current[8]:
                return QualificationDecision("INCOMPLETE", "UTC evidence expired during observation")
        days = {datetime.fromtimestamp(row[5], timezone.utc).date() for row in rows}
        if len(days) < 2:
            return QualificationDecision("OBSERVING", "No complete verified UTC-day boundary is present")
        if max(days).toordinal() - min(days).toordinal() != 1:
            return QualificationDecision("INCOMPLETE", "UTC observations do not bracket one continuous midnight boundary")
        # The present collector does not retain the full continuous equity proof.
        return QualificationDecision("INCOMPLETE", "Continuous equity and opening-balance proof is not yet implemented")
