#!/usr/bin/env python3
"""Local, READ-ONLY HTTP endpoint for an authenticated Flutter status client.

Bind loopback only. For phone access, terminate TLS at a trusted reverse proxy
or private tunnel; NEVER expose raw port 8787 to the public Internet.
No broker connection, trade commands or credentials are accepted here.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.monitoring.status_snapshot import DEFAULT_STATUS_PATH, public_snapshot
from src.monitoring.demo_account_snapshot import DEFAULT_DEMO_PATH, public_demo_snapshot
from src.monitoring.demo_controls import DEFAULT_PAUSE_PATH, demo_paused, pause_demo, resume_demo


def token_valid(header: str | None, token: str) -> bool:
    if not header or not token or len(token) < 32:
        return False
    scheme, sep, supplied = header.partition(" ")
    return bool(
        sep and scheme.lower() == "bearer"
        and hmac.compare_digest(supplied, token)
    )


def build_handler(
    token: str,
    status_path: Path,
    demo_path: Path = DEFAULT_DEMO_PATH,
    control_token: str = "",
    pause_path: Path = DEFAULT_PAUSE_PATH,
):
    class StatusHandler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: dict):
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, private")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path not in ("/v1/status", "/v1/demo-account"):
                self._reply(404, {"error": "not_found"})
                return
            if not token_valid(self.headers.get("Authorization"), token):
                self._reply(401, {"error": "unauthorized"})
                return
            status = public_snapshot(status_path)
            if self.path == "/v1/status":
                self._reply(200, {**status, "remote_paused": demo_paused(pause_path),
                                  "remote_control_available": len(control_token) >= 32})
                return
            # Never release balances when MT5 is disconnected, stale or
            # configured for trading. Account endpoint requires healthy dry-run.
            if (status["stale"] or status["state"] not in ("running", "paused")
                    or status["mode"] != "dry_run"
                    or status["trading_enabled"]):
                self._reply(503, {"error": "demo_engine_unavailable"})
                return
            self._reply(200, public_demo_snapshot(demo_path))

        def do_POST(self):
            # Dedicated DEMO-only signal-simulation PAUSE/RESUME controls.
            # No routes for orders, accounts, broker configuration, or SL/TP.
            if self.path not in ("/v1/demo-control/pause", "/v1/demo-control/resume"):
                self._reply(405, {"error": "unsupported_operation"})
                return
            if (len(control_token) < 32 or
                    not token_valid(self.headers.get("Authorization"), control_token)):
                self._reply(401, {"error": "control_unauthorized"})
                return
            if self.headers.get("Content-Length", "0") not in ("", "0"):
                self._reply(400, {"error": "control_body_not_allowed"})
                return
            if self.path.endswith("/pause"):
                # PAUSE is always allowed for a valid control key, even when
                # the worker is offline: it must remain fail-safe on restart.
                try:
                    pause_demo(pause_path)
                except OSError:
                    self._reply(503, {"error": "pause_file_unavailable"})
                    return
                self._reply(200, {"ok": True, "remote_paused": True})
                return

            status = public_snapshot(status_path)
            demo = public_demo_snapshot(demo_path)
            if (status["stale"] or status["state"] not in ("running", "paused")
                    or status["mode"] != "dry_run"
                    or status["trading_enabled"] or
                    status.get("demo_guarded") is not True or
                    demo["available"] is not True or demo["account_type"] != "demo"):
                self._reply(409, {"error": "demo_only_resume_blocked"})
                return
            # Removing the remote flag NEVER clears the manual kill switch.
            try:
                resume_demo(pause_path)
            except OSError:
                self._reply(503, {"error": "resume_file_unavailable"})
                return
            self._reply(200, {"ok": True, "remote_paused": False})

        do_PUT = do_DELETE = do_PATCH = do_POST

        def log_message(self, fmt, *args):
            # No headers or credentials in stdout.
            pass

    return StatusHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--demo-path", type=Path,
                        default=Path(os.environ.get("BOT_DEMO_ACCOUNT_PATH", str(DEFAULT_DEMO_PATH))))
    parser.add_argument("--pause-path", type=Path,
                        default=Path(os.environ.get("BOT_REMOTE_PAUSE_PATH", str(DEFAULT_PAUSE_PATH))))
    args = parser.parse_args()
    token = os.environ.get("BOT_STATUS_READ_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Set BOT_STATUS_READ_TOKEN to a random token >=32 characters")
    control_token = os.environ.get("BOT_DEMO_CONTROL_TOKEN", "")
    if control_token and (len(control_token) < 32 or control_token == token):
        raise SystemExit("BOT_DEMO_CONTROL_TOKEN must be independent and >=32 characters")
    if not (1024 <= args.port <= 65535):
        raise SystemExit("Port must be 1024..65535")

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        build_handler(token, args.status_path, args.demo_path, control_token, args.pause_path)
    )
    print(f"Read-only status API: http://127.0.0.1:{args.port}/v1/status")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
