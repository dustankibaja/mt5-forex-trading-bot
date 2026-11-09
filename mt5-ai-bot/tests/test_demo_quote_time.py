from types import SimpleNamespace

import pytest

from src.execution.demo_quote_time import quote_time_blocker


NOW = 1794213743.5


@pytest.mark.parametrize("offset_ms, expected", [
    (-500, None),
    (1, "future-dated"),
    (-61000, "stale"),
    (7200000, "future-dated"),
    (10800000, "future-dated"),
    (-3600000, "stale"),
])
def test_raw_utc_freshness_never_infers_a_server_or_dst_offset(offset_ms, expected):
    milliseconds = int(NOW * 1000) + offset_ms
    tick = SimpleNamespace(time=milliseconds // 1000, time_msc=milliseconds)
    blocker = quote_time_blocker(tick, NOW)
    if expected is None:
        assert blocker is None
    else:
        assert expected in blocker


@pytest.mark.parametrize("tick, expected", [
    (None, "missing"),
    (SimpleNamespace(time=int(NOW)), "missing"),
    (SimpleNamespace(time=int(NOW) - 1, time_msc=int(NOW * 1000)), "disagree"),
])
def test_missing_and_inconsistent_timestamp_fields_block(tick, expected):
    assert expected in quote_time_blocker(tick, NOW)
