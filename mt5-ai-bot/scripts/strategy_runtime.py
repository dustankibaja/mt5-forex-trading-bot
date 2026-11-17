"""JSON-in/JSON-out strategy validation and preview runtime."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from src.product.strategy_evaluator import preview
from src.product.strategy_spec import explain_strategy, validate_strategy

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "preview"))
    parser.add_argument("strategy", type=Path)
    parser.add_argument("--candles", type=Path)
    args = parser.parse_args()
    try:
        strategy = validate_strategy(json.loads(args.strategy.read_text(encoding="utf-8")))
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
