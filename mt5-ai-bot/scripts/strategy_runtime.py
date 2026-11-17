"""JSON-in/JSON-out strategy validation and preview runtime."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from src.product.strategy_evaluator import preview
from src.product.strategy_spec import explain_strategy, validate_strategy
from src.product.natural_language import LocalRuleInterpreter, proposal_to_strategy

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "preview", "interpret"))
    parser.add_argument("strategy", type=Path)
    parser.add_argument("--candles", type=Path)
    args = parser.parse_args()
    try:
        def reject_constant(value): raise ValueError(f"invalid JSON numeric constant: {value}")
        payload = json.loads(args.strategy.read_text(encoding="utf-8"), parse_constant=reject_constant)
        if args.command == "interpret":
            proposal = LocalRuleInterpreter().interpret(str(payload.get("description", "")), payload.get("previous"))
            result = {"proposal": proposal, "execution_enabled": False}
            if proposal["state"] == "draft_complete": result["strategy"] = proposal_to_strategy(proposal, strategy_id=str(payload.get("strategy_id", "teach-my-bot-draft")), name=str(payload.get("name", "Taught strategy")))
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        strategy = validate_strategy(payload)
        result = {"strategy": strategy, "explanation": explain_strategy(strategy), "execution_enabled": False}
        if args.command == "preview":
            if args.candles is None: raise ValueError("--candles is required for preview")
            result["preview"] = preview(strategy, json.loads(args.candles.read_text(encoding="utf-8")))
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error), "execution_enabled": False}), file=sys.stderr)
        return 2
if __name__ == "__main__": raise SystemExit(main())
