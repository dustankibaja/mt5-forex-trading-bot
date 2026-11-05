#!/usr/bin/env python3
"""Safety preflight: verify MT5 is connected to a DEMO account.

Never logs in, places orders, or prints an account identifier or password.
"""
from __future__ import annotations

import sys

import MetaTrader5 as mt5


def validate_demo_environment(api=mt5) -> tuple[bool, str]:
    """Small injectable check, isolated from the actual trading engine."""
    if not api.initialize():
        return False, "MT5 terminal not reachable. Open the MT5 Windows desktop app."
    try:
        terminal = api.terminal_info()
        if terminal is None or not terminal.connected:
            return False, "MT5 terminal is offline or disconnected."
        account = api.account_info()
        if account is None:
            return False, "No MT5 account is signed in."
        if getattr(account, "trade_mode", None) != api.ACCOUNT_TRADE_MODE_DEMO:
            return False, (
                "STOP: account is NOT classified as DEMO. "
                "Sign in to a demo broker account before continuing."
            )
        return True, "MT5 connected to a DEMO account. Safe for read-only dry-run tests."
    finally:
        api.shutdown()


def main() -> int:
    passed, message = validate_demo_environment()
    print(message)
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
