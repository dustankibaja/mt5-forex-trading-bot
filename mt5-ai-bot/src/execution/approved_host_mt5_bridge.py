"""Read-only MT5 build-6327 timestamp observation model.

This is a model boundary, not an MT5 client.  It invokes no MetaTrader API and
therefore cannot inspect credentials, switch accounts, change permissions, or
submit orders.  A future approved-host adapter must supply the raw fields.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from src.execution.quote_time_certification import UtcEvidence, _is_verified_utc_evidence


@dataclass(frozen=True)
class RawMt5Tick:
    account_binding: str
    host_identity: str
    symbol: str
    native_time: int
    native_time_msc: int
    python_time: int
    python_time_msc: int
    bid: float
    ask: float
    receipt_monotonic_ns: int


@dataclass(frozen=True)
class Mt5Build6327Observation:
    raw: RawMt5Tick
    utc: UtcEvidence
    is_new_tick: bool
    cached_reason: str


class Mt5Build6327ReadOnlyBridge:
    """Preserve raw native/Python fields and classify only local repetition."""
    def __init__(self, *, account_binding: str, host_identity: str):
        if not account_binding or not host_identity:
            raise ValueError("verified DEMO binding and approved host identity are required")
        self._binding = account_binding
        self._host = host_identity
        self._last: dict[str, tuple[int, int, int, int, float, float]] = {}

    def record(self, raw: RawMt5Tick, utc: UtcEvidence) -> Mt5Build6327Observation:
        if (not _is_verified_utc_evidence(utc) or raw.account_binding != self._binding
                or raw.host_identity != self._host or utc.account_binding != self._binding
                or utc.host_identity != self._host):
            raise ValueError("same-host, account-bound verified UTC evidence is required")
        if (not raw.symbol or any(type(value) is not int for value in
                (raw.native_time, raw.native_time_msc, raw.python_time, raw.python_time_msc, raw.receipt_monotonic_ns))
                or raw.native_time_msc // 1000 != raw.native_time
                or raw.python_time_msc // 1000 != raw.python_time
                or not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                           for value in (raw.bid, raw.ask)) or raw.ask < raw.bid):
            raise ValueError("raw MT5 tick fields are invalid")
        fingerprint = (raw.native_time, raw.native_time_msc, raw.python_time, raw.python_time_msc, raw.bid, raw.ask)
        previous = self._last.get(raw.symbol)
        is_new = previous != fingerprint
        self._last[raw.symbol] = fingerprint
        return Mt5Build6327Observation(raw, utc, is_new,
                                       "" if is_new else "raw native/Python quote fields repeated")
