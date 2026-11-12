"""Synthetic 4 Hz arrivals with atomic batches and independent restart replay."""
import argparse
import json
import sqlite3
import statistics
import tempfile
import time
import tracemalloc
from contextlib import closing
from decimal import Decimal as D
from pathlib import Path

from benchmark_paper_fixture import RULES
from src.monitoring.paper_portfolio import Decision, Quote, append_fixture_events


def arrivals(first, last):
    for i in range(first, last):
        at = i * 250
        if i % 14400 == 0:
            yield Decision(f"d{i}", at - 1, (i // 14400) % 3 - 1, D(".002"), D(".004"))
        bid = D("1.1") + D(i % 100) / D("100000")
        yield Quote(f"q{i}", at, at, bid, bid + D(".0002"))


def run(path, seed, batch, repetitions):
    append_fixture_events(path, RULES, arrivals(1, seed + 1))
    times = []
    for n in range(repetitions):
        first = seed + 1 + n * batch
        start = time.perf_counter()
        state = append_fixture_events(path, RULES, arrivals(first, first + batch))
        times.append(time.perf_counter() - start)
    start = time.perf_counter()
    if append_fixture_events(path, RULES) != state:
        raise RuntimeError("Restart replay diverged")
    restart = time.perf_counter() - start
    tracemalloc.start()
    if append_fixture_events(path, RULES) != state:
        raise RuntimeError("Traced restart replay diverged")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    with closing(sqlite3.connect(path)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Fixture database failed integrity check")
    return dict(seed=seed, batch=batch, repetitions=repetitions,
                median_commit_s=statistics.median(times), worst_commit_s=max(times),
                worst_buffer_fill_s=(batch - 1) / 4,
                quotes_per_commit_second=batch * repetitions / sum(times),
                restart_s=restart, db_bytes=path.stat().st_size, replay_peak_bytes=peak,
                replay_equal=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=args.scratch) as root:
        print(json.dumps([run(Path(root) / f"batch-{seed}-{size}.sqlite3", seed, size, 8)
                          for seed, size in ((30000, 4), (30000, 20), (60000, 20))],
                         indent=2))
