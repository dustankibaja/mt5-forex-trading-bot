"""Recovery policy and journal binding for monitoring-only workers."""
import hashlib
import hmac
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

RETRY = 2
BLOCKED = 3


class RecoveryBlocked(RuntimeError):
    pass


class RecoveryUnavailable(RuntimeError):
    pass


def read_binding(journal):
    try:
        with closing(sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RecoveryBlocked("journal_integrity")
            result = db.execute("SELECT salt,digest FROM forward_source WHERE singleton=1").fetchone()
            if (not result or not isinstance(result[0], str) or not result[0]
                    or not isinstance(result[1], str) or len(result[1]) != 64):
                raise RecoveryBlocked("journal_binding_missing")
            return result
    except sqlite3.Error as exc:
        raise RecoveryBlocked("journal_unavailable") from exc


def verify_session(api, binding, terminal_exe):
    terminal = api.terminal_info()
    if terminal is None or not terminal.connected:
        raise RecoveryUnavailable("terminal_disconnected")
    if terminal_exe.parent.resolve() != Path(terminal.path).resolve():
        raise RecoveryBlocked("terminal_installation_changed")
    account = api.account_info()
    if account is None or not account.login:
        raise RecoveryBlocked("account_session_missing")
    if account.trade_mode != api.ACCOUNT_TRADE_MODE_DEMO:
        raise RecoveryBlocked("account_not_demo")
    if terminal.trade_allowed:
        raise RecoveryBlocked("desktop_algo_enabled")
    identity = (account.login, account.server)
    encoded = json.dumps(identity, separators=(",", ":"))
    actual = hashlib.sha256((binding[0] + encoded).encode()).hexdigest()
    if not hmac.compare_digest(actual, binding[1]):
        raise RecoveryBlocked("journal_identity_mismatch")
    return identity


@contextmanager
def windows_lock(path):
    """Hold a byte lock until the process exits, including abrupt exit."""
    import msvcrt

    with path.open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RecoveryBlocked("duplicate_process_lock") from exc
        yield


@dataclass
class Backoff:
    limit: int = 8
    failures: int = 0

    def delay(self):
        self.failures += 1
        if self.failures > self.limit:
            raise RecoveryBlocked("restart_budget_exhausted")
        return min(120, 5 * 2 ** (self.failures - 1))
