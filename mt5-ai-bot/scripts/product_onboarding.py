#!/usr/bin/env python3
"""JSON interface for the local Emtifize Windows onboarding wizard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import MetaTrader5 as mt5

from src.product.onboarding import discover_terminals, inspect_existing_demo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("detect")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--terminal", type=Path, required=True)
    verify.add_argument("--symbol", default="EURUSD")
    args = parser.parse_args()

    if args.action == "detect":
        result = {"schema": "emtifize-onboarding-v1", "terminals": discover_terminals()}
    else:
        result = inspect_existing_demo(mt5, args.terminal, symbol=args.symbol)
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if args.action == "detect" or result["account_verified"] else 2


if __name__ == "__main__":
    sys.exit(main())
