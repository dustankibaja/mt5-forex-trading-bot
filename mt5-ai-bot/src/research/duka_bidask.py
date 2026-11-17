"""Read Dukascopy monthly H1 bid/ask candles; research only, no MT5 connection.

Datafeed: /EURUSD/YYYY/MM_ZERO_BASED/{BID|ASK}_candles_hour_1.bi5
LZMA records: >IIIIIf (UTC seconds from month start, O C L H volume).
"""
from __future__ import annotations

import hashlib
import io
import lzma
import os
import struct
import time
from pathlib import Path
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

RECORD = struct.Struct(">IIIIIf")
BASE = "https://datafeed.dukascopy.com/datafeed/EURUSD"
SCALE = 100000.0


def parse_month(raw: bytes, year: int, month: int, side: str) -> pd.DataFrame:
    if side not in ("bid", "ask"):
        raise ValueError("side must be bid or ask")
    if not raw:
        raise ValueError(f"Empty Dukascopy month {year}-{month:02d}: {side}")
    decoded = lzma.decompress(raw)
    if len(decoded) % RECORD.size:
        raise ValueError("Truncated Dukascopy hourly candle file")
    base = datetime(year, month, 1, tzinfo=timezone.utc)
    following = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    rows = []
    for position in range(0, len(decoded), RECORD.size):
        seconds, op, cl, lo, hi, volume = RECORD.unpack_from(decoded, position)
        date = base + timedelta(seconds=seconds)
        if not (base <= date < following) or seconds % 3600 != 0:
            raise ValueError(f"Invalid hourly timestamp offset {seconds}")
        o, c, l, h = (value / SCALE for value in (op, cl, lo, hi))
        if not (l > 0 and l <= min(o, c) and h >= max(o, c) and np.isfinite(volume)):
            raise ValueError("Dukascopy candle validation failed")
        rows.append((date, o, h, l, c))
    if not rows:
        raise ValueError(f"No hourly records in {year}-{month:02d}")
    df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close"])
    df = df.set_index("datetime")
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError("Nonchronological Dukascopy records")
    return df.add_prefix(side + "_")


def download_month(year: int, month: int, side: str, cache_dir: Path | None = None) -> tuple[bytes, str]:
    url = f"{BASE}/{year}/{month-1:02d}/{side.upper()}_candles_hour_1.bi5"
    cache_path = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_path = cache_dir / f"EURUSD-{year}-{month:02d}-{side}.bi5"
        if cache_path.is_file():
            raw = cache_path.read_bytes()
            try:
                parse_month(raw, year, month, side)  # Verify every cached file.
                return raw, url
            except (lzma.LZMAError, ValueError, EOFError):
                cache_path.unlink(missing_ok=True)  # Corrupt cache must not be used.

    last_error = None
    for retry in range(7):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "MT5-AI-Bot-academic-backtest/1.0"}
            )
            with urllib.request.urlopen(request, timeout=40) as reply:
                content = reply.read()
            if not content:
                raise ValueError(f"Empty reply: {url}")
            # A successful HTTP response is not enough: validate binary
            # structure and OHLC invariants before trusting/persisting.
            parse_month(content, year, month, side)
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_path.with_suffix(".tmp")
                tmp.write_bytes(content)
                os.replace(tmp, cache_path)
            return content, url
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as ex:
            last_error = ex
            if isinstance(ex, urllib.error.HTTPError) and ex.code == 404:
                raise RuntimeError(f"Missing data month {url}") from ex
            if retry == 6:
                break
            # Respect temporary 503 / rate limiting without hammering
            # Dukascopy. Resumable local cache preserves completed months.
            time.sleep(min(10 * 2 ** retry, 90))
    raise RuntimeError(f"Could not download {url}: {last_error}")


def month_iter(start_year=2022, start_month=4, end_year=2026, end_month=9):
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        yield year, month
        month += 1
        if month == 13:
            month, year = 1, year + 1


def load_historical(start=(2022, 4), end=(2026, 9), cache_dir: Path | None = Path("data/dukascopy_cache")):
    pieces = []
    manifest = []
    for year, month in month_iter(*start, *end):
        sides = {}
        for side in ("bid", "ask"):
            raw, url = download_month(year, month, side, cache_dir=cache_dir)
            frame = parse_month(raw, year, month, side)
            sides[side] = frame
            manifest.append({
                "period": f"{year}-{month:02d}", "side": side,
                "url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                "candles": len(frame),
            })
            # Dukascopy throttles frequent requests.
            time.sleep(1.0)
        joined = sides["bid"].join(sides["ask"], how="inner", validate="one_to_one")
        if joined.empty:
            raise ValueError(f"No aligned bid/ask bars for {year}-{month:02d}")
        if len(joined) < 250:
            raise ValueError(f"Insufficient bid/ask coverage in {year}-{month:02d}")
        if (len(joined) / max(len(sides["bid"]), len(sides["ask"]))) < 0.98:
            raise ValueError(f"Bid/ask candle misalignment in {year}-{month:02d}")
        for suffix in ("open", "high", "low", "close"):
            if (joined[f"ask_{suffix}"] < joined[f"bid_{suffix}"]).any():
                raise ValueError(f"Negative bid/ask spread in {year}-{month:02d}")
        pieces.append(joined)
        print(f"Verified {year}-{month:02d}: {len(joined)} aligned candles", flush=True)

    df = pd.concat(pieces).sort_index()
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError("Duplicate/nonchronological months")
    spread = (df.ask_open - df.bid_open) / 0.0001
    if (spread < 0).any() or not np.isfinite(spread).all():
        raise ValueError("Invalid spread")
    return df, manifest
