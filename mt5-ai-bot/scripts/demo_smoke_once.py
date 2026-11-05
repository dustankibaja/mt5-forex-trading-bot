#!/usr/bin/env python3
"""SEPARATE, locally authorized, one-shot MT5 broker DEMO execution smoke test.

Unattended Emtifize ATR worker stays DRY-RUN. This script is never invoked
from the phone or API. This does NOT demonstrate a profitable strategy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import MetaTrader5 as mt5

from src.execution.demo_order_firewall import (
    DemoSafetyError,
    execute_one_demo_smoke,
    initialize_broker_pin,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--pin-demo-account", action="store_true")
    command.add_argument("--execute-one-demo-smoke", action="store_true")
    parser.add_argument("--confirm", default="", help="Local operator consent")
    args = parser.parse_args()
    if args.execute_one_demo_smoke and args.confirm != "DEMO_ONLY_ONE_TINY_ORDER":
        print("BLOCKED: local DEMO-only operator confirmation required.")
        return 2
    if not mt5.initialize():
        print("MT5 desktop unavailable.")
        return 2
    try:
        if args.pin_demo_account:
            initialize_broker_pin(mt5)
            print("DEMO broker identity pinned locally. No order submitted.")
            return 0
        result = execute_one_demo_smoke(mt5, execute=True)
        print(json.dumps(result.public_report(), indent=2))
        print("DEMO broker history must be reconciled. Profitability NOT certified.")
        return 0 if result.status == "DEMO_ORDER_FILLED" else 3
    except DemoSafetyError as exc:
        print(f"BLOCKED: {exc}")
        return 3
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
