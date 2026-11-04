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


def token_valid(header: str | None, token: str) -> bool:
    if not header or not token or len(token) < 32:
        return False
    scheme, sep, supplied = header.partition(" ")
    return bool(
        sep and scheme.lower() == "bearer"
        and hmac.compare_digest(supplied, token)
    )


def build_handler(token: str, status_path: Path):
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
            if self.path != "/v1/status":
                self._reply(404, {"error": "not_found"})
                return
            if not token_valid(self.headers.get("Authorization"), token):
                self._reply(401, {"error": "unauthorized"})
                return
            self._reply(200, public_snapshot(status_path))

        def do_POST(self):
            self._reply(405, {"error": "read_only"})

        do_PUT = do_DELETE = do_PATCH = do_POST

        def log_message(self, fmt, *args):
            # No headers or credentials in stdout.
            pass

    return StatusHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    args = parser.parse_args()
    token = os.environ.get("BOT_STATUS_READ_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Set BOT_STATUS_READ_TOKEN to a random token >=32 characters")
    if not (1024 <= args.port <= 65535):
        raise SystemExit("Port must be 1024..65535")

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), build_handler(token, args.status_path)
    )
    print(f"Read-only status API: http://127.0.0.1:{args.port}/v1/status")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
