"""Evaluate the frozen 2020 FXCM cohort from local, official archive files."""
import argparse
import gzip
import hashlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.research.bidask_backtest import simulate
from src.research.regime_signals import indicators
from run_sprint11_research import diagnostics

FIELDS = [side + part for side in ("Bid", "Ask") for part in ("Open", "High", "Low", "Close")]
COLUMNS = [side + "_" + part for side in ("bid", "ask") for part in ("open", "high", "low", "close")]


def parse(raw):
    # Limit compressed and decompressed input before parsing.
    if len(raw) > 100_000:
        raise ValueError("Unexpected compressed weekly size")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        data = compressed.read(256_001)
    if len(data) > 256_000:
        raise ValueError("Unexpected expanded weekly size")
    df = pd.read_csv(io.BytesIO(data))
    if list(df.columns) != ["DateTime", *FIELDS] or not 1 <= len(df) <= 168:
        raise ValueError("Unexpected FXCM archive schema")
    utc = pd.to_datetime(df.DateTime, format="%m/%d/%Y %H:%M:%S.%f", utc=True)
    if utc.duplicated().any() or not utc.is_monotonic_increasing or not utc.eq(utc.dt.floor("h")).all():
        raise ValueError("Archive timestamps are not distinct chronological UTC hours")
    result = df[FIELDS].apply(pd.to_numeric, errors="raise")
    result.index = pd.DatetimeIndex(utc)
    result.columns = COLUMNS
    if not result.ge(.1).all().all() or not result.le(10).all().all():
        raise ValueError("Invalid OHLC prices")
    for side in ("bid", "ask"):
        op, hi, lo, cl = (result[side + "_" + part] for part in ("open", "high", "low", "close"))
        if ((lo > op) | (lo > cl) | (hi < op) | (hi < cl)).any():
            raise ValueError("Malformed OHLC")
    if any((result["bid_" + part] > result["ask_" + part]).any()
           for part in ("open", "high", "low", "close")):
        raise ValueError("Crossed bid/ask OHLC")
    return result


def run(root):
    frames, manifest = [], []
    failures = []
    for year, weeks in ((2019, range(48, 53)), (2020, range(1, 54))):
        for week in weeks:
            file = root / f"{year}-{week:02d}.csv.gz"
            if year == 2020 and week == 53 and not file.exists():
                continue
            entry = dict(year=year, week=week,
                         url=f"https://candledata.fxcorporate.com/H1/EURUSD/{year}/{week}.csv.gz")
            try:
                raw = file.read_bytes()
                entry["sha256"] = hashlib.sha256(raw).hexdigest()
                frame = parse(raw)
            except FileNotFoundError:
                failures.append(dict(year=year, week=week, reason="Required archive file missing"))
            except (OSError, ValueError) as exc:
                failures.append(dict(year=year, week=week, reason=str(exc)))
            else:
                frames.append(frame)
                entry["rows"] = len(frame)
            manifest.append(entry)
    if failures:
        return dict(status="blocked", source_files_parsed=len(frames), failures=failures,
                    screen_passed=False, manifest=manifest)
    side = pd.concat(frames).sort_index()
    if side.index.has_duplicates:
        duplicates = side[side.index.duplicated(keep=False)]
        if duplicates.groupby(level=0).nunique().gt(1).any().any():
            raise ValueError("Conflicting duplicate hours")
        side = side[~side.index.duplicated()]
    side = side[side.index.year <= 2020]
    evaluation = side[side.index.year == 2020]
    warmup = len(side) - len(evaluation)
    if (warmup < 210 or len(evaluation) < 5500 or evaluation.index.month.nunique() != 12
            or evaluation.index[-1].day != 31):
        raise ValueError("Frozen annual coverage gate failed")
    mid = indicators(side)
    result = simulate(side, mid, "compression_release", "2020-01-01", "2021-01-01",
                      include_trades=True)
    trades = result.pop("trade_log")
    result.update(diagnostics(trades, 2020))
    gaps = evaluation.index.to_series().diff().dt.total_seconds().div(3600).dropna()
    spread = (evaluation.ask_open - evaluation.bid_open) * 10_000
    # Compare simulator fills against the actual predecessor timestamp.
    predecessor_gaps = []
    for trade in trades:
        ix = side.index.get_loc(pd.Timestamp(trade["entry_at"]))
        predecessor_gaps.append((side.index[ix] - side.index[ix - 1]).total_seconds() / 3600)
    interval = result["monthly_block_expectancy_95_r"]
    screen = (result["trades"] >= 50 and result["net_return_pct"] > 0
              and (result["profit_factor"] or 0) > 1 and result["max_marked_drawdown_pct"] <= 15
              and interval is not None and interval[0] > 0)
    return dict(status="evaluated", warmup_bars=warmup, evaluation_bars=len(evaluation), first=str(evaluation.index[0]),
                last=str(evaluation.index[-1]), gap_distribution_hours={str(k): int(v)
                    for k, v in gaps[gaps > 1].value_counts().sort_index().items()},
                entries_after_gap=sum(h > 1 for h in predecessor_gaps),
                spread_pips={str(k): float(v) for k, v in spread.quantile([.5, .9, .99]).items()},
                result=result, screen_passed=bool(screen), manifest=manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.archive_dir), indent=2))
