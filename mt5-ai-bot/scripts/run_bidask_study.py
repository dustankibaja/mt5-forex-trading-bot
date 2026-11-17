#!/usr/bin/env python3
"""Pre-registered EURUSD bid/ask research experiment. No live broker access."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.research.duka_bidask import load_historical
from src.research.regime_signals import CANDIDATES, indicators
from src.research.bidask_backtest import simulate

TRAIN = ("2022-04-01", "2025-01-01")
VALIDATION = ("2025-01-01", "2026-01-01")
HOLDOUT = ("2026-01-01", "2026-10-01")


def qualified(row: dict) -> bool:
    return bool(
        row["trades"] >= 50 and row["net_return_pct"] > 0
        and row["profit_factor"] is not None and row["profit_factor"] > 1.0
        and row["max_marked_drawdown_pct"] <= 15.0
    )


def render(result: dict) -> str:
    lines = [
        "# Dukascopy bid/ask research — pre-registered report",
        "",
        "Source: historical EURUSD H1 bid/ask Dukascopy files, "
        "recorded by file SHA256 in manifest.json. UTC. One run per frozen strategy.",
        "",
        "All strategies: 0.5% risk, 1.5 ATR stop, 2R TP, 48h max hold; "
        "variable historical entry spreads (max 2 pips), "
        "0.2 pip adverse slippage each side and $7/lot round-trip commission. "
        "Conservative stop-first within hourly candles. No swap, depth, partial fills or margin.",
        "",
        "| Window | Hypothesis | Trades | Net return | Profit factor | Max DD |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for window in ("development", "validation", "holdout"):
        for row in result.get(window, []):
            pf = "n/a" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"
            lines.append(
                f"| {window} | {row['hypothesis']} | {row['trades']} | "
                f"{row['net_return_pct']:+.2f}% | {pf} | "
                f"{row['max_marked_drawdown_pct']:.1f}% |"
            )
    lines.extend(["", f"**Validation-qualified candidates:** {', '.join(result['eligible']) or 'NONE'}."])
    if not result["eligible"]:
        lines.append("2026 holdout remained untested because all candidates failed validation.")
    else:
        lines.append(f"**Passed holdout gate:** {', '.join(result['holdout_passed']) or 'NONE'}.")
    lines.extend([
        "",
        "## Data coverage",
        f"{result['source_files']} source files, {result['bars_development_validation']:,} "
        "aligned development+validation hourly records.",
        f"Observed entry spread (pips): {result['spread_pips']}.",
        "",
        "## Limitations",
        "Historical hourly bid/ask bars do not reveal intrabar tick sequence. No swaps, "
        "broker contract/margin restrictions, execution queue or partial fills are "
        "simulated. These are research outcomes, not a live-profitability guarantee. "
        "No comparison to human-trader performance was conducted.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("bidask_report"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    side, manifest = load_historical(start=(2022, 4), end=(2025, 12))
    spread = (side.ask_open - side.bid_open) / .0001
    mid = indicators(side)
    results = {
        "source_files": len(manifest),
        "bars_development_validation": len(side),
        "spread_pips": {
            "p50": round(float(spread.quantile(.5)), 3),
            "p90": round(float(spread.quantile(.9)), 3),
            "p99": round(float(spread.quantile(.99)), 3),
        },
        "development": [
            simulate(side, mid, name, *TRAIN) for name in CANDIDATES
        ],
        "validation": [
            simulate(side, mid, name, *VALIDATION) for name in CANDIDATES
        ],
    }
    results["eligible"] = [
        r["hypothesis"] for r in results["validation"] if qualified(r)
    ]
    results["holdout"] = []
    results["holdout_passed"] = []

    # Holdout data are not fetched or inspected unless a pre-registered
    # strategy passes the 2025 validation gate. No hyperparameter tuning.
    if results["eligible"]:
        future, future_manifest = load_historical(
            start=(2026, 1), end=(2026, 9)
        )
        manifest.extend(future_manifest)
        import pandas as pd
        all_bars = pd.concat([side, future])
        future_mid = indicators(all_bars)
        results["holdout"] = [
            simulate(all_bars, future_mid, name, *HOLDOUT)
            for name in results["eligible"]
        ]
        results["holdout_passed"] = [
            row["hypothesis"] for row in results["holdout"]
            if qualified(row)
        ]

    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    report = render(results)
    (args.out / "report.md").write_text(report, encoding="utf-8")
    print(report, flush=True)


if __name__ == "__main__":
    main()
