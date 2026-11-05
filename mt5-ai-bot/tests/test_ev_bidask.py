"""No-network tests for annual bid/ask public dataset parser."""
import gzip
import json
from datetime import datetime, timezone

import pytest

from src.research.ev_annual_bidask import parse_annual, load_annual_bidask


def compressed_year(year=2025, *, negative_spread=False, duplicate=False):
    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
    records = []
    for i in range(5200):
        spread = -.0001 if negative_spread and i==0 else .0001
        records.append({
            "ts": start+3600*i, "o":1.1, "h":1.1005,
            "l":1.0995, "c":1.1002,
            "ao":1.1+spread, "ah":1.1005+spread,
            "al":1.0995+spread, "ac":1.1002+spread, "v":123,
        })
    if duplicate:
        records[100]["ts"] = records[99]["ts"]
    return gzip.compress(json.dumps(records).encode())


def test_annual_bidask_parser_validates_time_and_executable_sides():
    frame = parse_annual(compressed_year(), 2025)
    assert len(frame) == 5200
    assert frame.index[0].tzinfo is not None
    assert frame.iloc[0]["ask_open"] > frame.iloc[0]["bid_open"]
    assert "ask_high" in frame.columns


def test_bad_spread_and_duplicates_are_rejected():
    with pytest.raises(ValueError, match="Negative"):
        parse_annual(compressed_year(negative_spread=True), 2025)
    with pytest.raises(ValueError, match="Duplicate"):
        parse_annual(compressed_year(duplicate=True), 2025)


def test_sealed_2026_never_downloaded():
    with pytest.raises(ValueError, match="Sealed"):
        load_annual_bidask(years=(2026,))
