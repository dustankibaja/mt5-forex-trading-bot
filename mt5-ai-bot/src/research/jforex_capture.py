"""Quarantined JForex capture intake. This module cannot issue paper or broker orders."""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

HOUR = 3_600_000
POLICY = "jforex-acceptance-v1"
KINDS = {name: 0 for name in ("connecting", "connected", "subscribed", "disconnected",
                            "reconnecting", "heartbeat", "strategy_started", "strategy_stopped",
                            "gap", "end", "collector_fault", "demo_account_connected",
                            "warmup_written", "warmup_unavailable")}
KINDS.update(tick=2, h1=8)


@dataclass(frozen=True)
class Observation:
    source: str
    run: str
    sequence: int
    kind: str
    raw_ms: int
    utc_ms: int
    monotonic_ns: int
    dropped: int
    prices: tuple[Decimal, ...]

    @property
    def event_id(self):
        return f"{self.run}:{self.sequence}"


def decode(line: bytes) -> Observation:
    if len(line) > 1024 or not line.endswith(b"\n"):
        raise ValueError("Oversized or incomplete spool record")
    fields = line.decode("ascii").rstrip("\r\n").split("\t")
    if len(fields) < 11:
        raise ValueError("Missing spool fields")
    version, source, producer, run, seq, kind, raw, utc, mono, dropped, symbol, *prices = fields
    if (version != "1" or producer != "collector-1" or source not in {"synthetic", "jforex_demo"}
            or symbol != "EURUSD" or KINDS.get(kind) != len(prices) or str(uuid.UUID(run)) != run):
        raise ValueError("Unexpected event schema or provenance")
    if any(not s.isascii() or not s.isdigit() or len(s) > 18 for s in (seq, raw, utc, mono, dropped)):
        raise ValueError("Invalid timestamp or sequence integer")
    if int(seq) < 1 or not 946684800000 <= int(utc) < 4102444800000:
        raise ValueError("Invalid sequence or host UTC epoch milliseconds")
    try:
        numbers = tuple(Decimal(price) for price in prices)
    except InvalidOperation:
        raise ValueError("Invalid price representation") from None
    return Observation(source, run, int(seq), kind, int(raw), int(utc), int(mono), int(dropped), numbers)


def ingest(spool: Path, journal: Path) -> dict:
    """Idempotent transactional import of one immutable, closed spool."""
    if spool.resolve() == journal.resolve():
        raise ValueError("Capture and research journal must be distinct")
    with spool.open("rb") as stream, closing(sqlite3.connect(journal)) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and tables != {"capture_events"}:
            raise ValueError("Expected a dedicated capture journal")
        db.execute("""CREATE TABLE IF NOT EXISTS capture_events (
            run TEXT, sequence INTEGER, line BLOB NOT NULL, PRIMARY KEY(run, sequence)) WITHOUT ROWID""")
        seen = inserted = 0
        first = previous = None
        for line in iter(lambda: stream.readline(1025), b""):
            item = decode(line)
            first = first or item
            if (item.run != first.run or item.source != first.source or
                    (previous and (item.sequence <= previous.sequence or previous.kind == "end"))):
                raise ValueError("Spool run or ordering changed")
            prior = db.execute("SELECT line FROM capture_events WHERE run=? AND sequence=?",
                               (item.run, item.sequence)).fetchone()
            if prior is None:
                db.execute("INSERT INTO capture_events VALUES (?,?,?)", (item.run, item.sequence, line))
                inserted += 1
            elif prior[0] != line:
                raise ValueError("Immutable event ID collision")
            seen += 1
            previous = item
        if previous is None or previous.kind != "end":
            raise ValueError("Spool missing a clean end marker")
        count = db.execute("SELECT COUNT(*) FROM capture_events WHERE run=?", (previous.run,)).fetchone()[0]
        if count != seen:
            raise ValueError("Conflicting sealed run membership")
    return {"run": first.run, "source": first.source, "seen": seen, "inserted": inserted}


def valid_price(value):
    return value.is_finite() and Decimal(".1") <= value <= Decimal("10")


def replay(journal: Path, run: str):
    with closing(sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for (line,) in db.execute("SELECT line FROM capture_events WHERE run=? ORDER BY sequence", (run,)):
            yield decode(line)


def preview(spool: Path, *, line_limit=100_000) -> dict:
    """Inspect a bounded prefix of an open capture without promoting or importing it."""
    counts = Counter()
    first_tick = last_tick = None
    paired = 0
    previous = None
    with spool.open("rb") as stream:
        for _ in range(line_limit):
            line = stream.readline(1025)
            if not line or (not line.endswith(b"\n") and len(line) <= 1024):
                break
            item = decode(line)
            if previous and (item.run != previous.run or item.source != previous.source
                             or item.sequence <= previous.sequence or previous.kind == "end"):
                raise ValueError("Capture prefix order or provenance changed")
            previous = item
            counts[item.kind] += 1
            if item.kind == "tick":
                first_tick = first_tick or item
                last_tick = item
            elif item.kind == "h1":
                paired += 1
    return {
        "source": previous.source if previous else None,
        "trust": "diagnostic_only",
        "counts": dict(counts),
        "first_tick": tick_evidence(first_tick),
        "last_tick": tick_evidence(last_tick),
        "paired_h1_callbacks": paired,
        "closed": bool(previous and previous.kind == "end"),
        "prefix_limit": line_limit,
    }


def tick_evidence(item):
    if item is None:
        return None
    bid, ask = item.prices
    return {"raw_provider_ms": item.raw_ms, "host_utc_ms": item.utc_ms,
            "host_monotonic_ns": item.monotonic_ns, "bid": str(bid), "ask": str(ask),
            "receipt_minus_provider_ms": item.utc_ms - item.raw_ms}


def assess(events) -> dict:
    counts = Counter()
    age_hist = Counter()
    dates = {}
    paired = {}
    ohlc = {}
    clean_hours = set()
    previous = None
    seen_at_raw = set()
    last_raw = 0
    source = None
    connected = subscribed = ended = reconnect_pending = False
    disconnected_at = None
    max_reconnect_ms = 0
    for e in events:
        if ended or (previous and (e.run != previous.run or e.source != source)):
            raise ValueError("Expected one sealed run")
        source = e.source
        counts[e.kind] += 1
        counts["queue_drops"] = max(counts["queue_drops"], e.dropped)
        if e.sequence != (previous.sequence if previous else 0) + 1:
            counts["missing_sequence"] += max(1, e.sequence - (previous.sequence if previous else 0) - 1)
        if previous:
            if e.utc_ms < previous.utc_ms or e.monotonic_ns < previous.monotonic_ns:
                counts["clock_regression"] += 1
            if abs((e.utc_ms - previous.utc_ms) * 1_000_000 -
                   (e.monotonic_ns - previous.monotonic_ns)) > 100_000_000:
                counts["clock_step_or_capture_skew"] += 1
        previous = e
        if e.kind == "connected":
            connected, subscribed = True, False
        elif e.kind in {"disconnected", "reconnecting"}:
            connected = subscribed = False
            reconnect_pending = True
            if disconnected_at is None:
                disconnected_at = e.monotonic_ns
        elif e.kind == "subscribed":
            subscribed = connected
        elif e.kind == "end":
            ended = True
        elif e.kind == "h1":
            px = e.prices
            if (not subscribed or not e.raw_ms or e.raw_ms % HOUR or e.raw_ms + HOUR > e.utc_ms
                    or not all(map(valid_price, px))
                    or any(px[a] > px[a + 4] for a in range(4))
                    or any(not (px[i+2] <= min(px[i], px[i+3]) <= max(px[i], px[i+3]) <= px[i+1])
                           for i in (0, 4))):
                counts["invalid_h1"] += 1
            elif e.raw_ms in paired:
                counts["duplicate_h1"] += 1
            else:
                paired[e.raw_ms] = px
        elif e.kind == "tick":
            bid, ask = e.prices
            age = e.utc_ms - e.raw_ms
            if age < 0:
                counts["negative_age"] += 1
            if not subscribed:
                counts["unsubscribed_tick"] += 1
            elif not (valid_price(bid) and valid_price(ask) and ask >= bid):
                counts["invalid_quote"] += 1
            elif not 946684800000 <= e.raw_ms < 4102444800000:
                counts["invalid_provider_epoch"] += 1
            elif e.raw_ms < last_raw:
                counts["out_of_order"] += 1
                if age > 2000:
                    counts["stale"] += 1
            else:
                stamp = datetime.fromtimestamp(e.raw_ms / 1000, tz=timezone.utc)
                target = stamp.weekday() < 5 and 7 <= stamp.hour <= 17
                if e.raw_ms != last_raw:
                    seen_at_raw.clear()
                    last_raw = e.raw_ms
                key = (bid, ask)
                if key in seen_at_raw:
                    counts["duplicate_tick"] += 1
                    continue
                if len(seen_at_raw) >= 4096:
                    counts["ordering_capacity_exceeded"] += 1
                    continue
                seen_at_raw.add(key)
                if target and age >= 0:
                    age_hist[min(age, 2001)] += 1
                if age < -100:
                    counts["future"] += 1
                elif age > 2000:
                    counts["stale"] += 1
                else:
                    counts["eligible_tick"] += 1
                    if reconnect_pending:
                        counts["observed_reconnects"] += 1
                        reconnect_pending = False
                        max_reconnect_ms = max(max_reconnect_ms,
                                               (e.monotonic_ns - disconnected_at) // 1_000_000)
                        disconnected_at = None
                    bar = e.raw_ms // HOUR * HOUR
                    if target:
                        dates.setdefault(stamp.date().isoformat(), set()).add(stamp.hour)
                    aggregate = ohlc.setdefault(bar, [bid, bid, bid, bid, ask, ask, ask, ask])
                    for offset, value in ((0, bid), (4, ask)):
                        aggregate[offset+1] = max(aggregate[offset+1], value)
                        aggregate[offset+2] = min(aggregate[offset+2], value)
                        aggregate[offset+3] = value
    for hour, px in paired.items():
        if hour in ohlc and tuple(ohlc[hour]) == px:
            clean_hours.add(hour)
    p99 = None
    remaining = (99 * sum(age_hist.values()) + 99) // 100
    for age in sorted(age_hist):
        remaining -= age_hist[age]
        if remaining <= 0:
            p99 = age
            break
    full_dates = [day for day, hours in dates.items() if len(hours) == 11 and all(
        int(datetime.fromisoformat(f"{day}T{hour:02}:00:00+00:00").timestamp() * 1000) in clean_hours
        for hour in hours)]
    faults = ("queue_drops", "missing_sequence", "collector_fault", "clock_regression",
              "clock_step_or_capture_skew", "gap", "invalid_h1", "duplicate_h1",
              "ordering_capacity_exceeded", "unsubscribed_tick", "invalid_provider_epoch")
    measurements_pass = (source == "jforex_demo" and ended and len(full_dates) >= 5
                         and counts["observed_reconnects"] >= 1 and p99 is not None and p99 <= 1000
                         and not any(counts[fault] for fault in faults))
    return {"policy": POLICY, "source": source, "trust": "synthetic" if source == "synthetic" else "quarantined",
            "counters": dict(counts), "target_hours_by_utc_date": {k: len(v) for k, v in dates.items()},
            "matching_paired_hours": len(clean_hours), "fully_matched_target_days": full_dates,
            "target_nonnegative_age_p99_ms_capped_at_2001": p99,
            "longest_observed_reconnect_ms": max_reconnect_ms if counts["observed_reconnects"] else None,
            "rejected_or_duplicate_tick_fraction": (
                (counts["tick"] - counts["eligible_tick"]) / counts["tick"] if counts["tick"] else None),
            "observed_thresholds_met": measurements_pass,
            "requires_independent_clock_and_controlled_reconnect_evidence": True}


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spool", type=Path)
    parser.add_argument("journal", type=Path, nargs="?")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if args.preview:
        if args.journal:
            parser.error("--preview does not write to a journal")
        print(json.dumps(preview(args.spool), indent=2))
        return
    if args.journal is None:
        parser.error("a dedicated journal is required for sealed import")
    result = ingest(args.spool, args.journal)
    print(json.dumps({"ingest": result, "assessment": assess(replay(args.journal, result["run"]))}, indent=2))


if __name__ == "__main__":
    main()
