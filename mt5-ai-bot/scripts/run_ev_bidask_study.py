#!/usr/bin/env python3
"""Public annual H1 bid/ask test, never MT5 execution or 2026 holdout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.research.ev_annual_bidask import load_annual_bidask
from src.research.regime_signals import CANDIDATES, indicators
from src.research.bidask_backtest import simulate


def qualified(row):
    return (row["trades"] >= 50 and row["net_return_pct"] > 0
            and row["profit_factor"] is not None and row["profit_factor"] > 1
            and row["max_marked_drawdown_pct"] <= 15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("ev_research_report"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    side, manifest = load_annual_bidask()
    mid = indicators(side)
    development = [simulate(side, mid, name, "2022-01-01", "2025-01-01")
                   for name in CANDIDATES]
    validation = [simulate(side, mid, name, "2025-01-01", "2026-01-01")
                  for name in CANDIDATES]
    stress = [simulate(side, mid, name, "2025-01-01", "2026-01-01",
              slippage_pips=0.5, commission_per_lot=10.0) for name in CANDIDATES]
    spread = (side.ask_open - side.bid_open) / .0001
    allowed = [row["hypothesis"] for row in validation if qualified(row)]
    result = {
        "research_only": True, "profitable_strategy_verified": False,
        "source": "EV Trading Labs annual H1 EURUSD, Dukascopy-derived",
        "source_url": "https://evtradelabs.com/data",
        "sealed_holdout_2026_accessed": False, "bars": len(side),
        "spread_pips": {
            "p50": round(float(spread.quantile(.5)), 3),
            "p90": round(float(spread.quantile(.9)), 3),
            "p99": round(float(spread.quantile(.99)), 3)},
        "development": development, "validation": validation,
        "stress_2025": stress, "validation_qualified": allowed,
        "promotion_to_live": "NO",
        "why_not_live": "2026 holdout and actual broker forward-test missing",
    }
    lines = [
        "# EURUSD H1 public bid/ask replication — research only",
        "",
        "Source: EV Trading Labs https://evtradelabs.com/data (Dukascopy-derived). "
        "Original source URLs and SHA256 recorded in manifest.json.",
        f"Bars: {len(side):,}. Periods: 2022–2024 development, 2025 validation. "
        "2026 HOLDOUT NOT TOUCHED.",
        "",
        "0.5% risk, next-bar executable bid/ask, 1.5 ATR stop, 2R target, "
        "0.2 pip adverse slippage per side, $7/lot roundtrip commission, "
        "2 pip spread gate, 48-bar expiry. Stops-first on ambiguous H1 bars. "
        "No swaps, broker margin or tick-level execution modeled.",
        "",
        "| Window | Strategy | Trades | Net return | Profit factor | Max DD |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for window, rows in [
        ("2022–24 development", development),
        ("2025 validation", validation),
        ("2025 stressed costs", stress),
    ]:
        for row in rows:
            pf = row["profit_factor"]
            lines.append(
                f"| {window} | {row['hypothesis']} | {row['trades']} | "
                f"{row['net_return_pct']:+.2f}% | "
                f"{pf:.3f}" if pf is not None else "n/a"
                f"{row['max_marked_drawdown_pct']:.2f}% |"
            )
    lines.append("")
    lines.append("**2025 validation-qualified:** " + (", ".join(allowed) or "NONE"))
    lines.append("**Approved for live trading:** NO.")
    lines.append("Bid/ask distributor independent but data originate at Dukascopy. "
                 "No 2026 holdout, real broker swaps, margin, SL/TP gap-path or forward test.")
    (args.out/"results.json").write_text(json.dumps(result, indent=2)+"\n")
    (args.out/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    report="\n".join(lines)+"\n"
    (args.out/"report.md").write_text(report)
    print(report,flush=True)


if __name__=="__main__":
    main()
