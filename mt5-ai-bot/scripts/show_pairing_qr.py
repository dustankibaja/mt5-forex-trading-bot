"""Display a PRIVATE local QR code for Emtifize AI; never print secrets.

Requires qrcode[pil] (in requirements.txt). Payload contains both private
tokens and grants monitoring + DEMO simulation control. Treat the QR like
credentials. The PNG is a local TEMPORARY file: delete after scanning.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import qrcode


def payload_from_env() -> str:
    url = os.environ.get("EMTIFIZE_PAIR_URL", "").rstrip("/")
    read = os.environ.get("BOT_STATUS_READ_TOKEN", "")
    control = os.environ.get("BOT_DEMO_CONTROL_TOKEN", "")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or
            not parsed.hostname.endswith(".ts.net") or
            parsed.username or parsed.password or parsed.query or
            parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("Expected private Tailscale HTTPS hostname")
    if (len(read) < 32 or len(control) < 32 or read == control or
            not re.fullmatch(r"[A-Za-z0-9_-]+", read) or
            not re.fullmatch(r"[A-Za-z0-9_-]+", control)):
        raise ValueError("Separate strong pairing tokens are required")
    return json.dumps({
        "type": "emtifize-pair-v1",
        "url": url,
        "read_token": read,
        "control_token": control,
    }, separators=(",", ":"))


def main() -> int:
    try:
        payload = payload_from_env()
    except ValueError as exc:
        print(f"QR not created: {exc}", file=sys.stderr)
        return 2

    output = Path("runtime/pairing-PRIVATE-DELETE-AFTER-SCAN.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    image = qrcode.make(payload)
    image.save(output)
    print("Private QR ready. Do NOT screenshot, email, upload or share it.")
    print("Scan using Emtifize AI on YOUR phone and close/delete it afterwards.")
    if sys.platform == "win32":
        os.startfile(str(output.resolve()))  # nosec B606: local PNG viewer only
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
