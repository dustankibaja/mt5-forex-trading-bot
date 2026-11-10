"""One-shot MT5 DEMO order firewall for MECHANICAL SMOKE TESTING ONLY.

Never intended to execute the currently unprofitable ATR strategy unattended.
Uses a dedicated local opt-in; no phone/browser command path.

Security properties:
- Broker must be connected AND trade_mode == DEMO immediately before send.
- Locally pinned account fingerprint (never exposed through API) must match.
- Static EURUSD-only order, at most ONE lifetime smoke attempt until audited
  broker reconciliation is implemented; no auto-unlocking across UTC days.
- Broker-side SL and TP required, risk capped at 0.25% with slip/fees buffer,
  max 25% margin/free margin, fresh quote/spread, no any-symbol positions/orders.
- Durable SQLite intent COMMITTED *before* exactly one order_send. Unknown
  result is NEVER retried automatically. Restart requires broker reconciliation.
- No funded account mode; no retry, no position-changing API on Android.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.execution.demo_quote_time import quote_time_blocker

SYMBOL = "EURUSD"
MAGIC = 830117
PIP = 0.0001
DEFAULT_LEDGER = Path("runtime/demo_smoke_ledger.sqlite3")
DEFAULT_PIN = Path("runtime/demo_broker_pin.json")
MAX_RISK_PCT = 0.25
MAX_SPREAD_PIPS = 2.0
STOP_PIPS = 20
TARGET_PIPS = 40
ADVERSE_EXTRA_PIPS = 2
FEE_RESERVE_USD = 2.0


class DemoSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeResult:
    status: str
    order_retcode: int | None
    attempted: bool
    reason: str

    def public_report(self) -> dict[str, Any]:
        return {"status": self.status, "order_retcode": self.order_retcode,
                "attempted": self.attempted, "reason": self.reason,
                "live_trading_enabled": False}


def _account(api):
    terminal = api.terminal_info()
    account = api.account_info()
    if (terminal is None or not getattr(terminal, "connected", False)
            or not getattr(terminal, "trade_allowed", False)
            or getattr(terminal, "tradeapi_disabled", True)
            or account is None
            or getattr(account, "trade_mode", None) != api.ACCOUNT_TRADE_MODE_DEMO
            or not getattr(account, "trade_allowed", False)
            or not getattr(account, "trade_expert", False)):
        raise DemoSafetyError("Terminal disconnected, unauthorized, or NOT a trading-enabled DEMO")
    return account


def _check_order_budget(account, potential_loss: float, margin: float) -> None:
    # MT5 returns stop loss and margin in account currency. The fee reserve
    # is in USD, so this fixed smoke order only supports USD accounts.
    if getattr(account, "currency", None) != "USD":
        raise DemoSafetyError("USD account currency required for DEMO smoke risk")
    equity = float(getattr(account, "equity", float("nan")))
    free_margin = float(getattr(account, "margin_free", float("nan")))
    if not math.isfinite(equity) or potential_loss > equity * MAX_RISK_PCT / 100:
        raise DemoSafetyError("Broker minimum-lot stop risk exceeds 0.25% equity")
    if not math.isfinite(free_margin) or not 0 < margin <= free_margin * 0.25:
        raise DemoSafetyError("Broker min lot consumes too much free margin")


def _identity(account) -> bytes:
    login, server = getattr(account, "login", None), getattr(account, "server", None)
    if not isinstance(login, int) or login <= 0 or not isinstance(server, str) or not server:
        raise DemoSafetyError("Cannot read verified DEMO account identity")
    return f"{server}|{login}".encode("utf-8")


def initialize_broker_pin(api, path: Path = DEFAULT_PIN) -> None:
    """Pin DEMO account to local random-salt SHA256; never show login/server."""
    account = _account(api)
    pin = Path(path)
    pin.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(32)
    digest = hashlib.sha256(salt + _identity(account)).hexdigest()
    record = json.dumps({"schema": 1, "salt": salt.hex(), "digest": digest},
                        separators=(",", ":")).encode()
    try:
        descriptor = os.open(str(pin), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise DemoSafetyError("DEMO account already pinned; no silent repinning") from exc
    with os.fdopen(descriptor, "wb") as target:
        target.write(record)
        target.flush()
        os.fsync(target.fileno())


def _require_pin(account, path: Path) -> str:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        if record["schema"] != 1:
            raise ValueError("Unsupported pin")
        salt = bytes.fromhex(record["salt"])
        digest = hashlib.sha256(salt + _identity(account)).hexdigest()
        if not hmac.compare_digest(digest, record["digest"]):
            raise DemoSafetyError("DEMO broker account changed; pin mismatch")
        return digest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DemoSafetyError("Valid pinned DEMO identity required") from exc


def _ledger_connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20, isolation_level=None)
    con.execute("PRAGMA synchronous=FULL")
    con.execute("""CREATE TABLE IF NOT EXISTS smoke_intents (
      account_digest TEXT NOT NULL, day_utc TEXT NOT NULL,
      symbol TEXT NOT NULL, sent_at TEXT NOT NULL, status TEXT NOT NULL,
      retcode INTEGER, PRIMARY KEY (account_digest, day_utc, symbol)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS smoke_receipts (
      account_digest TEXT NOT NULL, day_utc TEXT NOT NULL, symbol TEXT NOT NULL,
      order_ticket INTEGER NOT NULL, deal_ticket INTEGER NOT NULL,
      PRIMARY KEY (account_digest, day_utc, symbol)
    )""")
    return con


def _reserve_intent(path: Path, digest: str, day: str, at: str) -> None:
    con = _ledger_connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        # Any historical attempt may still be open or awaiting broker history.
        # Even a known DONE result is NOT evidence that the resulting position
        # has closed, and the current system has no audited reconciliation
        # workflow. Fail closed across ALL UTC dates and all account digests.
        # Do not whitelist statuses here until durable reconciliation exists.
        previous = con.execute(
            "SELECT day_utc,status FROM smoke_intents LIMIT 1"
        ).fetchone()
        if previous is not None:
            con.execute("ROLLBACK")
            raise DemoSafetyError(
                "Prior DEMO smoke intent requires verified broker reconciliation;"
                " further orders locked across dates"
            )
        try:
            con.execute(
                "INSERT INTO smoke_intents(account_digest,day_utc,symbol,sent_at,status)"
                " VALUES (?,?,?,?,?)",
                (digest, day, SYMBOL, at, "ATTEMPT_RESERVED"),
            )
        except sqlite3.IntegrityError as exc:
            con.execute("ROLLBACK")
            raise DemoSafetyError("Duplicate DEMO intent blocked") from exc
        con.execute("COMMIT")
    finally:
        con.close()


def _record_result(path: Path, digest: str, day: str, status: str,
                   retcode: int | None, receipt=None) -> None:
    con = _ledger_connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "UPDATE smoke_intents SET status=?,retcode=?"
            " WHERE account_digest=? AND day_utc=? AND symbol=?",
            (status, retcode, digest, day, SYMBOL),
        )
        if receipt is not None:
            con.execute(
                "INSERT INTO smoke_receipts VALUES (?,?,?,?,?)",
                (digest, day, SYMBOL, getattr(receipt, "order", 0),
                 getattr(receipt, "deal", 0)),
            )
        con.execute("COMMIT")
    finally:
        con.close()


def _require_flat_account(api) -> None:
    """Block when the DEMO account has ANY position or pending order.

    MT5 positions_get()/orders_get() with NO symbol argument returns the
    complete account's positions/orders. Filtering only EURUSD is unsafe:
    unrelated manual exposure would otherwise be overlooked.
    """
    positions = api.positions_get()
    orders = api.orders_get()
    if positions is None or orders is None:
        raise DemoSafetyError("Cannot reconcile account-wide positions and orders")
    if len(positions) or len(orders):
        raise DemoSafetyError("DEMO account has positions or pending orders")


def execute_one_demo_smoke(
    api,
    *,
    pin_path: Path = DEFAULT_PIN,
    ledger_path: Path = DEFAULT_LEDGER,
    manual_kill_switch: Path = Path("KILL_SWITCH"),
    remote_pause_path: Path = Path("runtime/remote_pause.flag"),
    execute: bool = False,
    utcnow: datetime | None = None,
) -> SmokeResult:
    """Broker-side DEMO test order. Default is READ-ONLY. No blind retries."""
    if not execute:
        return SmokeResult("BLOCKED", None, False, "Explicit local DEMO execution not armed")
    if manual_kill_switch.exists() or remote_pause_path.exists():
        raise DemoSafetyError("A manual or phone pause is active")
    current = utcnow or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise DemoSafetyError("UTC clock is required")
    current = current.astimezone(timezone.utc)
    if current.weekday() > 4:
        raise DemoSafetyError("DEMO smoke only allowed on active weekdays")

    account = _account(api)
    digest = _require_pin(account, pin_path)
    for field in ("equity", "margin_free"):
        if not math.isfinite(float(getattr(account, field, float("nan")))) or (
                float(getattr(account, field)) <= 0):
            raise DemoSafetyError("Invalid broker account equity/margin")

    info = api.symbol_info(SYMBOL)
    if (info is None or not getattr(info, "visible", False)
            or getattr(info, "trade_mode", None) != api.SYMBOL_TRADE_MODE_FULL
            or getattr(info, "digits", None) not in (4, 5)
            or not math.isfinite(float(getattr(info, "point", float("nan"))))
            or float(getattr(info, "point")) <= 0):
        raise DemoSafetyError("Unsupported/unavailable EURUSD contract")
    lots = float(getattr(info, "volume_min", 0))
    step = float(getattr(info, "volume_step", 0))
    maximum = float(getattr(info, "volume_max", 0))
    if not (math.isfinite(lots) and math.isfinite(step) and math.isfinite(maximum)
            and 0 < lots <= maximum and 0 < step
            and abs(lots / step - round(lots / step)) < 1e-7):
        raise DemoSafetyError("Broker minimum lot not valid for incremental sizing")
    if info.trade_stops_level * info.point >= STOP_PIPS * PIP:
        raise DemoSafetyError("Broker stop-distance minimum too high")

    tick = api.symbol_info_tick(SYMBOL)
    if tick is None:
        raise DemoSafetyError("Missing broker quote")
    timestamp_blocker = quote_time_blocker(
        tick, utcnow.timestamp() if utcnow else time.time()
    )
    if timestamp_blocker:
        raise DemoSafetyError(timestamp_blocker)
    bid, ask = float(tick.bid), float(tick.ask)
    if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
        raise DemoSafetyError("Invalid broker quote")
    if (ask - bid) / PIP > MAX_SPREAD_PIPS:
        raise DemoSafetyError("Spread exceeds DEMO smoke limit")

    _require_flat_account(api)

    # DEMO smoke direction fixed BUY; this has NO claim to profit potential.
    direction = api.ORDER_TYPE_BUY
    stop = round(ask - STOP_PIPS * PIP, info.digits)
    target = round(ask + TARGET_PIPS * PIP, info.digits)
    if stop >= ask or target <= ask:
        raise DemoSafetyError("Invalid protective stop and target")
    buffered_stop = stop - ADVERSE_EXTRA_PIPS * PIP
    stop_loss = api.order_calc_profit(direction, SYMBOL, lots, ask, buffered_stop)
    margin = api.order_calc_margin(direction, SYMBOL, lots, ask)
    if stop_loss is None or margin is None:
        raise DemoSafetyError("Missing broker stop loss/margin calculations")
    potential_loss = abs(float(stop_loss)) + FEE_RESERVE_USD
    if not math.isfinite(potential_loss) or float(stop_loss) >= 0:
        raise DemoSafetyError("Broker minimum-lot stop risk exceeds 0.25% equity")
    _check_order_budget(account, potential_loss, float(margin))

    request = {
        "action": api.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": lots, "type": direction, "price": ask,
        "sl": stop, "tp": target, "deviation": 10,
        "magic": MAGIC, "comment": "EMTIFIZE_DEMO_SMOKE",
        "type_time": api.ORDER_TIME_GTC,
        "type_filling": api.ORDER_FILLING_FOK,
    }
    check = api.order_check(request)
    if check is None or getattr(check, "retcode", None) != 0:
        raise DemoSafetyError("Broker refused order_check; no order submitted")

    # Reconfirm identity, permissions and pause in the immediate send path.
    fresh_account = _account(api)
    if _require_pin(fresh_account, pin_path) != digest:
        raise DemoSafetyError("Account identity changed before DEMO send")
    if manual_kill_switch.exists() or remote_pause_path.exists():
        raise DemoSafetyError("Kill switch activated during order check")
    fresh_tick = api.symbol_info_tick(SYMBOL)
    timestamp_blocker = quote_time_blocker(
        fresh_tick, utcnow.timestamp() if utcnow else time.time()
    )
    if timestamp_blocker:
        raise DemoSafetyError(timestamp_blocker)
    if float(fresh_tick.ask) != ask or float(fresh_tick.bid) != bid:
        raise DemoSafetyError("Broker quote changed before DEMO send")
    _require_flat_account(api)

    day = current.strftime("%Y-%m-%d")
    _reserve_intent(ledger_path, digest, day, current.isoformat())
    # SQLite may wait on another process. Revalidate the exact checked prices,
    # exposure and account after that wait, before entering the broker send path.
    _require_flat_account(api)
    final_tick = api.symbol_info_tick(SYMBOL)
    timestamp_blocker = quote_time_blocker(
        final_tick, utcnow.timestamp() if utcnow else time.time()
    )
    if timestamp_blocker:
        raise DemoSafetyError(timestamp_blocker)
    if float(final_tick.ask) != ask or float(final_tick.bid) != bid:
        raise DemoSafetyError("Broker quote changed during durable reservation")
    final_account = _account(api)
    if _require_pin(final_account, pin_path) != digest:
        raise DemoSafetyError("Account identity changed during durable reservation")
    _check_order_budget(final_account, potential_loss, float(margin))
    if manual_kill_switch.exists() or remote_pause_path.exists():
        raise DemoSafetyError("Kill switch activated during durable reservation")
    try:
        result = api.order_send(request)   # Exactly ONE broker call.
    except Exception:
        _record_result(ledger_path, digest, day, "UNKNOWN_BROKER_OUTCOME", None)
        raise DemoSafetyError("Unknown broker outcome; never retry without reconciliation")
    if result is None:
        _record_result(ledger_path, digest, day, "UNKNOWN_BROKER_OUTCOME", None)
        raise DemoSafetyError("No broker result; never retry automatically")

    retcode = int(result.retcode)
    if retcode == api.TRADE_RETCODE_DONE:
        status = "DEMO_ORDER_FILLED"
    elif retcode == getattr(api, "TRADE_RETCODE_DONE_PARTIAL", -1):
        status = "DEMO_PARTIAL_FILL_RECONCILE"
    else:
        status = "DEMO_ORDER_OUTCOME_RECONCILE"
    _record_result(ledger_path, digest, day, status, retcode, receipt=result)
    return SmokeResult(status, retcode, True, "Broker record/reconciliation required")
