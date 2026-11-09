"""Read-only broker evidence for a previously attempted DEMO smoke order."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from src.execution.demo_order_firewall import (
    DEFAULT_LEDGER, DEFAULT_PIN, MAGIC, SYMBOL, DemoSafetyError, _require_pin,
)


def _pinned_demo(api, pin_path: Path) -> str:
    terminal, account = api.terminal_info(), api.account_info()
    if (not getattr(terminal, "connected", False)
            or getattr(account, "trade_mode", None) != api.ACCOUNT_TRADE_MODE_DEMO):
        raise DemoSafetyError("Connected pinned DEMO account required for audit")
    return _require_pin(account, pin_path)


def audit_demo_smoke(api, *, pin_path: Path = DEFAULT_PIN,
                     ledger_path: Path = DEFAULT_LEDGER) -> dict:
    """Correlate broker history without changing either the ledger or account."""
    digest = _pinned_demo(api, pin_path)
    report = {"execution_locked": True, "status": "UNVERIFIED"}
    try:
        con = sqlite3.connect(ledger_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = con.execute(
                """SELECT i.status, r.order_ticket, r.deal_ticket
                   FROM smoke_intents i LEFT JOIN smoke_receipts r
                   USING (account_digest, day_utc, symbol)
                   WHERE i.account_digest=? AND i.symbol=? LIMIT 2""",
                (digest, SYMBOL),
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return report
    if len(rows) != 1:
        return report
    report["ledger_status"], order_ticket, deal_ticket = rows[0]
    if not order_ticket or not deal_ticket:
        return report

    orders = api.history_orders_get(ticket=order_ticket)
    fills = api.history_deals_get(ticket=order_ticket)
    if not orders or len(orders) != 1 or not fills:
        return report
    order = orders[0]
    if order.ticket != order_ticket or order.symbol != SYMBOL or order.magic != MAGIC:
        return report
    opening = [deal for deal in fills if deal.ticket == deal_ticket]
    if len(opening) != 1 or not opening[0].position_id:
        return report
    position_id = opening[0].position_id
    if any(d.order != order_ticket or d.position_id != position_id
           or d.symbol != SYMBOL or d.magic != MAGIC or d.entry != api.DEAL_ENTRY_IN
           or d.type != api.DEAL_TYPE_BUY for d in fills):
        return report

    deals = api.history_deals_get(position=position_id)
    positions, pending = api.positions_get(), api.orders_get()
    if not deals or positions is None or pending is None:
        return report
    if _pinned_demo(api, pin_path) != digest:
        return report
    report["order_state"] = int(order.state)
    if any(o.ticket == order_ticket or o.position_id == position_id for o in pending):
        return {**report, "status": "PENDING_EXPOSURE"}
    if any(p.identifier == position_id for p in positions):
        return {**report, "status": "OPEN_EXPOSURE"}

    entries = {d.ticket for d in fills}
    closes = [d for d in deals if d.entry == api.DEAL_ENTRY_OUT]
    if (order.state not in (api.ORDER_STATE_FILLED, api.ORDER_STATE_CANCELED,
                            api.ORDER_STATE_EXPIRED)
            or not closes or len({d.ticket for d in deals}) != len(deals)
            or {d.ticket for d in deals if d.entry == api.DEAL_ENTRY_IN} != entries
            or any(d.position_id != position_id or d.symbol != SYMBOL
                   or d.entry not in (api.DEAL_ENTRY_IN, api.DEAL_ENTRY_OUT)
                   or not math.isfinite(d.volume) or d.volume <= 0 for d in deals)
            or any(d.type != api.DEAL_TYPE_SELL for d in closes)):
        return report
    filled = sum(d.volume for d in fills)
    history_filled = sum(d.volume for d in deals if d.entry == api.DEAL_ENTRY_IN)
    closed = sum(d.volume for d in closes)
    if not all(math.isclose(filled, volume, rel_tol=0, abs_tol=1e-8)
               for volume in (history_filled, closed)):
        return report
    return {**report, "status": "CLOSURE_EVIDENCE", "filled_volume": filled,
            "closed_volume": closed, "closing_deals": len(closes)}
