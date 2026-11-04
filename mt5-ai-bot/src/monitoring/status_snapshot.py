"""Minimal non-sensitive engine heartbeat written atomically by the MT5 worker.

No account number, broker credentials, funds, positions, API keys or orders
are ever stored in this v1 snapshot. Read-only API uses it for health.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATUS_PATH = Path("runtime/engine_status.json")
VALID_STATES = {"running", "paused", "offline"}


def publish_status(
    path: str | Path,
    *,
    state: str,
    dry_run: bool,
    symbols: list[str],
    now: datetime | None = None,
) -> None:
    if state not in VALID_STATES:
        raise ValueError("Invalid engine status")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Status timestamp must have timezone")
    safe_symbols = [str(s)[:20] for s in symbols[:20]]
    record = {
        "schema_version": 1,
        "state": state,
        "mode": "dry_run" if dry_run else "live_configuration",
        "trading_enabled": state == "running" and not dry_run,
        "strategy": "atr_breakout",
        "symbols": safe_symbols,
        "updated_at": current.astimezone(timezone.utc).isoformat(),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def public_snapshot(path: str | Path, *, now: datetime | None = None) -> dict:
    offline = {
        "schema_version": 1, "state": "offline", "mode": "unknown",
        "trading_enabled": False, "strategy": None,
        "symbols": [], "updated_at": None, "stale": True,
    }
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        age = (current - stamp.astimezone(timezone.utc)).total_seconds()
        if not -5 <= age <= 30:
            return {**offline, "updated_at": record.get("updated_at")}
        if record.get("schema_version") != 1 or record.get("state") not in VALID_STATES:
            return offline
        # Strict allowlist avoids accidentally exposing added private fields.
        return {
            "schema_version": 1,
            "state": record["state"],
            "mode": record["mode"] if record.get("mode") in ("dry_run", "live_configuration") else "unknown",
            "trading_enabled": bool(record.get("trading_enabled", False)),
            "strategy": record.get("strategy") if record.get("strategy") == "atr_breakout" else None,
            "symbols": [
                s for s in record.get("symbols", [])[:20]
                if isinstance(s, str) and len(s) <= 20
            ],
            "updated_at": record["updated_at"],
            "stale": False,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return offline
