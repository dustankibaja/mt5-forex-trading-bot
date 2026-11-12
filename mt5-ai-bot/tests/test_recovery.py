import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.monitoring.recovery import (
    Backoff, RecoveryBlocked, RecoveryUnavailable, read_binding, verify_session,
)
from src.monitoring.shadow_diagnostics import ProspectiveJournal


class Terminal:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, installation):
        self.info = SimpleNamespace(connected=True, path=str(installation), trade_allowed=False)
        self.account = SimpleNamespace(login=123, server="test", trade_mode=0)

    def terminal_info(self):
        return self.info

    def account_info(self):
        return self.account


def test_session_recovery_distinguishes_disconnection_and_identity_block(tmp_path):
    terminal = tmp_path / "terminal64.exe"
    api = Terminal(tmp_path)
    salt = "fixture-salt"
    digest = hashlib.sha256((salt + json.dumps((123, "test"), separators=(",", ":"))).encode()).hexdigest()
    binding = (salt, digest)
    assert verify_session(api, binding, terminal) == (123, "test")
    api.info.connected = False
    with pytest.raises(RecoveryUnavailable, match="terminal_disconnected"):
        verify_session(api, binding, terminal)
    api.info.connected = True
    assert verify_session(api, binding, terminal) == (123, "test")
    api.account.login = 456
    with pytest.raises(RecoveryBlocked, match="identity_mismatch"):
        verify_session(api, binding, terminal)
    api.account.trade_mode = 2
    with pytest.raises(RecoveryBlocked, match="not_demo"):
        verify_session(api, binding, terminal)
    api.account = None
    with pytest.raises(RecoveryBlocked, match="session_missing"):
        verify_session(api, binding, terminal)


def test_read_binding_fails_closed_for_corrupt_missing_or_unbound_journal(tmp_path):
    path = tmp_path / "journal.sqlite3"
    with pytest.raises(RecoveryBlocked, match="journal_unavailable"):
        read_binding(path)
    assert not path.exists()
    path.write_bytes(b"invalid sqlite")
    with pytest.raises(RecoveryBlocked, match="journal_unavailable"):
        read_binding(path)
    assert path.read_bytes() == b"invalid sqlite"
    path = tmp_path / "unbound.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE forward_source(singleton INTEGER, salt TEXT, digest TEXT)")
    with pytest.raises(RecoveryBlocked, match="binding_missing"):
        read_binding(path)
    journal = ProspectiveJournal(path, existing_only=True)
    with pytest.raises(RuntimeError, match="binding missing"):
        journal._persist({}, None)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM forward_source").fetchone() == (0,)


def test_retry_budget_is_bounded_and_exponential():
    budget = Backoff()
    assert [budget.delay() for _ in range(8)] == [5, 10, 20, 40, 80, 120, 120, 120]
    with pytest.raises(RecoveryBlocked, match="restart_budget_exhausted"):
        budget.delay()
