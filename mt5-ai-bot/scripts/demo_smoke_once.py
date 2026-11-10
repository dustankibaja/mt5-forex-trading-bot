#!/usr/bin/env python3
"""SEPARATE, locally authorized, one-shot MT5 broker DEMO execution smoke test.

Unattended Emtifize ATR worker stays DRY-RUN. This script is never invoked
from the phone or API. This does NOT demonstrate a profitable strategy.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import MetaTrader5 as mt5

from src.execution.demo_order_firewall import (
    DemoSafetyError,
    execute_one_demo_smoke,
)
from src.execution.demo_reconciliation import audit_demo_smoke


def canonical_runtime() -> Path:
    return Path.home() / "mt5-forex-trading-bot" / "mt5-ai-bot" / "runtime"


def require_existing_ledger(ledger: Path) -> None:
    try:
        with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise DemoSafetyError("Canonical smoke ledger failed integrity check")
            connection.execute("SELECT account_digest, status FROM smoke_intents LIMIT 1")
            connection.execute("SELECT order_ticket, deal_ticket FROM smoke_receipts LIMIT 1")
    except sqlite3.Error as exc:
        raise DemoSafetyError("Canonical smoke ledger is missing, damaged, or unprovisioned") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--pin-demo-account", action="store_true")
    command.add_argument("--execute-one-demo-smoke", action="store_true")
    command.add_argument("--audit-demo-smoke", action="store_true")
    parser.add_argument("--confirm", default="", help="Local operator consent")
    args = parser.parse_args()
    if args.execute_one_demo_smoke and args.confirm != "DEMO_ONLY_ONE_TINY_ORDER":
        print("BLOCKED: local DEMO-only operator confirmation required.")
        return 2
    runtime = canonical_runtime()
    pin = runtime / "demo_broker_pin.json"
    ledger = runtime / "demo_smoke_ledger.sqlite3"
    if args.pin_demo_account:
        print("BLOCKED: account pin provisioning requires reviewed canonical runtime and broker history.")
        return 3
    if args.execute_one_demo_smoke:
        try:
            require_existing_ledger(ledger)
        except DemoSafetyError as exc:
            print(f"BLOCKED: {exc}")
            return 3
    if not mt5.initialize():
        print("MT5 desktop unavailable.")
        return 2
    try:
        if args.audit_demo_smoke:
            print(json.dumps(audit_demo_smoke(mt5, pin_path=pin, ledger_path=ledger), indent=2))
            return 0
        result = execute_one_demo_smoke(
            mt5, execute=True, pin_path=pin, ledger_path=ledger,
            manual_kill_switch=runtime.parent / "KILL_SWITCH",
            remote_pause_path=runtime / "remote_pause.flag",
            existing_ledger_only=True,
        )
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
