#!/usr/bin/env python3
"""Inspect MT5 broker DEMO order constraints; sends ZERO orders.

Readiness does NOT grant execution, nor does it prove strategy profitability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

import MetaTrader5 as mt5

from src.execution.demo_readiness import inspect_demo_execution_conditions


def main() -> int:
    if not mt5.initialize():
        print("MT5 terminal unavailable. Open the Windows desktop terminal.", file=sys.stderr)
        return 2
    try:
        result = inspect_demo_execution_conditions(mt5, symbol="EURUSD")
        print(json.dumps(result.public_report(), indent=2))
        if result.ready_for_mechanical_review:
            print("Broker constraints acceptable for reviewing a future tiny DEMO-only test.")
            print("ORDER EXECUTION IS STILL DISABLED. Profitability not established.")
            return 0
        print("DEMO-order readiness blockers remain. Nothing was traded.")
        return 3
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
