"""Conservative OHLC backtester for EURUSD H1. Research only, not a broker emulator."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd
from src.research.signals import signal

PIP = 0.0001


def simulate(
    df: pd.DataFrame, strategy: str, start: str, end: str,
    *, starting_balance: float = 10000.0,
    spread_pips: float = 1.2, slippage_side_pips: float = 0.2,
    commission_roundtrip_per_lot: float = 7.0,
) -> dict[str, Any]:
    """Signal at previous close, entry at next open; stop-first within bars.

    Assumes mid-price candles, EURUSD USD quote, 100k standard lot ($10/pip).
    Does not model swaps, variable spreads, stop-market fill liquidity, or margin.
    """
    begin = int(df.index.searchsorted(pd.Timestamp(start, tz="UTC")))
    finish = int(df.index.searchsorted(pd.Timestamp(end, tz="UTC")))
    if begin >= finish:
        raise ValueError("Empty validation window")
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr = df.atr14.to_numpy()
    offset = PIP * (spread_pips / 2 + slippage_side_pips)
    bal = starting_balance
    peak, max_dd = bal, 0.0
    position = None
    trades: list[dict] = []
    day, day_pnl, day_count = "", 0.0, 0

    def close_position(p: dict, price: float, bar_i: int, reason: str) -> float:
        pnl = ((price - p["entry"]) * p["direction"] / PIP *
               10 * p["lots"] - commission_roundtrip_per_lot * p["lots"])
        trades.append({
            "pnl": pnl, "r": pnl / p["risk"], "exit_reason": reason,
            "opened": str(df.index[p["opened"]]), "closed": str(df.index[bar_i]),
        })
        return pnl

    for i in range(max(begin, 200), finish):
        current_day = df.index[i].strftime("%Y-%m-%d")
        if current_day != day:
            day, day_pnl, day_count = current_day, 0.0, 0

        if position is not None:
            p = position
            stop_mid = p["sl"] + p["direction"] * offset
            target_mid = p["tp"] + p["direction"] * offset
            exit_price, why = None, ""
            if p["direction"] == 1:
                if o[i] <= stop_mid:
                    exit_price, why = min(p["sl"], o[i] - offset), "gap_stop"
                elif o[i] >= target_mid:
                    exit_price, why = p["tp"], "gap_target"
                elif l[i] <= stop_mid:
                    exit_price, why = p["sl"], "stop"
                elif h[i] >= target_mid:
                    exit_price, why = p["tp"], "target"
            else:
                if o[i] >= stop_mid:
                    exit_price, why = max(p["sl"], o[i] + offset), "gap_stop"
                elif o[i] <= target_mid:
                    exit_price, why = p["tp"], "gap_target"
                elif h[i] >= stop_mid:
                    exit_price, why = p["sl"], "stop"
                elif l[i] <= target_mid:
                    exit_price, why = p["tp"], "target"
            if exit_price is None and i - p["opened"] >= 48:
                exit_price, why = c[i] - p["direction"] * offset, "timeout"
            if exit_price is not None:
                pnl = close_position(p, exit_price, i, why)
                bal += pnl
                day_pnl += pnl
                position = None

        # Never open on the last bar of a partition, and never use current
        # bar's close, high or low for an order at the same bar's open.
        if (position is None and i < finish - 1 and i > begin and i > 200
                and day_count < 3 and day_pnl > -0.02 * bal):
            direction = signal(df, i - 1, strategy)
            distance = atr[i - 1] * 1.5
            if direction and distance > PIP and bal > 0:
                entry = o[i] + direction * offset
                budget = bal * 0.005
                risk_per_lot = distance / PIP * 10
                lots = math.floor((budget / risk_per_lot + 1e-9) / 0.01) * 0.01
                if lots >= 0.01:
                    position = {
                        "direction": direction, "entry": entry,
                        "sl": entry - direction * distance,
                        "tp": entry + direction * distance * 2,
                        "lots": lots, "risk": budget, "opened": i,
                    }
                    day_count += 1

        marked = bal
        if position is not None:
            p = position
            marked += ((c[i] - p["direction"] * offset - p["entry"]) *
                       p["direction"] / PIP * 10 * p["lots"] -
                       commission_roundtrip_per_lot * p["lots"])
        peak = max(peak, marked)
        max_dd = max(max_dd, 100 * (peak - marked) / peak)

    # Include any open exposure at the exact end of the partition.
    if position is not None:
        p = position
        exit_price = c[finish - 1] - p["direction"] * offset
        bal += close_position(p, exit_price, finish - 1, "period_end")

    win = [t for t in trades if t["pnl"] > 0]
    gain = sum(t["pnl"] for t in win)
    loss = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    return {
        "strategy": strategy,
        "trades": len(trades),
        "net_return_pct": round(100 * (bal / starting_balance - 1), 4),
        "win_rate_pct": round(100 * len(win) / len(trades), 4) if trades else 0.0,
        "profit_factor": round(gain / loss, 4) if loss else None,
        "max_marked_drawdown_pct": round(max_dd, 4),
        "expectancy_r": round(sum(t["r"] for t in trades) / len(trades), 5) if trades else None,
        "ending_balance_usd": round(bal, 2),
        "gap_stops": sum(t["exit_reason"] == "gap_stop" for t in trades),
        "time_exits": sum(t["exit_reason"] in ("timeout", "period_end") for t in trades),
    }
