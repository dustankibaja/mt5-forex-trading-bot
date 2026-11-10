"""Descriptive diagnostics for seven frozen EURUSD hypotheses through 2025."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from itertools import groupby
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.validate_strategies import PERIODS, SOURCE, STRATEGIES, load_data
from src.research import backtest, bidask_backtest
from src.research.ev_annual_bidask import load_annual_bidask
from src.research.regime_signals import CANDIDATES, indicators
from src.research.signals import enrich

OHLC_SHA256 = "1b29ca23bdc7b2645ae48a0ccb06108263b69e586bdc7d0ba40e66d1e5966eb9"


def summarize(result, frame):
    records = result.pop("trade_log")
    if not records:
        return result
    trades = pd.DataFrame(records).rename(columns={
        "pnl_usd": "pnl", "entry_at": "opened", "exit_at": "closed",
    })
    pnl = trades.pnl.to_numpy()
    r = trades.r.to_numpy()
    opened = pd.DatetimeIndex(trades.opened)
    closed = pd.DatetimeIndex(trades.closed)
    quarter = closed.tz_localize(None).to_period("Q")
    cash_flows = pd.Series(pnl, index=quarter).groupby(level=0).sum()
    prior_cash = 10000 + cash_flows.cumsum().shift(fill_value=0)
    lagged_atr = frame.atr14.shift(1)
    baseline = lagged_atr.rolling(60).median().shift(1)
    vol = lagged_atr.reindex(opened).to_numpy()
    threshold = baseline.reindex(opened).to_numpy()
    regimes = {}
    for label, mask in (("higher_atr", vol > threshold), ("lower_atr", vol <= threshold)):
        regimes[label] = {"trades": int(mask.sum()), "mean_r": float(r[mask].mean()) if mask.any() else None}

    # Resample consecutive trades in blocks of five to retain some serial
    # dependence. This interval is descriptive and ignores selection effects.
    block_length = 5
    rng = np.random.default_rng(83)
    starts = rng.integers(0, len(r), size=(5000, (len(r) + block_length - 1) // block_length))
    indices = (starts[:, :, None] + np.arange(block_length)) % len(r)
    means = r[indices.reshape(5000, -1)[:, :len(r)]].mean(axis=1)
    return {
        **result,
        "average_win_usd": float(pnl[pnl > 0].mean()) if (pnl > 0).any() else None,
        "average_loss_usd": float(pnl[pnl < 0].mean()) if (pnl < 0).any() else None,
        "average_holding_hours_bar_to_bar": float(np.mean((closed - opened) / pd.Timedelta(hours=1))),
        "longest_losing_streak": max((sum(1 for _ in group) for loss, group in groupby(pnl < 0) if loss), default=0),
        "realized_quarterly_return_pct": {str(k): round(v, 4) for k, v in (100 * cash_flows / prior_cash).items()},
        "entry_atr_regimes": regimes,
        "mean_r_block_bootstrap_95pct": np.quantile(means, [0.025, 0.975]).tolist(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with urlopen(SOURCE, timeout=90) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != OHLC_SHA256:
        raise ValueError("Frozen OHLC source hash changed")
    frame = enrich(load_data(raw, 100000))
    side, manifest = load_annual_bidask()
    mid = indicators(side)
    widened = side.copy()
    widened.loc[:, widened.columns.str.startswith("bid_")] -= 0.25 * bidask_backtest.PIP
    widened.loc[:, widened.columns.str.startswith("ask_")] += 0.25 * bidask_backtest.PIP
    rows = {}
    for name in STRATEGIES:
        window = PERIODS["holdout"]
        row = summarize(backtest.simulate(frame, name, *window, include_trades=True), frame)
        row["spread_stress"] = backtest.simulate(frame, name, *window, spread_pips=2.0)
        row["slippage_stress"] = backtest.simulate(frame, name, *window, slippage_side_pips=0.5)
        rows[name] = row
    for name in CANDIDATES:
        window = ("2025-01-01", "2026-01-01")
        row = summarize(bidask_backtest.simulate(side, mid, name, *window, include_trades=True), mid)
        row["spread_stress"] = bidask_backtest.simulate(widened, mid, name, *window)
        row["slippage_stress"] = bidask_backtest.simulate(side, mid, name, *window, slippage_pips=0.5)
        rows[name] = row
    coverage = {}
    for name, index in (("ohlc", frame.index), ("bidask", side.index)):
        gaps = index.to_series().diff().dropna() / pd.Timedelta(hours=1)
        coverage[name] = {"gaps_over_one_hour_including_weekends": int((gaps > 1).sum()),
                          "longest_gap_hours": float(gaps.max())}
    result = {"ohlc_sha256": OHLC_SHA256, "bidask_manifest": manifest,
              "coverage": coverage, "strategies": rows}
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
