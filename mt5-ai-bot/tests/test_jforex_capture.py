import uuid

import pytest

from decimal import Decimal as D

from src.research.jforex_capture import HOUR, Observation, assess, ingest, replay

BASE = 1767600000000


def spool(path, rows):
    run = str(uuid.uuid4())
    lines = []
    for seq, (kind, raw, values, drops) in enumerate(rows, 1):
        line = [1, "synthetic", "collector-1", run, seq, kind, raw,
                BASE + seq, seq * 1_000_000, drops, "EURUSD", *values]
        lines.append("\t".join(map(str, line)) + "\n")
    path.write_bytes("".join(lines).encode())
    return run


def test_capture_replay_checks_faults_and_keeps_synthetic_untrusted(tmp_path):
    path, db = tmp_path / "capture.tsv", tmp_path / "capture.sqlite"
    quote = ("1.1", "1.1002")
    run = spool(path, [
        ("connected", 0, (), 0), ("subscribed", 0, (), 0),
        ("tick", BASE - 1, quote, 0), ("tick", BASE - 1, quote, 0),
        ("tick", BASE - 4000, quote, 0), ("tick", BASE + 500, quote, 0),
        ("tick", BASE + 501, ("NaN", "1.2"), 0),
        ("disconnected", 0, (), 0), ("connected", 0, (), 0),
        ("subscribed", 0, (), 0), ("tick", BASE + 600, quote, 0),
        ("h1", BASE, (1.1,) * 8, 0), ("end", 0, (), 1),
    ])
    assert ingest(path, db)["inserted"] == 13
    assert ingest(path, db)["inserted"] == 0
    result = assess(replay(db, run))
    assert result["trust"] == "synthetic"
    assert not result["observed_thresholds_met"]
    for name in ("duplicate_tick", "stale", "out_of_order", "invalid_quote", "invalid_h1",
                 "queue_drops"):
        assert result["counters"][name] == 1
    assert result["counters"]["future"] == 2


def test_incomplete_and_rewritten_events_do_not_change_journal(tmp_path):
    path, db = tmp_path / "capture.tsv", tmp_path / "capture.sqlite"
    run = spool(path, [("connected", 0, (), 0), ("end", 0, (), 0)])
    clean = path.read_bytes()
    path.write_bytes(clean[:-1])
    with pytest.raises(ValueError, match="incomplete"):
        ingest(path, db)
    path.write_bytes(clean)
    assert ingest(path, db)["inserted"] == 2
    path.write_bytes(clean.replace(b"connected", b"heartbeat"))
    with pytest.raises(ValueError, match="collision"):
        ingest(path, db)
    assert [e.kind for e in replay(db, run)] == ["connected", "end"]


def test_paired_bar_matches_observed_sides_and_cannot_certify_short_run():
    run = str(uuid.uuid4())
    start = BASE // HOUR * HOUR

    def e(sequence, kind, raw, received, prices=()):
        return Observation("jforex_demo", run, sequence, kind, raw, received,
                           (received - start) * 1_000_000, 0, tuple(map(D, prices)))

    rows = [e(1, "connected", 0, start),
            e(2, "subscribed", 0, start),
            e(3, "tick", start + 10, start + 20, ("1.1000", "1.1002")),
            e(4, "tick", start + 30, start + 40, ("1.1001", "1.1003")),
            e(5, "h1", start, start + HOUR + 1,
              ("1.1000", "1.1001", "1.1000", "1.1001", "1.1002", "1.1003", "1.1002", "1.1003")),
            e(6, "end", 0, start + HOUR + 2)]
    result = assess(rows)
    assert result["matching_paired_hours"] == 1
    assert result["trust"] == "quarantined"
    assert not result["observed_thresholds_met"]
