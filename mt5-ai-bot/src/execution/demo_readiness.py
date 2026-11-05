"""Non-trading MT5 broker readiness checks for a future DEMO-order experiment.

No order_send, broker login/logout, order_check or position mutation.
This does NOT grant execution permission, certify strategy profitability,
or change the existing DRY_RUN/require-demo safety boundary.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DemoReadiness:
    ready_for_mechanical_review: bool
    blockers: tuple[str, ...]
    symbol: str
    risk_limit_pct: float
    estimated_min_lot_stop_loss: float | None
    account_currency: str | None
    min_lot: float | None
    spread_pips: float | None
    broker_margin_at_min_lot: float | None

    def public_report(self) -> dict[str, Any]:
        """Allowlisted diagnostics, no account number, name or server."""
        return {
            "ready_for_mechanical_review": self.ready_for_mechanical_review,
            "symbol": self.symbol,
            "risk_limit_pct": self.risk_limit_pct,
            "blockers": list(self.blockers),
            "estimated_min_lot_stop_loss": self.estimated_min_lot_stop_loss,
            "account_currency": self.account_currency,
            "min_lot": self.min_lot,
            "spread_pips": self.spread_pips,
            "broker_margin_at_min_lot": self.broker_margin_at_min_lot,
            "order_execution_enabled": False,
            "profitable_strategy_verified": False,
        }


def _finite_positive(value) -> bool:
    try:
        x = float(value)
        return math.isfinite(x) and x > 0
    except (TypeError, ValueError, OverflowError):
        return False


def inspect_demo_execution_conditions(
    api,
    *,
    symbol: str = "EURUSD",
    max_risk_pct: float = 0.25,
    stop_pips: float = 20.0,
    max_spread_pips: float = 2.0,
    now_s: float | None = None,
) -> DemoReadiness:
    """Read-only, conservative operational readiness — NOT a trading permit."""
    blockers: list[str] = []
    currency: str | None = None
    volume: float | None = None
    stop_loss: float | None = None
    spread: float | None = None
    margin: float | None = None

    if not (0 < max_risk_pct <= 0.25):
        raise ValueError("Preflight uses no more than 0.25% simulated risk per trade")
    if not (_finite_positive(stop_pips) and _finite_positive(max_spread_pips)):
        raise ValueError("Invalid test-stop or test-spread settings")

    terminal = api.terminal_info()
    account = api.account_info()
    if terminal is None or not bool(getattr(terminal, "connected", False)):
        blockers.append("MT5 terminal not connected")
    if account is None or getattr(account, "trade_mode", None) != api.ACCOUNT_TRADE_MODE_DEMO:
        blockers.append("Broker account is not verified DEMO")
    if terminal is not None and not bool(getattr(terminal, "trade_allowed", False)):
        blockers.append("MT5 desktop Algo Trading is not enabled")
    if account is not None and not bool(getattr(account, "trade_allowed", False)):
        blockers.append("Broker account does not allow trading")
    if account is not None and not bool(getattr(account, "trade_expert", False)):
        blockers.append("Broker account does not allow expert/automated trading")

    info = api.symbol_info(symbol)
    if (info is None or not bool(getattr(info, "visible", False)) or
            getattr(info, "trade_mode", None) != api.SYMBOL_TRADE_MODE_FULL):
        blockers.append("Symbol unavailable, hidden or non-tradable in Market Watch")
        info = None
    tick = api.symbol_info_tick(symbol) if info is not None else None
    if tick is None:
        blockers.append("No usable current broker bid/ask quote")

    balance = getattr(account, "balance", None)
    margin_free = getattr(account, "margin_free", None)
    if not (_finite_positive(balance) and _finite_positive(margin_free)):
        blockers.append("Invalid broker balance or free margin")
    if account is not None:
        raw_currency = getattr(account, "currency", None)
        if isinstance(raw_currency, str) and 3 <= len(raw_currency) <= 5 and raw_currency.isalpha():
            currency = raw_currency.upper()
        else:
            blockers.append("Unexpected broker account currency")

    if info is not None and tick is not None:
        point = getattr(info, "point", None)
        digits = getattr(info, "digits", None)
        minimum = getattr(info, "volume_min", None)
        maximum = getattr(info, "volume_max", None)
        step = getattr(info, "volume_step", None)
        if not (isinstance(digits, int) and digits in (4, 5) and
                all(_finite_positive(x) for x in (point, minimum, maximum, step)) and
                minimum <= maximum):
            blockers.append("Unsupported EURUSD contract digits, lot or tick specification")
        else:
            volume = float(minimum)
            # EURUSD standard: 0.0001 is one pip; 5-digit quotes use fractional pip points.
            pip = 0.0001
            ask, bid = getattr(tick, "ask", None), getattr(tick, "bid", None)
            when = getattr(tick, "time", None)
            if not (_finite_positive(ask) and _finite_positive(bid) and ask >= bid):
                blockers.append("Invalid broker quote")
            else:
                ask, bid = float(ask), float(bid)
                spread = round((ask - bid) / pip, 3)
                if spread > max_spread_pips:
                    blockers.append("Broker spread exceeds demo trial limit")
                if when is None or not -5 <= ((now_s or time.time()) - float(when)) <= 120:
                    blockers.append("Broker tick is stale")
                if float(getattr(info, "trade_stops_level", 0)) * float(point) > stop_pips * pip:
                    blockers.append("Minimum broker stop distance exceeds chosen test stop")
                stop_buy = ask - stop_pips * pip
                stop_sell = bid + stop_pips * pip
                losses = []
                for side, entry, stop in (
                    (api.ORDER_TYPE_BUY, ask, stop_buy),
                    (api.ORDER_TYPE_SELL, bid, stop_sell),
                ):
                    pnl = api.order_calc_profit(side, symbol, volume, entry, stop)
                    if pnl is None or not math.isfinite(float(pnl)) or pnl >= 0:
                        blockers.append("Broker could not calculate valid stop risk")
                    else:
                        losses.append(abs(float(pnl)))
                if len(losses) == 2:
                    stop_loss = round(max(losses), 2)
                    if _finite_positive(balance) and stop_loss > float(balance) * max_risk_pct / 100:
                        blockers.append("Broker minimum lot exceeds per-trade risk budget")
                # Conservative margin sufficiency check at the minimum lot.
                observed_margin = api.order_calc_margin(api.ORDER_TYPE_BUY, symbol, volume, ask)
                if observed_margin is None or not math.isfinite(float(observed_margin)) or observed_margin < 0:
                    blockers.append("Broker could not calculate margin requirement")
                else:
                    margin = round(float(observed_margin), 2)
                    if _finite_positive(margin_free) and margin > float(margin_free) * 0.25:
                        blockers.append("Demo margin requirement exceeds 25% of free margin")

    return DemoReadiness(
        ready_for_mechanical_review=len(blockers) == 0,
        blockers=tuple(blockers),
        symbol=symbol,
        risk_limit_pct=max_risk_pct,
        estimated_min_lot_stop_loss=stop_loss,
        account_currency=currency,
        min_lot=volume,
        spread_pips=spread,
        broker_margin_at_min_lot=margin,
    )
