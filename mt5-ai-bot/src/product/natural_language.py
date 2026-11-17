"""Provider-independent strategy teaching boundary and limited local fallback."""
from __future__ import annotations
import re
from copy import deepcopy
from typing import Any, Protocol
from .strategy_spec import validate_strategy

MAX_DESCRIPTION = 4000

class InterpretationProvider(Protocol):
    name: str
    def interpret(self, text: str, previous: dict[str, Any] | None = None) -> dict[str, Any]: ...

def _indicator(name: str, period: int) -> dict[str, Any]:
    return {"type": "indicator", "indicator": name, "period": period}

def _comparison(left: dict[str, Any], operator: str, right: dict[str, Any]) -> dict[str, Any]:
    return {"type": "comparison", "left": left, "operator": operator, "right": right}

class LocalRuleInterpreter:
    """Honest fallback for EMA/SMA/RSI prose; not arbitrary-language AI."""
    name = "local-limited-v1"
    def interpret(self, text: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip(): raise ValueError("Describe the strategy in a few sentences.")
        if len(text) > MAX_DESCRIPTION: raise ValueError("Description is too long; use 4,000 characters or fewer.")
        lower = text.lower()
        unsupported = [term for term in ("smart money", "order block", "support", "resistance", "martingale", "python", "news") if term in lower]
        facts = deepcopy((previous or {}).get("parsed_facts", {}))
        timeframe = re.search(r"\b(m15|h1|h4|d1)\b", lower)
        if timeframe: facts["timeframe"] = timeframe.group(1).upper()
        sl = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?pip\s+stop", lower)
        tp = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?pip\s+take", lower)
        risk = re.search(r"risk\s+(?:no more than\s+)?(\d+(?:\.\d+)?)\s*%", lower)
        if sl: facts["stop_loss_pips"] = float(sl.group(1))
        if tp: facts["take_profit_pips"] = float(tp.group(1))
        if risk: facts["risk_percent"] = float(risk.group(1))
        ema = re.search(r"(?:the\s+)?(\d+)\s*(ema|sma)\s+cross(?:es)?\s+above\s+(?:the\s+)?(\d+)\s*(?:ema|sma)", lower)
        below = re.search(r"(?:the\s+)?(\d+)\s*(ema|sma)\s+cross(?:es)?\s+below\s+(?:the\s+)?(\d+)\s*(?:ema|sma)", lower)
        rsi = re.search(r"rsi\s*(\d+)\s+cross(?:es)?\s+above\s+(\d+(?:\.\d+)?)", lower)
        trend = re.search(r"price\s+is\s+above\s+(?:the\s+)?(\d+)\s*(ema|sma)", lower)
        if ema: facts["long"] = _comparison(_indicator(ema.group(2).upper(), int(ema.group(1))), "crosses_above", _indicator(ema.group(2).upper(), int(ema.group(3))))
        if below: facts["short"] = _comparison(_indicator(below.group(2).upper(), int(below.group(1))), "crosses_below", _indicator(below.group(2).upper(), int(below.group(3))))
        if rsi:
            rule = _comparison(_indicator("RSI", int(rsi.group(1))), "crosses_above", {"type": "constant", "value": float(rsi.group(2))})
            if trend:
                filter_rule = _comparison({"type": "price", "field": "close"}, "greater_than", _indicator(trend.group(2).upper(), int(trend.group(1))))
                rule = {"type": "group", "operator": "AND", "conditions": [rule, filter_rule]}
            facts["long"] = rule
        missing, questions = [], []
        for key, question in (("timeframe", "Which timeframe should I use: M15, H1, H4 or D1?"), ("long", "What exact BUY condition should generate a signal?"), ("short", "What exact SELL condition should generate a signal?"), ("stop_loss_pips", "How many pips should the stop loss be?"), ("take_profit_pips", "How many pips should the take profit be?"), ("risk_percent", "What percentage should be risked per trade?")):
            if key not in facts: missing.append(key); questions.append(question)
        ambiguities = []
        if re.search(r"rsi\s*(?:goes|is)\s+above", lower): ambiguities.append("RSI level wording is ambiguous: choose crosses above or remains above.")
        if "buy" in lower and "sell" in lower and facts.get("long") == facts.get("short"): ambiguities.append("BUY and SELL rules conflict.")
        return {"provider": self.name, "external_transmission": False, "state": "draft_complete" if not missing and not unsupported and not ambiguities else "clarification_pending", "parsed_facts": facts, "suggested_defaults": {"session": "00:00-23:59 UTC", "max_positions": 1, "maximum_holding_candles": 24, "opposite_signal": True}, "missing_required_fields": missing, "unresolved_questions": questions, "ambiguous_instructions": ambiguities, "unsupported_instructions": unsupported, "limitation": "Local fallback understands explicit EMA/SMA crossovers and RSI cross-above with an optional EMA/SMA price filter. It does not understand arbitrary trading prose."}

def proposal_to_strategy(proposal: dict[str, Any], *, strategy_id: str, name: str) -> dict[str, Any]:
    if proposal.get("state") != "draft_complete": raise ValueError("Resolve every clarification before backend validation.")
    facts, defaults = proposal["parsed_facts"], proposal["suggested_defaults"]
    def group(rule: dict[str, Any]) -> dict[str, Any]: return rule if rule.get("type") == "group" else {"type": "group", "operator": "AND", "conditions": [rule]}
    raw = {"schema_version":"1.0.0","strategy_id":strategy_id,"version":1,"name":name,"description":"Created with Teach My Bot local fallback.","symbol":"EURUSD","timeframe":facts["timeframe"],"evaluation":"completed_candle","long_entry":group(facts["long"]),"short_entry":group(facts["short"]),"session":{"timezone":"UTC","start":"00:00","end":"23:59"},"risk":{"risk_per_trade_percent":facts["risk_percent"],"maximum_simultaneous_positions":defaults["max_positions"]},"exits":{"stop_loss_pips":facts["stop_loss_pips"],"take_profit_pips":facts["take_profit_pips"],"opposite_signal":defaults["opposite_signal"],"maximum_holding_candles":defaults["maximum_holding_candles"]},"confirmed_for_testing":False}
    return validate_strategy(raw)
