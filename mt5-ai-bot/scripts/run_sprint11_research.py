"""Run three fixed exploratory rules; never request the sealed 2026 data."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.research.bidask_backtest import simulate
from src.research.ev_annual_bidask import load_annual_bidask
from src.research.regime_signals import indicators

YEARS = (2022, 2023, 2024, 2025)


def signals(f):
    clock = f.index.to_series()
    hour = f.index.hour
    step = clock.diff().eq(pd.Timedelta(hours=1))
    next_hour = step.shift(-1, fill_value=False)
    trend = (hour >= 7) & (hour <= 16) & step & (f.atr14 > f.atr60_median_prior)
    prev = f.shift(1)
    quiet = ((hour >= 10) & (hour <= 16) & step & (f.atr14 <= f.atr60_median_prior)
             & ((f.ema50 - f.ema200).abs() <= .5 * f.atr14))
    london = (hour == 8) & step & step.shift(1, fill_value=False) & step.shift(2, fill_value=False)
    high = f.high.shift().rolling(3).max()
    low = f.low.shift().rolling(3).min()
    body = f.close - f.open
    above = f.close > f.ema20
    below = f.close < f.ema20
    pairs = {
        "trend_resumption": (trend & (f.close > f.ema50) & (f.ema50 > f.ema200)
                             & (prev.close <= prev.ema20) & above,
                             trend & (f.close < f.ema50) & (f.ema50 < f.ema200)
                             & (prev.close >= prev.ema20) & below),
        "london_momentum": (london & (f.close > high) & (body >= .5 * f.atr14),
                            london & (f.close < low) & (-body >= .5 * f.atr14)),
        "quiet_reversion": (quiet & (prev.ema20 - prev.close >= prev.atr14) & (f.close > prev.close),
                            quiet & (prev.close - prev.ema20 >= prev.atr14) & (f.close < prev.close)),
    }
    return {name: (long.astype(int) - short.astype(int)).where(next_hour, 0)
            for name, (long, short) in pairs.items()}


def diagnostics(log, year):
    months = [[] for _ in range(12)]
    for t in log:
        date = pd.Timestamp(t["entry_at"])
        if date.year == year:
            months[date.month - 1].append(t["r"])
    rng = np.random.default_rng(112026)
    draws = rng.integers(0, 12, size=(3000, 12))
    sums = np.array([sum(m) for m in months])[draws].sum(axis=1)
    counts = np.array([len(m) for m in months])[draws].sum(axis=1)
    positive = sorted((t["pnl_usd"] for t in log if t["pnl_usd"] > 0), reverse=True)
    return {
        "monthly_block_expectancy_95_r": np.quantile(sums[counts > 0] / counts[counts > 0],
                                                     [.025, .975]).tolist() if counts.any() else None,
        "top_five_gross_gain_share": sum(positive[:5]) / sum(positive) if positive else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    side, manifest = load_annual_bidask(YEARS)
    expected = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if [(r["year"], r["sha256"]) for r in manifest] != [(r["year"], r["sha256"]) for r in expected]:
        raise SystemExit("Annual source digest changed")
    mid = indicators(side)
    results = {}
    for name, directions in signals(mid).items():
        rows = []
        for year in YEARS:
            for scenario, costs in (("base", {}), ("stress", dict(slippage_pips=.6,
                                          commission_per_lot=10, carry_per_lot=10))):
                row = simulate(side, mid, name, f"{year}-01-01", f"{year + 1}-01-01",
                               directions=directions, include_trades=True, **costs)
                log = row.pop("trade_log")
                rows.append(dict(year=year, scenario=scenario, **row, **diagnostics(log, year)))
        base = [r for r in rows if r["scenario"] == "base"]
        stress = [r for r in rows if r["scenario"] == "stress"]
        passes = (sum(r["net_return_pct"] for r in base) > 0
                  and sum(r["net_return_pct"] for r in stress) > 0
                  and sum(r["net_return_pct"] > 0 for r in base) >= 3
                  and base[-1]["trades"] >= 50
                  and max(r["max_marked_drawdown_pct"] for r in rows) <= 15)
        results[name] = dict(screen_passed=bool(passes), annual=rows)
    print(json.dumps(dict(manifest=manifest, results=results), indent=2))


if __name__ == "__main__":
    main()
