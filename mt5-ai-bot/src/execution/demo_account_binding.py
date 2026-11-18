"""Durable local binding for one explicitly selected MT5 DEMO installation.

The record contains salted hashes only. It never stores or changes broker
credentials and cannot switch the terminal account.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path


class AccountBindingError(RuntimeError):
    pass


def _value(obj, name: str):
    value = getattr(obj, name, None)
    if value is None or isinstance(value, str) and not value:
        raise AccountBindingError(f"MT5 {name} identity is unavailable")
    return value


def _payload(api) -> bytes:
    terminal, account = api.terminal_info(), api.account_info()
    if terminal is None or account is None:
        raise AccountBindingError("MT5 terminal/account is unavailable")
    if getattr(account, "trade_mode", None) != api.ACCOUNT_TRADE_MODE_DEMO:
        raise AccountBindingError("Only an independently authenticated DEMO account may be bound")
    values = (
        str(_value(terminal, "path")),
        str(_value(terminal, "data_path")),
        str(_value(account, "server")),
        str(_value(account, "login")),
    )
    return "\0".join(values).encode("utf-8")


def create_local_binding(api, path: Path) -> dict:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(32)
    digest = hashlib.sha256(salt + _payload(api)).hexdigest()
    account = api.account_info()
    record = {
        "schema": "emtifize-demo-binding-v1",
        "salt": salt.hex(),
        "digest": digest,
        "account_label": f"••••{str(account.login)[-4:]}",
        "server_label": f"{str(account.server)[:3]}…",
    }
    try:
        descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise AccountBindingError("Local DEMO binding already exists; silent replacement is prohibited") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    return {"account_label": record["account_label"], "server_label": record["server_label"], "binding_id": digest[:16]}


def verify_local_binding(api, path: Path) -> dict:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        if record.get("schema") != "emtifize-demo-binding-v1":
            raise ValueError("unsupported binding")
        salt = bytes.fromhex(record["salt"])
        actual = hashlib.sha256(salt + _payload(api)).hexdigest()
        if not hmac.compare_digest(actual, record["digest"]):
            raise AccountBindingError("MT5 terminal, data directory, server or DEMO account changed")
        return {"verified": True, "account_label": record["account_label"], "server_label": record["server_label"], "binding_id": actual[:16]}
    except AccountBindingError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AccountBindingError("Valid local DEMO binding is required") from error
