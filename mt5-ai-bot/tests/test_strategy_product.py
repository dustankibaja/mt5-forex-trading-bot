from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from src.product.strategy_evaluator import CandleValidationError, evaluate, explain_signal, preview
from src.product.strategy_spec import StrategyValidationError, explain_strategy, validate_strategy


def ema(period: int) -> dict:
    return {"type": "indicator", "indicator": "EMA", "period": period}


def comparison(left: dict, operator: str, right: dict) -> dict:
    return {"type": "comparison", "left": left, "operator": operator, "right": right}


def strategy() -> dict:
    return {
        "schema_version": "1.0.0", "strategy_id": "ema-cross-demo", "version": 1,
        "name": "EMA crossover", "description": "Controlled fixture strategy",
        "symbol": "EURUSD", "timeframe": "H1", "evaluation": "completed_candle",
        "long_entry": {"type": "group", "operator": "AND", "conditions": [comparison(ema(2), "crosses_above", ema(3))]},
        "short_entry": {"type": "group", "operator": "AND", "conditions": [comparison(ema(2), "crosses_below", ema(3))]},
        "session": {"timezone": "UTC", "start": "00:00", "end": "23:59"},
        "risk": {"risk_per_trade_percent": 0.25, "maximum_simultaneous_positions": 1},
        "exits": {"stop_loss_pips": 20, "take_profit_pips": 40, "opposite_signal": True, "maximum_holding_candles": 24},
        "confirmed_for_testing": True,
    }


def candles(closes: list[float]) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"timestamp": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"), "open": close, "high": close + .001, "low": close - .001, "close": close, "complete": True, "source": "controlled-fixture", "price_basis": "mid_bid_ask"} for i, close in enumerate(closes)]


def test_validate_hash_explain_and_edit_changes_hash():
    first = validate_strategy(strategy())
    second_raw = deepcopy(first); second_raw.pop("configuration_hash"); second_raw["long_entry"]["conditions"][0]["left"]["period"] = 4
    second = validate_strategy(second_raw)
    assert first["configuration_hash"] != second["configuration_hash"]
    assert "completed EURUSD H1 candle" in explain_strategy(first)
    assert "cannot place broker orders" in explain_strategy(first)


def test_nested_conditions_and_invalid_risk():
    raw = strategy()
    raw["long_entry"] = {"type": "group", "operator": "OR", "conditions": [raw["long_entry"], comparison({"type": "price", "field": "close"}, "greater_than", {"type": "price", "field": "previous_high"})]}
    assert validate_strategy(raw)["long_entry"]["operator"] == "OR"
    raw["risk"]["risk_per_trade_percent"] = 50
    with pytest.raises(StrategyValidationError, match="at most"):
        validate_strategy(raw)


def test_exact_crossover_timing_neutral_and_replay():
    data = candles([4, 3, 2, 1, 2, 4])
    result = evaluate(strategy(), data, evaluated_at="2026-02-01T00:00:00Z")
    again = evaluate(strategy(), deepcopy(data), evaluated_at="2026-02-01T00:00:00Z")
    assert result == again
    assert result["decision"] == "long"
    comparison_result = result["long"]["children"][0]
    assert comparison_result["previous_left"] <= comparison_result["previous_right"]
    neutral = evaluate(strategy(), candles([1, 2, 3, 4, 5, 6]))
    assert neutral["decision"] == "neutral"
    assert result["execution_enabled"] is False


def test_warmup_missing_and_incomplete_candles_rejected():
    with pytest.raises(CandleValidationError, match="warm-up"):
        evaluate(strategy(), candles([1, 2, 3]))
    missing = candles([1, 2, 3, 4]); missing[2].pop("close")
    with pytest.raises(CandleValidationError, match="malformed"):
        evaluate(strategy(), missing)
    incomplete = candles([1, 2, 3, 4]); incomplete[-1]["complete"] = False
    with pytest.raises(CandleValidationError, match="incomplete"):
        evaluate(strategy(), incomplete)


def test_malformed_malicious_and_conflicting_hash_rejected():
    raw = strategy(); raw["python"] = "import os; os.system('bad')"
    with pytest.raises(StrategyValidationError, match="unsupported"):
        validate_strategy(raw)
    hashed = validate_strategy(strategy()); hashed["name"] = "tampered"
    with pytest.raises(StrategyValidationError, match="hash"):
        validate_strategy(hashed)


def test_signal_preview_is_not_profitability_backtest():
    result = preview(strategy(), candles([4, 3, 2, 1, 2, 4, 5, 4, 2]))
    assert result["evaluated_candle_count"] + result["warmup_rejected_count"] == 8
    assert result["buy_signal_count"] >= 1
    assert result["profitability_included"] is False
    assert result["execution_enabled"] is False


def test_signal_explanation_preserves_completed_candle_details_and_warmup_reason():
    explanation = explain_signal(strategy(), candles([4, 3, 2, 1, 2, 4]))
    assert explanation["display_decision"] == "BUY"
    assert explanation["timeframe"] == "H1" and explanation["source"] == "controlled-fixture"
    assert explanation["execution_enabled"] is False and explanation["warmup_required"] is False
    warmup = explain_signal(strategy(), candles([1, 2, 3]))
    assert warmup["display_decision"] == "NO SIGNAL"
    assert warmup["reason_code"] == "INDICATOR_WARM_UP"
    assert warmup["warmup_required"] is True
