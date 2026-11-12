"""Measure bounded fixture append, deterministic recovery and SQLite integrity."""
import argparse
import json
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from contextlib import closing
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.monitoring.paper_portfolio import Decision, PaperRules, Quote, append_fixture_events

RULES = PaperRules("synthetic-hourly", "benchmark-v1", 0, D("10000"), D(".0025"), D("30"),
                   1, 1000, 30_000, 3_600_000, D(".0005"), D(".0001"), D(".10"))


def events(count):
    for i in range(1, count + 1):
        at = i * 15_000
        if i % 240 == 0:
            yield Decision(f"d{i}", at - 1, (i // 240) % 3 - 1, D(".002"), D(".004"))
        bid = D("1.10") + D(i % 100) / D("100000")
        yield Quote(f"q{i}", at, at, bid, bid + D(".0002"))


def benchmark(path, count):
    start = time.perf_counter()
    append_fixture_events(path, RULES, events(count))
    seed = time.perf_counter() - start
    start = time.perf_counter()
    state = append_fixture_events(path, RULES, (Quote("last", (count + 1) * 15_000,
                                                     (count + 1) * 15_000, D("1.1"), D("1.1002")),))
    append = time.perf_counter() - start
    start = time.perf_counter()
    assert append_fixture_events(path, RULES) == state
    recover = time.perf_counter() - start
    start = time.perf_counter()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    integrity = time.perf_counter() - start
    tracemalloc.start()
    try:
        assert append_fixture_events(path, RULES) == state
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"quotes": count, "seed_seconds": seed, "one_append_seconds": append,
            "recovery_seconds": recover, "sqlite_integrity_seconds": integrity,
            "sqlite_bytes": path.stat().st_size, "replay_peak_python_bytes": peak,
            "closed_fixture_trades": len(state["closed_trades"]), "reconciles": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("counts", type=int, nargs="+")
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    if any(count <= 0 for count in args.counts):
        parser.error("quote counts must be positive")
    with tempfile.TemporaryDirectory(dir=args.scratch) as root:
        print(json.dumps([benchmark(Path(root) / f"fixture-{i}.sqlite3", count)
                          for i, count in enumerate(args.counts)], indent=2))
