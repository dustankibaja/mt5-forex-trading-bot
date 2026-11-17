"""MT5-free integration checks for separate-token DEMO simulation controls."""
import json
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.serve_status import build_handler
from src.monitoring.demo_controls import demo_paused, pause_demo, resume_demo
from src.monitoring.status_snapshot import publish_status


READ = "r" * 50
CONTROL = "c" * 50


def _request(base, path, token, method="POST"):
    request = Request(
        base + path,
        headers={"Authorization": "Bearer " + token},
        method=method,
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as response:
        return response.code, json.load(response)


def test_remote_flag_does_not_modify_manual_kill_switch(tmp_path):
    remote = tmp_path / "runtime" / "remote.flag"
    manual = tmp_path / "KILL_SWITCH"
    manual.write_text("manual-stop")
    pause_demo(remote)
    pause_demo(remote)
    assert demo_paused(remote)
    resume_demo(remote)
    assert not demo_paused(remote)
    assert manual.read_text() == "manual-stop"


def test_separate_secret_and_safeguarded_resume(tmp_path):
    now = datetime.now(timezone.utc)
    status = tmp_path / "status.json"
    demo = tmp_path / "demo.json"
    pause = tmp_path / "remote.flag"
    publish_status(status, state="paused", dry_run=True,
                   demo_guarded=True, symbols=["EURUSD"], now=now)
    demo.write_text(json.dumps({
        "schema_version": 1, "available": True, "stale": False,
        "account_type": "demo", "updated_at": now.isoformat(),
        "currency": "USD", "balance": 10000.0, "equity": 10000.0,
        "margin_free": 10000.0, "floating_pnl": 0.0,
        "positions": [], "recent_closing_deals": [],
    }))
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        build_handler(READ, status, demo, CONTROL, pause),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        # The read token cannot send commands; separate credentials matter.
        assert _request(base, "/v1/demo-control/pause", READ)[0] == 401
        assert not demo_paused(pause)

        code, data = _request(base, "/v1/demo-control/pause", CONTROL)
        assert code == 200
        assert data == {"ok": True, "remote_paused": True}
        assert demo_paused(pause)

        # Status client sees whether command controls exist, never sees token.
        code, data = _request(base, "/v1/status", READ, method="GET")
        assert code == 200
        assert data["remote_paused"] is True
        assert data["demo_guarded"] is True
        assert data["remote_control_available"] is True
        assert CONTROL not in json.dumps(data)

        code, data = _request(base, "/v1/demo-control/resume", CONTROL)
        assert code == 200
        assert data["remote_paused"] is False
        assert not demo_paused(pause)

        # A live-config heartbeat MUST NOT authorize resume.
        pause_demo(pause)
        publish_status(status, state="paused", dry_run=False,
                       symbols=["EURUSD"], now=now)
        assert _request(base, "/v1/demo-control/resume", CONTROL)[0] == 409
        assert demo_paused(pause)

        # Even a dry-run without an explicit demo-only guard is refused.
        publish_status(status, state="paused", dry_run=True,
                       demo_guarded=False, symbols=["EURUSD"], now=now)
        assert _request(base, "/v1/demo-control/resume", CONTROL)[0] == 409
        assert demo_paused(pause)

        # A pause remains available during engine outages for fail-safe startup.
        assert _request(base, "/v1/demo-control/pause", CONTROL)[0] == 200
        assert demo_paused(pause)

        # No remotely callable market order endpoint exists.
        assert _request(base, "/v1/orders", CONTROL)[0] == 405
        assert _request(base, "/v1/demo-account", CONTROL)[0] == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
