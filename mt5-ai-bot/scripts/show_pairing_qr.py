"""Display a local, private QR for the already running DEMO bridge.

This script DOES NOT transmit or persist the QR payload. Secrets are read
only from the parent PowerShell process environment. Never screenshot or
post the QR, since it grants read-only + demo simulation controls.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse


def build_pairing_payload(base_url: str, read_token: str, control_token: str) -> str:
    parsed = urlparse(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or
            not parsed.hostname.endswith(".ts.net") or
            parsed.username or parsed.password or parsed.port or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Pairing URL must be a private Tailscale HTTPS host")
    if (len(read_token) < 40 or len(control_token) < 40 or
            read_token == control_token):
        raise ValueError("Two different strong pairing credentials required")
    return json.dumps({
        "type": "emtifize-pair-v1",
        "url": f"https://{parsed.hostname}",
        "read_token": read_token,
        "control_token": control_token,
    }, separators=(",", ":"))


def main() -> int:
    # Intentionally never print any credentials or QR payload.
    url = os.environ.get("EMTIFIZE_PAIR_URL", "")
    read = os.environ.get("BOT_STATUS_READ_TOKEN", "")
    control = os.environ.get("BOT_DEMO_CONTROL_TOKEN", "")
    payload = build_pairing_payload(url, read, control)

    import tkinter as tk
    from PIL import ImageTk
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=7,
        border=3,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    picture = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    window = tk.Tk()
    window.title("Emtifize AI · Private phone pairing")
    window.configure(bg="#101829")
    window.resizable(False, False)
    tk.Label(window, text="Scan with Emtifize AI", font=("Segoe UI", 17, "bold"),
             fg="white", bg="#101829").pack(padx=22, pady=(18, 6))
    tk.Label(window, text="Open the phone app → Scan Windows QR",
             font=("Segoe UI", 11), fg="#b3c0d4", bg="#101829").pack()
    image = ImageTk.PhotoImage(picture)
    label = tk.Label(window, image=image, bg="white")
    label.image = image
    label.pack(padx=24, pady=14)
    tk.Label(window, text=url, font=("Segoe UI", 10),
             fg="#b3c0d4", bg="#101829").pack()
    tk.Label(window, text="PRIVATE: Do not screenshot or share this QR.",
             font=("Segoe UI", 10, "bold"), fg="#f5b963",
             bg="#101829").pack(pady=(12, 8))
    tk.Button(window, text="Close", command=window.destroy,
              font=("Segoe UI", 12), padx=20, pady=5).pack(pady=(6, 20))
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
