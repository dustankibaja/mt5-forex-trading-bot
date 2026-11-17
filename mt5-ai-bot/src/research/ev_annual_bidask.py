"""Independent public annual EURUSD H1 bid/ask research feed.

The source is EV Trading Labs' publicly advertised annual candle catalog.
Its H1 annual files are aggregated from Dukascopy. This is an independent
distribution/format check, NOT an independently originated market feed.
Current-year 2026 (sealed holdout) is deliberately never requested.

Data and attribution: https://evtradelabs.com/data
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import urllib.request
from datetime import timezone

import pandas as pd

BASE = "https://evtradelabs.com/api/simulator/data/EURUSD/H1/"
FIELDS = ("o", "h", "l", "c", "ao", "ah", "al", "ac")


def parse_annual(raw: bytes, year: int) -> pd.DataFrame:
    if year not in (2022, 2023, 2024, 2025):
        raise ValueError("Only preregistered 2022–2025 development/validation data allowed")
    decoded = gzip.decompress(raw)
    obj = json.loads(decoded)
    rows = obj if isinstance(obj, list) else obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("Unexpected annual data format")
    frame = pd.DataFrame(rows)
    if not {"ts", *FIELDS}.issubset(set(frame.columns)):
        raise ValueError("Annual dataset lacks timestamp or bid/ask OHLC")
    if not all(pd.api.types.is_numeric_dtype(frame[col]) for col in ("ts", *FIELDS)):
        raise ValueError("Annual dataset contains nonnumeric OHLC values")
    if not len(frame) >= 5000:
        raise ValueError("Insufficient hourly records for a complete forex year")
    times = pd.to_datetime(frame["ts"], unit="s", utc=True, errors="raise")
    if times.dt.year.nunique() != 1 or int(times.dt.year.iloc[0]) != year:
        raise ValueError("Year mismatch or cross-year timestamps")
    if not times.is_monotonic_increasing or times.duplicated().any():
        raise ValueError("Duplicate or nonchronological hourly candles")
    if (frame["ts"].mod(3600) != 0).any():
        raise ValueError("Hour bars must be stamped on UTC hour boundary")
    ohlc = frame[list(FIELDS)].astype("float64")
    if not all(math.isfinite(v) for v in ohlc.to_numpy().ravel()):
        raise ValueError("Non-finite bid/ask price")
    if (ohlc <= 0).any().any():
        raise ValueError("Non-positive bid/ask price")
    for cols in (("o", "h", "l", "c"), ("ao", "ah", "al", "ac")):
        op, hi, lo, cl = (ohlc[name] for name in cols)
        if ((lo > op) | (lo > cl) | (hi < op) | (hi < cl) | (hi < lo)).any():
            raise ValueError("Bad bid/ask candle range")
    for b, a in zip(("o","h","l","c"),("ao","ah","al","ac")):
        if (ohlc[a] < ohlc[b]).any():
            raise ValueError("Negative historical bid/ask spread")

    result = pd.DataFrame(index=pd.DatetimeIndex(times, tz=timezone.utc))
    for name, source in zip(
        ("bid_open","bid_high","bid_low","bid_close",
         "ask_open","ask_high","ask_low","ask_close"),
        FIELDS,
    ):
        result[name] = ohlc[source].to_numpy()
    return result


def load_annual_bidask(years=(2022, 2023, 2024, 2025)):
    bars = []
    manifest = []
    for year in years:
        if year not in (2022,2023,2024,2025):
            raise ValueError("Sealed 2026 holdout is not authorized for research screening")
        url = f"{BASE}{year}.json.gz"
        request = urllib.request.Request(url, headers={
            "User-Agent": "Emtifize EURUSD academic research, source verified 2026-11",
            "Accept": "application/octet-stream",
        })
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise ValueError(f"Missing annual file HTTP {response.status}")
            raw = response.read(4_000_000)
        annual = parse_annual(raw, year)
        bars.append(annual)
        manifest.append({
            "year":year, "url":url,
            "sha256":hashlib.sha256(raw).hexdigest(), "bars":len(annual),
            "first": annual.index.min().isoformat(),
            "last": annual.index.max().isoformat(),
            "attribution":"EV Trading Labs — derived from Dukascopy ticks",
        })
    combined = pd.concat(bars)
    if combined.index.has_duplicates or not combined.index.is_monotonic_increasing:
        raise ValueError("Nonchronological annual concatenation")
    return combined, manifest
