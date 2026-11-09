"""Allowlisted, read-only MT5 DEMO account data for the private Flutter client.

The MT5 Python session stays in the existing Windows worker process; the
loopback-only API reads atomic snapshots and never connects to a broker.
Never serializes account numbers, name, server, tickets, magic, comments,
credentials, or arbitrary MT5 objects. Unavailable/stale data fail closed.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DEMO_PATH = Path("runtime/demo_account.json")
SCHEMA = 1
MAX_ROWS = 20
MAX_AGE_SECONDS = 35


def _utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("UTC timestamp must have a timezone")
    return value.astimezone(timezone.utc)


def _numeric(value, places: int = 2) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Invalid broker numeric value")
    return round(parsed, places)


def _stamp_from_epoch(value) -> str:
    return datetime.fromtimestamp(int(value), timezone.utc).isoformat()


def _write(path: str | Path, record: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as f:
            json.dump(record, f, allow_nan=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _unavailable_record(now: datetime | None = None) -> dict:
    return {"schema_version": SCHEMA, "available": False, "account_type": "unknown",
            "stale": True, "updated_at": _utc(now).isoformat(),
            "currency": None, "balance": None, "equity": None,
            "margin_free": None, "floating_pnl": None,
            "positions": [], "recent_closing_deals": []}


def invalidate_demo_snapshot(path: str | Path, *, now: datetime | None = None) -> None:
    _write(path, _unavailable_record(now))


def capture_demo_snapshot(api, path: str | Path, *, now: datetime | None = None) -> bool:
    """Capture only broker-verified DEMO account, no orders and no login data.

    Failures invalidate the previous snapshot, so broker disconnection or
    account switching cannot leave the old demo balances displayed as live.
    """
    current = _utc(now)
    try:
        terminal = api.terminal_info()
        account = api.account_info()
        if (terminal is None or not getattr(terminal, "connected", False)
                or account is None
                or getattr(account, "trade_mode", None) != api.ACCOUNT_TRADE_MODE_DEMO):
            invalidate_demo_snapshot(path, now=current)
            return False

        positions = api.positions_get()
        since = current - timedelta(days=7)
        deals = api.history_deals_get(since, current)
        if positions is None or deals is None:
            invalidate_demo_snapshot(path, now=current)
            return False

        currency = str(getattr(account, "currency", "")).strip().upper()
        if not (3 <= len(currency) <= 5 and currency.isalpha()):
            raise ValueError("Unexpected account currency")

        pos_rows = []
        for p in sorted(positions, key=lambda p: int(p.time), reverse=True)[:MAX_ROWS]:
            side = ("BUY" if p.type == api.POSITION_TYPE_BUY else
                    "SELL" if p.type == api.POSITION_TYPE_SELL else None)
            if side is None:
                continue
            pos_rows.append({
                "symbol": str(p.symbol)[:20], "side": side,
                "volume": _numeric(p.volume, 3),
                "open_price": _numeric(p.price_open, 6),
                "current_price": _numeric(p.price_current, 6),
                "profit": _numeric(p.profit),
                "opened_at": _stamp_from_epoch(p.time),
            })

        # Closing DEALS are not complete round-trip trades. Show them as such;
        # exclude deposits, credits and opening transactions.
        close_entries = {api.DEAL_ENTRY_OUT, api.DEAL_ENTRY_INOUT}
        if hasattr(api, "DEAL_ENTRY_OUT_BY"):
            close_entries.add(api.DEAL_ENTRY_OUT_BY)
        deal_rows = []
        for deal in sorted(deals, key=lambda d: int(d.time), reverse=True):
            if len(deal_rows) >= MAX_ROWS:
                break
            if deal.entry not in close_entries:
                continue
            side = ("BUY" if deal.type == api.DEAL_TYPE_BUY else
                    "SELL" if deal.type == api.DEAL_TYPE_SELL else None)
            if side is None:
                continue
            pnl = sum(_numeric(getattr(deal, field, 0.0)) for field in
                      ("profit", "commission", "swap", "fee"))
            deal_rows.append({
                "symbol": str(deal.symbol)[:20], "deal_side": side,
                "volume": _numeric(deal.volume, 3),
                "net_pnl": _numeric(pnl),
                "closed_at": _stamp_from_epoch(deal.time),
            })

        record = {
            "schema_version": SCHEMA, "available": True,
            "account_type": "demo", "stale": False,
            "updated_at": current.isoformat(),
            "currency": currency,
            "balance": _numeric(account.balance),
            "equity": _numeric(account.equity),
            "margin_free": _numeric(account.margin_free),
            "floating_pnl": _numeric(account.profit),
            "positions": pos_rows,
            "recent_closing_deals": deal_rows,
        }
        _write(path, record)
        return True
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, OSError):
        invalidate_demo_snapshot(path, now=current)
        return False


def public_demo_snapshot(path: str | Path, *, now: datetime | None = None) -> dict:
    """Strict API allowlist with 35s freshness; never return stale balances."""
    unavailable = _unavailable_record(now)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        age = (_utc(now) - stamp.astimezone(timezone.utc)).total_seconds()
        if (data.get("schema_version") != SCHEMA or
                data.get("account_type") != "demo" or
                data.get("available") is not True or not -5 <= age <= MAX_AGE_SECONDS):
            return unavailable
        currency = data["currency"]
        if not (isinstance(currency, str) and 3 <= len(currency) <= 5
                and currency.isalpha()):
            return unavailable
        balances = {key: _numeric(data[key]) for key in
                    ("balance", "equity", "margin_free", "floating_pnl")}
        positions = []
        for raw in data["positions"][:MAX_ROWS]:
            if raw["side"] not in ("BUY", "SELL"):
                continue
            positions.append({
                "symbol": str(raw["symbol"])[:20], "side": raw["side"],
                "volume": _numeric(raw["volume"], 3),
                "open_price": _numeric(raw["open_price"], 6),
                "current_price": _numeric(raw["current_price"], 6),
                "profit": _numeric(raw["profit"]),
                "opened_at": str(raw["opened_at"])[:40],
            })
        deals = []
        for raw in data["recent_closing_deals"][:MAX_ROWS]:
            if raw["deal_side"] not in ("BUY", "SELL"):
                continue
            deals.append({
                "symbol": str(raw["symbol"])[:20], "deal_side": raw["deal_side"],
                "volume": _numeric(raw["volume"], 3),
                "net_pnl": _numeric(raw["net_pnl"]),
                "closed_at": str(raw["closed_at"])[:40],
            })
        return {
            "schema_version": SCHEMA, "available": True, "stale": False,
            "account_type": "demo", "updated_at": stamp.isoformat(),
            "currency": currency, **balances,
            "positions": positions, "recent_closing_deals": deals,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, IndexError):
        return unavailable
