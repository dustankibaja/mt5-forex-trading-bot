"""Display an in-memory PRIVATE pairing QR; never save/print credentials.

The visible QR grants demo controls. Close the local window after pairing.
"""
from __future__ import annotations

import json
import os
import re
import sys
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

    # Keep the credential-bearing QR ONLY in this local window's memory.
    # It is never written to a file, terminal, log or cloud service.
    import tkinter as tk
    from PIL import ImageTk

    root = tk.Tk()
    root.title("Emtifize AI - PRIVATE PAIRING")
    root.configure(bg="#111A2B")
    root.resizable(False, False)
    title = tk.Label(root, text="Scan once with Emtifize AI",
                     fg="white", bg="#111A2B", font=("Segoe UI", 16, "bold"))
    title.pack(padx=20, pady=(18, 8))
    qr_image = qrcode.make(payload).convert("RGB").resize((390, 390))
    photo = ImageTk.PhotoImage(qr_image, master=root)
    qr_label = tk.Label(root, image=photo, borderwidth=0)
    qr_label.image = photo
    qr_label.pack(padx=22, pady=8)
    note = tk.Label(root, text="PRIVATE: this QR grants demo controls.\n"
                    "Never photograph, share, or upload it. Close after scanning.",
                    fg="#FFCC88", bg="#111A2B", font=("Segoe UI", 10))
    note.pack(padx=20, pady=(8, 12))
    tk.Button(root, text="Close after pairing", command=root.destroy,
              width=25).pack(pady=(0, 20))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
