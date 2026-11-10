import sqlite3
from contextlib import closing
from dataclasses import replace
from decimal import Decimal as D

import pytest

from src.monitoring.paper_portfolio import Decision, Financing, Gap, PaperRules, Quote, append_fixture_events


RULES = PaperRules("frozen-model", "fixture-v1", 0, D("10000"), D(".0025"),
                   D("100"), 2, 1000, 100, 6, D(".0005"), D(".0001"), D(".10"))


def decision(key, time, direction=1):
    return Decision(key, time, direction, D(".002"), D(".004"))


def quote(time, bid="1.1000", ask="1.1002", *, generated=None):
    return Quote(f"q{time}", time, time if generated is None else generated, D(bid), D(ask))


REFERENCE = (
    decision("A", 1), quote(2), quote(3, "1.1050", "1.1052"),
    decision("B", 4, -1), quote(5), Financing("overnight", 6, D(".0002")), quote(7, "1.1040", "1.1042"),
    decision("C", 8), quote(9, "1.1000", "1.1003"), quote(10, "1.0980", "1.0982"),
    decision("D", 11, -1), quote(12), quote(18, "1.0980", "1.0982"), decision("neutral", 19, 0),
)


def test_reference_portfolio_reconciles_with_hand_calculation(tmp_path):
    state = append_fixture_events(tmp_path / "book.sqlite3", RULES, REFERENCE)
    assert [t["exit_reason"] for t in state["closed_trades"]] == ["target", "stop", "stop", "time"]
    assert [D(t["net"]) for t in state["closed_trades"]] == [D("3.80"), D("-4.70"), D("-2.60"), D("1.50")]
    assert D(state["cash"]) == D("9998.00")
    assert D(state["equity"]) == D("9998.00")
    assert D(state["max_drawdown"]) == D("7.80")
    assert D(state["profit_factor"]) == pytest.approx(D("5.30") / D("7.30"))
    assert D(state["expectancy_r"]) == pytest.approx(D("-2.00") / D("8.80"))
    assert D(state["win_rate"]) == D(".50")
    assert sum(D(t["cash_delta"]) for t in state["transactions"]) == D("-2.00")
    assert state["decisions"]["neutral"]["status"] == "neutral"
    assert state["open_positions"] == {}


def test_restart_and_failed_projection_write_are_idempotent(tmp_path):
    path = tmp_path / "book.sqlite3"
    intent = decision("A", 1)
    assert append_fixture_events(path, RULES, (intent,))["decisions"]["A"]["status"] == "pending"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TRIGGER fail_projection BEFORE UPDATE ON paper_state
                      BEGIN SELECT RAISE(ABORT, 'fixture write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="fixture write failure"):
        append_fixture_events(path, RULES, (quote(2),))
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT count(*) FROM paper_events").fetchone() == (1,)
        db.execute("DROP TRIGGER fail_projection")
    open_state = append_fixture_events(path, RULES, (intent, quote(2)))
    assert D(open_state["margin"]) == D("11")
    assert D(open_state["gross_exposure"]) == D("1100")
    assert D(open_state["unrealized"]) == D("-.40")
    assert D(open_state["equity"]) == D("9999.50")
    assert append_fixture_events(path, RULES, (intent, quote(2))) == open_state
    with pytest.raises(ValueError, match="Conflicting"):
        append_fixture_events(path, RULES, (replace(intent, direction=-1),))
    with pytest.raises(ValueError, match="freeze"):
        append_fixture_events(path, replace(RULES, execution="other"))
    assert len(append_fixture_events(path, RULES)["transactions"]) == 1


def test_spread_margin_risk_and_concurrency_limits(tmp_path):
    cases = (
        ("spread", RULES, quote(2, "1.1000", "1.1010"), "spread_limit"),
        ("margin", replace(RULES, leverage=D(1), max_units=1_000_000),
         quote(2, "110", "110.0002"), "insufficient_margin"),
        ("risk", replace(RULES, opening_cash=D("1")), quote(2), "insufficient_risk_budget"),
    )
    for name, rules, tick, expected in cases:
        state = append_fixture_events(tmp_path / name, rules, (decision("A", 1), tick))
        assert state["decisions"]["A"]["status"] == expected
    intents = (decision("A", 1), decision("B", 1, -1), decision("C", 1), quote(2))
    state = append_fixture_events(tmp_path / "limit", RULES, intents)
    assert set(state["open_positions"]) == {"A", "B"}
    assert state["decisions"]["C"]["status"] == "position_limit"


def test_gap_stale_closure_and_causality(tmp_path):
    path = tmp_path / "book"
    state = append_fixture_events(path, RULES, (
        decision("A", 1), quote(2, generated=1), quote(3), Gap("market-closed", 4, "session_closed"),
        decision("B", 5), quote(6, "1.1060", "1.1062"),
    ))
    assert state["decisions"]["B"]["status"] == "gap"
    assert state["open_positions"]["A"]["entry_ms"] == 3
    assert state["open_positions"]["A"]["gap_exposed"]
    assert state["closed_trades"] == []
    state = append_fixture_events(path, RULES, (quote(7, "1.1060", "1.1062"),))
    assert state["closed_trades"] == []
    state = append_fixture_events(path, RULES, (quote(8, "1.0960", "1.0962"),))
    assert state["closed_trades"][0]["exit_reason"] == "stop"
    stale = append_fixture_events(tmp_path / "stale", RULES, (
        decision("C", 1), quote(60_002, generated=1), quote(60_003),
    ))
    assert stale["decisions"]["C"]["status"] == "gap"
    assert stale["transactions"] == []
    missing = append_fixture_events(tmp_path / "missing", RULES, (
        quote(1), decision("D", 2), quote(200),
    ))
    assert missing["decisions"]["D"]["status"] == "gap"
    with pytest.raises(ValueError, match="chronological"):
        append_fixture_events(path, RULES, (quote(5),))


def test_slippage_change_worsens_same_stop_outcome(tmp_path):
    events = (decision("A", 1), quote(2), quote(3, "1.0960", "1.0962"))
    low = append_fixture_events(tmp_path / "low", RULES, events)
    high = append_fixture_events(tmp_path / "high", replace(RULES, slippage=D(".0003")), events)
    assert D(high["closed_trades"][0]["net"]) < D(low["closed_trades"][0]["net"])


def test_restart_rejects_unreconciled_projection(tmp_path):
    path = tmp_path / "book"
    append_fixture_events(path, RULES, (decision("A", 1), quote(2)))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE paper_state SET projection='{}'")
    with pytest.raises(ValueError, match="does not reconcile"):
        append_fixture_events(path, RULES)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM paper_state")
    with pytest.raises(ValueError, match="no saved execution freeze"):
        append_fixture_events(path, RULES)
