from copy import deepcopy
import math
from datetime import datetime, timedelta, timezone
import pytest
from src.product.natural_language import LocalRuleInterpreter, proposal_to_strategy
from src.product.strategy_evaluator import CandleValidationError, validate_candles
from src.product.strategy_spec import StrategyValidationError, validate_strategy

def _ema(period): return {"type":"indicator","indicator":"EMA","period":period}
def _comparison(left, operator, right): return {"type":"comparison","left":left,"operator":operator,"right":right}
def strategy():
    return {"schema_version":"1.0.0","strategy_id":"teach-test-demo","version":1,"name":"Test","description":"","symbol":"EURUSD","timeframe":"H1","evaluation":"completed_candle","long_entry":{"type":"group","operator":"AND","conditions":[_comparison(_ema(2),"crosses_above",_ema(3))]},"short_entry":{"type":"group","operator":"AND","conditions":[_comparison(_ema(2),"crosses_below",_ema(3))]},"session":{"timezone":"UTC","start":"00:00","end":"23:59"},"risk":{"risk_per_trade_percent":0.25,"maximum_simultaneous_positions":1},"exits":{"stop_loss_pips":20,"take_profit_pips":40,"opposite_signal":True,"maximum_holding_candles":24},"confirmed_for_testing":False}
def candles(values):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    return [{"timestamp":(start+timedelta(hours=i)).isoformat().replace("+00:00","Z"),"open":v,"high":v+.1,"low":v-.1,"close":v,"complete":True,"source":"fixture","price_basis":"mid_bid_ask"} for i,v in enumerate(values)]

def test_complete_ema_description_becomes_unconfirmed_valid_schema():
    text = "Buy EURUSD when the 20 EMA crosses above the 50 EMA on H1. Sell when the 20 EMA crosses below the 50 EMA. Use a 20-pip stop loss, a 40-pip take profit, and risk 0.25% per trade."
    proposal = LocalRuleInterpreter().interpret(text)
    assert proposal["state"] == "draft_complete"
    assert proposal["external_transmission"] is False
    result = proposal_to_strategy(proposal, strategy_id="teach-ema-demo", name="Taught EMA")
    assert result["confirmed_for_testing"] is False
    assert result["configuration_hash"]

def test_rsi_filter_and_clarification_workflow():
    first = LocalRuleInterpreter().interpret("Buy when RSI goes above 30.")
    assert first["state"] == "clarification_pending"
    assert first["ambiguous_instructions"]
    explicit = LocalRuleInterpreter().interpret("Buy when RSI 14 crosses above 30 and price is above EMA 200 on H1. Use a 20-pip stop loss, a 40-pip take profit, and risk 0.25% per trade.")
    assert explicit["parsed_facts"]["long"]["operator"] == "AND"
    assert "short" in explicit["missing_required_fields"]

@pytest.mark.parametrize("text", ["Use smart money concepts", "Trade subjective support and resistance", "Run custom Python", "Use martingale"])
def test_unsupported_subjective_or_unsafe_language_is_visible(text):
    result = LocalRuleInterpreter().interpret(text)
    assert result["unsupported_instructions"]
    assert result["state"] == "clarification_pending"

def test_nonfinite_boolean_fractional_and_inconsistent_operands_rejected():
    raw = strategy(); raw["risk"]["risk_per_trade_percent"] = math.nan
    with pytest.raises(StrategyValidationError, match="finite"): validate_strategy(raw)
    raw = strategy(); raw["version"] = True
    with pytest.raises(StrategyValidationError, match="version"): validate_strategy(raw)
    raw = strategy(); raw["long_entry"]["conditions"][0]["left"]["period"] = 2.5
    with pytest.raises(StrategyValidationError, match="integer"): validate_strategy(raw)
    raw = strategy(); raw["long_entry"]["conditions"][0]["left"]["value"] = 7
    with pytest.raises(StrategyValidationError, match="inconsistent"): validate_strategy(raw)

def test_candles_reject_nonfinite_alignment_missing_and_mixed_provenance():
    data = candles([1, 2, 3, 4]); data[1]["close"] = math.inf
    with pytest.raises(CandleValidationError, match="finite"): validate_candles(data)
    data = candles([1, 2, 3, 4]); data[2]["timestamp"] = "2026-01-01T02:30:00Z"
    with pytest.raises(CandleValidationError, match="aligned"): validate_candles(data)
    data = candles([1, 2, 3, 4]); data.pop(2)
    with pytest.raises(CandleValidationError, match="missing"): validate_candles(data)
    data = candles([1, 2, 3, 4]); data[-1]["source"] = "other"
    with pytest.raises(CandleValidationError, match="consistent"): validate_candles(data)

def test_complexity_limit_rejects_abuse():
    raw = strategy()
    leaf = raw["long_entry"]["conditions"][0]
    raw["long_entry"] = {"type":"group","operator":"AND","conditions":[deepcopy(leaf) for _ in range(129)]}
    with pytest.raises(StrategyValidationError, match="complexity"): validate_strategy(raw)

def test_mixed_ema_sma_is_preserved_exactly():
    p = LocalRuleInterpreter().interpret("Buy when 20 EMA crosses above 50 SMA on H1. Sell when 20 SMA crosses below 50 EMA. Use a 20 pip stop, 40 pip take profit, and risk 0.25%.")
    assert p["parsed_facts"]["long"]["right"]["indicator"] == "SMA"
    assert p["parsed_facts"]["short"]["left"]["indicator"] == "SMA"
    assert p["parsed_facts"]["short"]["right"]["indicator"] == "EMA"

def test_partial_match_with_extra_condition_is_not_accepted():
    p = LocalRuleInterpreter().interpret("Buy when 20 EMA crosses above 50 EMA and MACD crosses above its signal on H1. Sell when 20 EMA crosses below 50 EMA. Use a 20 pip stop, 40 pip take profit, and risk 0.25%.")
    assert p["state"] == "clarification_pending"
    assert "macd" in p["unsupported_instructions"]
