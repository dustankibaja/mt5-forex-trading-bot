"""EURUSD side-specific H1 research simulator. Does NOT send orders.

Bid/ask opens and candle extremes are the historical series; fills are
conservatively adjusted for adverse slippage and stop gaps. Results omit
swap, market depth, varying commission, margin, broker restrictions and
true tick-by-tick path; never consider these live-performance predictions.
"""
from __future__ import annotations

import math

import pandas as pd

from src.research.regime_signals import signal

PIP = 0.0001
USD_PER_PIP_PER_LOT = 10.0


def simulate(
    side: pd.DataFrame,
    mid: pd.DataFrame,
    hypothesis: str,
    start: str,
    end: str,
    *,
    slippage_pips: float = 0.2,
    commission_per_lot: float = 7.0,
    initial_cash: float = 10000.0,
    spread_limit_pips: float = 2.0,
    include_trades: bool = False,
    directions: pd.Series | None = None,
    carry_per_lot: float = 0.0,
) -> dict:
    begin = int(side.index.searchsorted(pd.Timestamp(start, tz="UTC")))
    finish = int(side.index.searchsorted(pd.Timestamp(end, tz="UTC")))
    if begin >= finish:
        raise ValueError("Missing test interval")
    if not side.index.equals(mid.index):
        raise ValueError("Bid-ask data and indicators must have identical timestamps")
    if directions is not None and (not side.index.equals(directions.index)
                                   or not directions.isin((-1, 0, 1)).all()):
        raise ValueError("Directions must be aligned and ternary")
    if not math.isfinite(carry_per_lot) or carry_per_lot < 0:
        raise ValueError("Carry must be finite and nonnegative")

    values = {field: side[field].to_numpy() for field in side.columns}
    atr = mid.atr14.to_numpy()
    cash, peak, worst_dd = initial_cash, initial_cash, 0.0
    pos, trades = None, []
    day, day_pnl, day_count = "", 0.0, 0
    slip = PIP * slippage_pips
    spread_skips = 0
    roll_day = (side.index - pd.Timedelta(hours=22)).normalize()

    def costs(p, idx):
        return (commission_per_lot + carry_per_lot *
                (roll_day[idx] - roll_day[p["opened"]]).days) * p["lots"]

    def fill_close(p, px, idx, reason):
        pnl = ((px - p["entry"]) * p["direction"] / PIP
               * USD_PER_PIP_PER_LOT * p["lots"]
               - costs(p, idx))
        trades.append({
            "pnl_usd": pnl,
            "r": pnl / p["risk_usd"],
            "entry_at": str(side.index[p["opened"]]),
            "exit_at": str(side.index[idx]),
            "reason": reason,
        })
        return pnl

    def exit_if_hit(p, idx):
        d = p["direction"]
        # A long exits at BID, a short covers at ASK.
        side_name = "bid" if d > 0 else "ask"
        op = values[f"{side_name}_open"][idx]
        hi = values[f"{side_name}_high"][idx]
        lo = values[f"{side_name}_low"][idx]
        sl, tp = p["sl"], p["tp"]
        if d > 0:
            if op <= sl:
                return min(sl, op) - slip, "stop_gap"
            if op >= tp:
                return tp - slip, "target_gap"
            if lo <= sl:
                return sl - slip, "stop"
            if hi >= tp:
                return tp - slip, "target"
        else:
            if op >= sl:
                return max(sl, op) + slip, "stop_gap"
            if op <= tp:
                return tp + slip, "target_gap"
            if hi >= sl:
                return sl + slip, "stop"
            if lo <= tp:
                return tp + slip, "target"
        return None, ""

    for i in range(max(begin, 211), finish):
        new_day = side.index[i].strftime("%Y-%m-%d")
        if new_day != day:
            day, day_pnl, day_count = new_day, 0.0, 0

        # An existing position can exit at any point *inside* this bar.
        # We cannot then open a new trade at this bar's already-passed OPEN.
        began_with_position = pos is not None
        if pos is not None:
            exit_price, why = exit_if_hit(pos, i)
            if exit_price is None and i - pos["opened"] >= 48:
                side_name = "bid" if pos["direction"] > 0 else "ask"
                exit_price = values[f"{side_name}_close"][i] - pos["direction"] * slip
                why = "time_exit"
            if exit_price is not None:
                pnl = fill_close(pos, exit_price, i, why)
                cash += pnl
                day_pnl += pnl
                pos = None

        # Strictly signal on i-1, execute on opening quote of i.
        if (
            pos is None and not began_with_position and i > begin and i < finish - 1 and cash > 0
            and day_count < 3 and day_pnl > -cash * 0.02
        ):
            spread = (values["ask_open"][i] - values["bid_open"][i]) / PIP
            if not (math.isfinite(spread) and 0 <= spread <= spread_limit_pips):
                spread_skips += 1
            else:
                direction = (signal(mid, i - 1, hypothesis) if directions is None
                             else int(directions.iat[i - 1]))
                stop_distance = 1.5 * atr[i - 1]
                if direction and stop_distance > PIP:
                    # Executable ask for long, bid for short; risk assessed
                    # per standard EURUSD lot with broker-compatible min steps.
                    entry_mid = (
                        values["ask_open"][i] if direction > 0
                        else values["bid_open"][i]
                    )
                    entry = entry_mid + direction * slip
                    budget = cash * 0.005
                    risk_one_lot = (
                        (stop_distance + slip) / PIP * USD_PER_PIP_PER_LOT
                        + commission_per_lot
                    )
                    lots = math.floor((budget / risk_one_lot + 1e-9) / .01) * .01
                    if lots >= .01:
                        pos = {
                            "direction": direction, "entry": entry,
                            "sl": entry - direction * stop_distance,
                            "tp": entry + direction * stop_distance * 2,
                            "lots": round(lots, 8), "opened": i,
                            "risk_usd": budget,
                        }
                        day_count += 1
                        # The entry candle might also hit the protective stop.
                        exit_price, why = exit_if_hit(pos, i)
                        if exit_price is not None:
                            pnl = fill_close(pos, exit_price, i, "entry_" + why)
                            cash += pnl
                            day_pnl += pnl
                            pos = None

        marked = cash
        if pos is not None:
            side_name = "bid" if pos["direction"] > 0 else "ask"
            liquidation = values[f"{side_name}_close"][i] - pos["direction"] * slip
            marked += (
                (liquidation - pos["entry"]) * pos["direction"] / PIP
                * USD_PER_PIP_PER_LOT * pos["lots"]
                - costs(pos, i)
            )
        peak = max(peak, marked)
        worst_dd = max(worst_dd, (peak - marked) / peak * 100)

    if pos is not None:
        d = pos["direction"]
        px = values["bid_close" if d > 0 else "ask_close"][finish - 1] - d * slip
        cash += fill_close(pos, px, finish - 1, "period_end")

    gains = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    losses = -sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0)
    result = {
        "hypothesis": hypothesis,
        "trades": len(trades),
        "net_return_pct": round(100 * (cash / initial_cash - 1), 4),
        "profit_factor": round(gains / losses, 4) if losses else None,
        "win_rate_pct": round(100 * sum(t["pnl_usd"] > 0 for t in trades) / len(trades), 2) if trades else 0.0,
        "expectancy_r": round(sum(t["r"] for t in trades) / len(trades), 5) if trades else None,
        "max_marked_drawdown_pct": round(worst_dd, 4),
        "spread_skips": spread_skips,
        "end_balance_usd": round(cash, 2),
    }
    if include_trades:
        result["trade_log"] = trades
    return result
