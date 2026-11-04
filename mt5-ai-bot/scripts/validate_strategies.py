#!/usr/bin/env python3
"""Repeatable EURUSD H1 historical strategy comparison; DOES NOT place trades."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.research.signals import enrich, STRATEGIES
from src.research.backtest import simulate

SOURCE = (
    "https://raw.githubusercontent.com/ejtraderLabs/historical-data/"
    "fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd/EURUSD/EURUSDh1.csv"
)
PERIODS = {
    "development": ("2012-11-16", "2018-01-01"),
    "validation": ("2018-01-01", "2020-01-01"),
    "holdout": ("2020-01-01", "2022-03-05"),
}


def load_data(raw: bytes, price_scale: float) -> pd.DataFrame:
    if price_scale <= 0 or not math.isfinite(price_scale):
        raise ValueError("Invalid data price scale")
    df = pd.read_csv(io.BytesIO(raw))
    date = "Date" if "Date" in df.columns else "datetime"
    if date not in df:
        raise ValueError("Input CSV requires Date or datetime")
    df.index = pd.to_datetime(df[date], utc=True, errors="raise")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("Non-chronological or duplicate candles")
    for col in ("open", "high", "low", "close"):
        if col not in df:
            raise ValueError(f"Missing {col}")
        df[col] = pd.to_numeric(df[col], errors="raise") / price_scale
    prices = df[["open", "high", "low", "close"]]
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError("Non-finite or non-positive prices")
    if ((df.high < df[["open", "close"]].max(axis=1)) |
        (df.low > df[["open", "close"]].min(axis=1)) |
        (df.high < df.low)).any():
        raise ValueError("Invalid OHLC ranges")
    return prices.copy()


def format_report(result: dict) -> str:
    lines = [
        "# MT5 AI Bot — strategy validation research",
        "",
        f"Data source: {result['source']}",
        f"Data SHA256: {result['sha256']}",
        f"Bars: {result['bars']:,} | {result['start']} to {result['end']}",
        "",
        "Assumed EURUSD H1 mid candles, $10k starting account per period, "
        "0.5% risk/trade, 1.5 ATR stop, 2R target, maximum 48-bar hold, "
        "three entries/day, 1.2-pip spread, 0.2-pip adverse slippage per side, "
        "$7 round-trip commission per standard lot. Orders enter at next open; "
        "stop-first when SL and TP are both touched. No swap or variable spread.",
        "",
        "| Period | Strategy | Trades | Net return | Win rate | Profit factor | Max drawdown |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for period, runs in result["periods"].items():
        for row in runs:
            pf = "n/a" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"
            lines.append(
                f"| {period} | {row['strategy']} | {row['trades']} | "
                f"{row['net_return_pct']:+.2f}% | {row['win_rate_pct']:.1f}% | "
                f"{pf} | {row['max_marked_drawdown_pct']:.1f}% |"
            )
    lines.extend([
        "",
        f"Validation leader: **{result['validation_leader']}**.",
        f"Approved for profitable demo-candidate development: **{result['approved']}**.",
        "",
        "Preliminary simulation, not a claim of profitable trading. No benchmark "
        "demonstrates outperforming most human traders. Price timestamps assume UTC; "
        "vendor time origin is not independently certified. Historical bid/ask "
        "spreads, financing charges, intrabar fill sequence, broker contract "
        "specifications, and independent data-source confirmation remain open.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--data-url", default=SOURCE)
    parser.add_argument("--price-scale", type=float, default=100000)
    parser.add_argument("--out", type=Path, default=Path("validation_report"))
    args = parser.parse_args()
    if args.csv:
        raw, source = args.csv.read_bytes(), str(args.csv)
    else:
        req = urllib.request.Request(
            args.data_url, headers={"User-Agent": "mt5-validation-research/1.0"}
        )
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read()
        source = args.data_url

    frame = enrich(load_data(raw, args.price_scale))
    result = {
        "source": source,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bars": len(frame),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "periods": {},
    }
    for period, (start, end) in PERIODS.items():
        result["periods"][period] = [
            simulate(frame, strategy, start, end) for strategy in STRATEGIES
        ]
    leader = max(result["periods"]["validation"], key=lambda x: x["net_return_pct"])
    result["validation_leader"] = leader["strategy"]
    holdout = next(
        r for r in result["periods"]["holdout"]
        if r["strategy"] == leader["strategy"]
    )
    result["approved"] = (
        leader["strategy"]
        if leader["net_return_pct"] > 0 and leader["profit_factor"] is not None
        and leader["profit_factor"] > 1 and holdout["net_return_pct"] > 0
        and holdout["profit_factor"] is not None and holdout["profit_factor"] > 1
        else "NONE"
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    report = format_report(result)
    (args.out / "report.md").write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
