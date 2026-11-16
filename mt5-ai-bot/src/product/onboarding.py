"""Read-only MT5 discovery and DEMO account onboarding.

This module never accepts brokerage credentials, switches accounts, or sends orders.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import time
from typing import Any, Iterable


COMMON_TERMINALS = (
    Path(r"C:\Program Files\MetaTrader 5\terminal64.exe"),
    Path(r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe"),
)


def discover_terminals(
    *,
    candidates: Iterable[Path] = COMMON_TERMINALS,
    local_app_data: Path | None = None,
) -> list[str]:
    """Return unique, absolute terminal executables from bounded known locations."""
    found: set[Path] = set()
    for candidate in candidates:
        if candidate.is_file():
            found.add(candidate.resolve())
    root = local_app_data
    if root is None:
        value = os.environ.get("LOCALAPPDATA")
        root = Path(value) if value else None
    programs = root / "Programs" if root else None
    if programs and programs.is_dir():
        for candidate in programs.glob("*/terminal64.exe"):
            if candidate.is_file():
                found.add(candidate.resolve())
    return [str(path) for path in sorted(found, key=lambda item: str(item).lower())]


def _positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and number > 0


def _masked_login(login: Any) -> str:
    value = str(login) if login is not None else ""
    return "••••" + value[-4:] if value else "Unavailable"


def inspect_existing_demo(
    api,
    terminal_path: Path,
    *,
    symbol: str = "EURUSD",
    now_s: float | None = None,
) -> dict[str, Any]:
    """Verify the already authenticated terminal without logging in or trading."""
    terminal_path = terminal_path.resolve()
    if not terminal_path.is_file() or terminal_path.name.lower() != "terminal64.exe":
        return _failure("We could not find the selected MetaTrader 5 terminal.")
    if not api.initialize(path=str(terminal_path)):
        return _failure("Open MetaTrader 5, sign in to your DEMO account, then try again.")
    try:
        terminal = api.terminal_info()
        account = api.account_info()
        checks: list[dict[str, Any]] = []

        connected = bool(terminal and getattr(terminal, "connected", False))
        checks.append(_check("Terminal connection", connected,
                             "Connected" if connected else "MetaTrader 5 is offline"))

        is_demo = bool(account and getattr(account, "trade_mode", None)
                       == api.ACCOUNT_TRADE_MODE_DEMO)
        checks.append(_check("Account type", is_demo,
                             "Verified DEMO" if is_demo else "This is not a DEMO account"))

        info = api.symbol_info(symbol) if connected else None
        if info is not None and not bool(getattr(info, "visible", False)):
            api.symbol_select(symbol, True)
            info = api.symbol_info(symbol)
        available = bool(info and getattr(info, "visible", False))
        checks.append(_check("EUR/USD availability", available,
                             "Available" if available else "EUR/USD is unavailable in Market Watch"))

        tick = api.symbol_info_tick(symbol) if available else None
        valid_quote = bool(tick and _positive(getattr(tick, "bid", None))
                           and _positive(getattr(tick, "ask", None))
                           and float(tick.ask) >= float(tick.bid))
        checks.append(_check("Live quote", valid_quote,
                             "Bid and ask received" if valid_quote else "No valid bid/ask quote"))

        trade_allowed = bool(terminal and getattr(terminal, "trade_allowed", False)
                             and account and getattr(account, "trade_allowed", False))
        checks.append(_check("Broker trading permission", trade_allowed,
                             "Available for later DEMO review" if trade_allowed
                             else "Trading permission is currently disabled"))

        raw_tick_seconds = getattr(tick, "time", None) if tick else None
        receipt = time.time() if now_s is None else now_s
        raw_age = receipt - float(raw_tick_seconds) if _positive(raw_tick_seconds) else None
        clock_certified = False
        checks.append(_check(
            "Execution clock",
            False,
            "Quote-time certification is still required before DEMO execution",
        ))

        identity = None
        masked = "Unavailable"
        server = "Unavailable"
        if account is not None:
            login = getattr(account, "login", None)
            raw_server = getattr(account, "server", None)
            if login is not None and isinstance(raw_server, str) and raw_server.strip():
                server = raw_server.strip()
                masked = _masked_login(login)
                identity = hashlib.sha256(
                    f"{login}|{server}".encode("utf-8")
                ).hexdigest()

        account_verified = connected and is_demo and available and valid_quote and identity is not None
        blockers = [item["detail"] for item in checks if not item["passed"]]
        return {
            "schema": "emtifize-onboarding-v1",
            "account_verified": account_verified,
            "demo_only": True,
            "execution_allowed": False,
            "execution_blocked_reason": (
                "DEMO execution stays locked until quote-time and product safety review pass."
            ),
            "terminal_path": str(terminal_path),
            "account_fingerprint": identity,
            "account_label": masked,
            "server": server,
            "symbol": symbol,
            "checks": checks,
            "blockers": blockers,
            "quote": {
                "received": valid_quote,
                "raw_provider_seconds": raw_tick_seconds,
                "host_receipt_seconds": receipt,
                "raw_age_seconds": raw_age,
                "clock_certified": clock_certified,
            },
        }
    finally:
        api.shutdown()


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _failure(message: str) -> dict[str, Any]:
    return {
        "schema": "emtifize-onboarding-v1",
        "account_verified": False,
        "demo_only": True,
        "execution_allowed": False,
        "execution_blocked_reason": message,
        "checks": [],
        "blockers": [message],
    }
