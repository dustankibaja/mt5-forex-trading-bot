"""Deterministic completed-candle signal evaluator with no broker dependency."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isnan
from typing import Any

import numpy as np

from .strategy_spec import StrategyValidationError, validate_strategy


class CandleValidationError(StrategyValidationError):
    pass


def _ema(values: list[float], period: int) -> list[float]:
    result = [float("nan")] * len(values)
    if len(values) < period: return result
    result[period - 1] = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for index in range(period, len(values)):
        result[index] = alpha * values[index] + (1 - alpha) * result[index - 1]
    return result


def _sma(values: list[float], period: int) -> list[float]:
    return [float("nan") if i + 1 < period else sum(values[i + 1 - period:i + 1]) / period for i in range(len(values))]


def _rsi(values: list[float], period: int) -> list[float]:
    result = [float("nan")] * len(values)
    if len(values) <= period: return result
    gains = [max(values[i] - values[i - 1], 0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0) for i in range(1, len(values))]
    avg_gain, avg_loss = sum(gains[:period]) / period, sum(losses[:period]) / period
    result[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        result[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def _atr(candles: list[dict[str, Any]], period: int) -> list[float]:
    tr = []
    for i, candle in enumerate(candles):
        previous = candle["close"] if i == 0 else candles[i - 1]["close"]
        tr.append(max(candle["high"] - candle["low"], abs(candle["high"] - previous), abs(candle["low"] - previous)))
    return _ema(tr, period)


def _series(operand: dict[str, Any], candles: list[dict[str, Any]]) -> list[float]:
    if operand["type"] == "constant": return [float(operand["value"])] * len(candles)
    if operand["type"] == "price":
        field = operand["field"]
        if field == "previous_high": return [float("nan")] + [c["high"] for c in candles[:-1]]
        if field == "previous_low": return [float("nan")] + [c["low"] for c in candles[:-1]]
        return [c[field] for c in candles]
    closes = [c["close"] for c in candles]
    name = operand["indicator"]
    if name == "EMA": return _ema(closes, int(operand["period"]))
    if name == "SMA": return _sma(closes, int(operand["period"]))
    if name == "RSI": return _rsi(closes, int(operand["period"]))
    if name == "ATR": return _atr(candles, int(operand["period"]))
    fast, slow, signal = int(operand["fast"]), int(operand["slow"]), int(operand["signal"])
    fast_s, slow_s = _ema(closes, fast), _ema(closes, slow)
    line = [float("nan") if isnan(a) or isnan(b) else a - b for a, b in zip(fast_s, slow_s)]
    first = next((i for i, v in enumerate(line) if not isnan(v)), len(line))
    signal_values = [float("nan")] * first + _ema(line[first:], signal)
    component = operand.get("component", "line")
    if component == "line": return line
    if component == "signal": return signal_values
    return [float("nan") if isnan(a) or isnan(b) else a - b for a, b in zip(line, signal_values)]


def validate_candles(candles: Any) -> list[dict[str, Any]]:
    if not isinstance(candles, list) or len(candles) < 2: raise CandleValidationError("at least two ordered completed candles are required")
    normalized, previous = [], None
    for index, raw in enumerate(candles):
        if not isinstance(raw, dict) or set(raw) != {"timestamp", "open", "high", "low", "close", "complete", "source", "price_basis"}:
            raise CandleValidationError(f"candle {index} is malformed")
        if raw["complete"] is not True: raise CandleValidationError(f"candle {index} is incomplete")
        if raw["price_basis"] not in {"mid_bid_ask", "bid", "ask"}: raise CandleValidationError(f"candle {index} price_basis is unsupported")
        try: stamp = datetime.fromisoformat(str(raw["timestamp"]).replace("Z", "+00:00"))
        except ValueError as error: raise CandleValidationError(f"candle {index} timestamp is invalid") from error
        if stamp.tzinfo is None: raise CandleValidationError(f"candle {index} timestamp must include timezone")
        if previous is not None and stamp <= previous: raise CandleValidationError("candles must be strictly ordered without duplicates")
        previous = stamp
        candle = {**raw, "timestamp": stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
        for key in ("open", "high", "low", "close"):
            try: candle[key] = float(raw[key])
            except (TypeError, ValueError) as error: raise CandleValidationError(f"candle {index}.{key} is invalid") from error
        if candle["low"] > min(candle["open"], candle["close"]) or candle["high"] < max(candle["open"], candle["close"]) or candle["low"] > candle["high"]:
            raise CandleValidationError(f"candle {index} OHLC is inconsistent")
        normalized.append(candle)
    return normalized


def _evaluate_node(node: dict[str, Any], candles: list[dict[str, Any]], index: int) -> tuple[bool, dict[str, Any]]:
    if node["type"] == "group":
        children = [_evaluate_node(child, candles, index) for child in node["conditions"]]
        passed = all(item[0] for item in children) if node["operator"] == "AND" else any(item[0] for item in children)
        return passed, {"type": "group", "operator": node["operator"], "passed": passed, "children": [item[1] for item in children]}
    left, right = _series(node["left"], candles), _series(node["right"], candles)
    values = [left[index], right[index]]
    if node["operator"].startswith("crosses_"): values += [left[index - 1], right[index - 1]]
    if any(isnan(v) for v in values): raise CandleValidationError("insufficient indicator warm-up for this signal candle")
    operator = node["operator"]
    passed = (left[index] > right[index] if operator == "greater_than" else left[index] < right[index] if operator == "less_than" else left[index - 1] <= right[index - 1] and left[index] > right[index] if operator == "crosses_above" else left[index - 1] >= right[index - 1] and left[index] < right[index])
    return passed, {"type": "comparison", "operator": operator, "passed": passed, "left": left[index], "right": right[index], "previous_left": left[index - 1], "previous_right": right[index - 1]}


def evaluate(strategy_raw: dict[str, Any], candles_raw: list[dict[str, Any]], *, evaluated_at: str | None = None) -> dict[str, Any]:
    strategy, candles = validate_strategy(strategy_raw), validate_candles(candles_raw)
    index = len(candles) - 1
    stamp = datetime.fromisoformat(candles[index]["timestamp"].replace("Z", "+00:00"))
    session = strategy["session"]
    now_hm = stamp.strftime("%H:%M")
    in_session = session["start"] <= now_hm < session["end"] if session["start"] < session["end"] else now_hm >= session["start"] or now_hm < session["end"]
    long_passed, long_details = _evaluate_node(strategy["long_entry"], candles, index)
    short_passed, short_details = _evaluate_node(strategy["short_entry"], candles, index)
    decision = "neutral"
    if in_session and long_passed != short_passed: decision = "long" if long_passed else "short"
    return {"strategy_id": strategy["strategy_id"], "strategy_version": strategy["version"], "configuration_hash": strategy["configuration_hash"], "signal_candle": candles[index]["timestamp"], "evaluated_at": evaluated_at or candles[index]["timestamp"], "decision": decision, "session_passed": in_session, "long": long_details, "short": short_details, "source": candles[index]["source"], "price_basis": candles[index]["price_basis"], "execution_enabled": False}


def preview(strategy: dict[str, Any], candles: list[dict[str, Any]]) -> dict[str, Any]:
    validated = validate_candles(candles)
    decisions, rejected = [], 0
    for end in range(2, len(validated) + 1):
        try: decisions.append(evaluate(strategy, validated[:end]))
        except CandleValidationError as error:
            if "warm-up" in str(error): rejected += 1
            else: raise
    return {"evaluated_candle_count": len(decisions), "warmup_rejected_count": rejected, "buy_signal_count": sum(d["decision"] == "long" for d in decisions), "sell_signal_count": sum(d["decision"] == "short" for d in decisions), "neutral_count": sum(d["decision"] == "neutral" for d in decisions), "signals": [{"timestamp": d["signal_candle"], "decision": d["decision"], "long_passed": d["long"]["passed"], "short_passed": d["short"]["passed"]} for d in decisions], "profitability_included": False, "execution_enabled": False}
