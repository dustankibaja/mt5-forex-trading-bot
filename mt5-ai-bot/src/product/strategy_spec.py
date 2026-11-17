"""Versioned, declarative customer strategy specification.

The schema deliberately has no executable-code escape hatch.  A future AI
proposal and the visual editor must both pass :func:`validate_strategy`.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "1.0.0"
TIMEFRAMES = {"M15", "H1", "H4", "D1"}
INDICATORS = {"EMA", "SMA", "RSI", "MACD", "ATR"}
PRICE_FIELDS = {"open", "high", "low", "close", "previous_high", "previous_low"}
OPERATORS = {"crosses_above", "crosses_below", "greater_than", "less_than"}
GROUPS = {"AND", "OR"}
TIMEZONES = {"UTC"}


class StrategyValidationError(ValueError):
    """Raised for an unsafe, incomplete, or ambiguous strategy."""


def canonical_payload(strategy: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(strategy)
    payload.pop("configuration_hash", None)
    return payload


def configuration_hash(strategy: dict[str, Any]) -> str:
    encoded = json.dumps(
        canonical_payload(strategy), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any, path: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyValidationError(f"{path} must be a number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise StrategyValidationError(f"{path} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise StrategyValidationError(f"{path} must be at most {maximum}")
    return result


def _operand(value: Any, path: str) -> None:
    if not isinstance(value, dict) or set(value) - {"type", "field", "indicator", "period", "fast", "slow", "signal", "component", "value"}:
        raise StrategyValidationError(f"{path} contains unsupported fields")
    kind = value.get("type")
    if kind == "price":
        if value.get("field") not in PRICE_FIELDS:
            raise StrategyValidationError(f"{path}.field is unsupported")
    elif kind == "constant":
        _number(value.get("value"), f"{path}.value")
    elif kind == "indicator":
        name = value.get("indicator")
        if name not in INDICATORS:
            raise StrategyValidationError(f"{path}.indicator is unsupported")
        if name == "MACD":
            fast = int(_number(value.get("fast"), f"{path}.fast", minimum=1, maximum=500))
            slow = int(_number(value.get("slow"), f"{path}.slow", minimum=2, maximum=500))
            _number(value.get("signal"), f"{path}.signal", minimum=1, maximum=500)
            if fast >= slow:
                raise StrategyValidationError(f"{path}.fast must be less than slow")
            if value.get("component", "line") not in {"line", "signal", "histogram"}:
                raise StrategyValidationError(f"{path}.component is unsupported")
        else:
            _number(value.get("period"), f"{path}.period", minimum=1, maximum=500)
    else:
        raise StrategyValidationError(f"{path}.type is unsupported")


def _condition(node: Any, path: str, depth: int = 0) -> None:
    if depth > 8 or not isinstance(node, dict):
        raise StrategyValidationError(f"{path} is too deeply nested or malformed")
    kind = node.get("type")
    if kind == "group":
        if set(node) != {"type", "operator", "conditions"} or node.get("operator") not in GROUPS:
            raise StrategyValidationError(f"{path} group is invalid")
        children = node.get("conditions")
        if not isinstance(children, list) or not children:
            raise StrategyValidationError(f"{path}.conditions cannot be empty")
        for index, child in enumerate(children):
            _condition(child, f"{path}.conditions[{index}]", depth + 1)
    elif kind == "comparison":
        if set(node) != {"type", "left", "operator", "right"} or node.get("operator") not in OPERATORS:
            raise StrategyValidationError(f"{path} comparison is invalid")
        _operand(node.get("left"), f"{path}.left")
        _operand(node.get("right"), f"{path}.right")
    else:
        raise StrategyValidationError(f"{path}.type is unsupported")


def validate_strategy(raw: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StrategyValidationError("strategy must be an object")
    allowed = {"schema_version", "strategy_id", "version", "name", "description", "symbol", "timeframe", "evaluation", "long_entry", "short_entry", "session", "risk", "exits", "confirmed_for_testing", "configuration_hash"}
    unknown = set(raw) - allowed
    if unknown:
        raise StrategyValidationError(f"unsupported top-level fields: {sorted(unknown)}")
    strategy = deepcopy(raw)
    if strategy.get("schema_version") != SCHEMA_VERSION:
        raise StrategyValidationError(f"schema_version must be {SCHEMA_VERSION}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", str(strategy.get("strategy_id", ""))):
        raise StrategyValidationError("strategy_id must be a stable lowercase identifier")
    if not isinstance(strategy.get("version"), int) or strategy["version"] < 1:
        raise StrategyValidationError("version must be a positive immutable integer")
    if not str(strategy.get("name", "")).strip() or len(str(strategy["name"])) > 80:
        raise StrategyValidationError("name is required and must be at most 80 characters")
    if strategy.get("symbol") != "EURUSD":
        raise StrategyValidationError("Milestone B supports EURUSD only")
    if strategy.get("timeframe") not in TIMEFRAMES:
        raise StrategyValidationError("timeframe is unsupported")
    if strategy.get("evaluation") != "completed_candle":
        raise StrategyValidationError("evaluation must be completed_candle")
    _condition(strategy.get("long_entry"), "long_entry")
    _condition(strategy.get("short_entry"), "short_entry")
    session = strategy.get("session")
    if not isinstance(session, dict) or set(session) != {"timezone", "start", "end"} or session.get("timezone") not in TIMEZONES:
        raise StrategyValidationError("session must define UTC timezone, start, and end")
    for key in ("start", "end"):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(session.get(key, ""))):
            raise StrategyValidationError(f"session.{key} must be HH:MM")
    risk = strategy.get("risk")
    if not isinstance(risk, dict) or set(risk) != {"risk_per_trade_percent", "maximum_simultaneous_positions"}:
        raise StrategyValidationError("risk is incomplete")
    _number(risk.get("risk_per_trade_percent"), "risk.risk_per_trade_percent", minimum=0.01, maximum=2.0)
    positions = _number(risk.get("maximum_simultaneous_positions"), "risk.maximum_simultaneous_positions", minimum=1, maximum=10)
    if int(positions) != positions:
        raise StrategyValidationError("maximum_simultaneous_positions must be an integer")
    exits = strategy.get("exits")
    if not isinstance(exits, dict) or set(exits) != {"stop_loss_pips", "take_profit_pips", "opposite_signal", "maximum_holding_candles"}:
        raise StrategyValidationError("exits are incomplete")
    _number(exits.get("stop_loss_pips"), "exits.stop_loss_pips", minimum=0.1, maximum=10000)
    _number(exits.get("take_profit_pips"), "exits.take_profit_pips", minimum=0.1, maximum=10000)
    _number(exits.get("maximum_holding_candles"), "exits.maximum_holding_candles", minimum=1, maximum=100000)
    if not isinstance(exits.get("opposite_signal"), bool):
        raise StrategyValidationError("exits.opposite_signal must be true or false")
    expected = configuration_hash(strategy)
    supplied = strategy.get("configuration_hash")
    if verify_hash and supplied is not None and supplied != expected:
        raise StrategyValidationError("configuration_hash does not match the strategy")
    strategy["configuration_hash"] = expected
    return strategy


def explain_strategy(strategy: dict[str, Any]) -> str:
    strategy = validate_strategy(strategy)
    def operand(value: dict[str, Any]) -> str:
        if value["type"] == "price": return value["field"].replace("_", " ")
        if value["type"] == "constant": return str(value["value"])
        if value["indicator"] == "MACD": return f"MACD {value['fast']}/{value['slow']}/{value['signal']} {value.get('component', 'line')}"
        return f"{value['period']}-period {value['indicator']}"
    def condition(value: dict[str, Any]) -> str:
        if value["type"] == "group":
            return f" {value['operator']} ".join(f"({condition(item)})" for item in value["conditions"])
        return f"{operand(value['left'])} {value['operator'].replace('_', ' ')} {operand(value['right'])}"
    exits = strategy["exits"]
    risk = strategy["risk"]
    return (
        f"On each completed {strategy['symbol']} {strategy['timeframe']} candle, generate a BUY signal when {condition(strategy['long_entry'])}. "
        f"Generate a SELL signal when {condition(strategy['short_entry'])}. Evaluate only from {strategy['session']['start']} to {strategy['session']['end']} {strategy['session']['timezone']}. "
        f"Use a {exits['stop_loss_pips']}-pip stop loss and {exits['take_profit_pips']}-pip take profit; risk at most {risk['risk_per_trade_percent']}% per trade with at most {risk['maximum_simultaneous_positions']} simultaneous position(s). "
        f"{'Exit on an opposite signal.' if exits['opposite_signal'] else 'Do not exit solely on an opposite signal.'} Maximum holding period: {exits['maximum_holding_candles']} candles. "
        "Signals are informational and cannot place broker orders in Product Beta Milestone B."
    )
