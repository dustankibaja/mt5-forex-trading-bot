# Emtifize AI v1.3 — Scan once / remember the Windows DEMO bot

## User flow
1. Keep MetaTrader 5 open on Windows, connected to the same broker-issued DEMO account.
2. Install the updated Windows source branch `feature/persistent-qr-pairing-2026-11`.
3. Install Python dependencies, including `qrcode[pil]==8.2`.
4. Run `start_demo_phone_bridge.ps1`. The bridge stores two secrets encrypted with Windows DPAPI for **the current Windows user** in gitignored `runtime/*.dpapi`. Secrets are reused, not regenerated on every startup.
5. The Windows PC displays a **local, temporary in-memory QR window** (QR data never saved to disk or uploaded). The window is shown only if `tailscale serve status` reports the private HTTPS hostname.
6. Install Android APK v1.3; tap **Scan QR on Windows PC**, point camera at QR, and connect. The Android app securely persists the private HTTPS host, read-only and demo-control tokens, using Android Keystore-backed `flutter_secure_storage`. Android backup is disabled.
7. Close the QR window after the scan. The QR grants both read access and DEMO simulation control—never photograph or share it. If a third party saw the QR, rotate tokens using a controlled stop-and-reset process, then re-pair.

## Next time you open Android

The pairing settings are restored automatically from encrypted Android storage. The app fetches current engine state and broker DEMO metrics, and refreshes every 15 seconds while foregrounded. On app resume from background, it immediately attempts a fresh request. If the PC is offline, it displays disconnected/unavailable **without erasing the saved pairing** and tries again while open. It does not cache old balances.

**Important:** This is persistent pairing, NOT a permanent network socket, Android background execution, or a cloud-hosted bot. If the Windows PC sleeps, is turned off, exits the API/worker, loses Tailscale, or MT5 disconnects, the app cannot show fresh data. For true days-long uptime, the Python/MT5 engine needs an always-on Windows computer/VPS, robust process supervision, and active Tailscale on both endpoints. Tailscale on Android must be enabled; phone battery settings can suspend its network connectivity.

## Windows upgrade from the current working v1.2

**Before upgrade:** stop both old Python processes after verifying their command lines against the PIDs in `runtime/demo-bridge-pids.json`, but leave MT5 and Tailscale open.

PowerShell in `C:\Users\WingerAPP\mt5-forex-trading-bot\mt5-ai-bot`:

```powershell
git status --short
git pull --ff-only origin feature/persistent-qr-pairing-2026-11
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_demo_phone_bridge.ps1
```

No new virtualenv or MT5 install required. As this is a previous single-branch clone, the `git pull --ff-only origin <branch>` pattern is supported; **check for local tracked modifications first**.

Tailscale Serve stays private at `https://<your-Windows-device>.<your-tailnet>.ts.net` proxied to `127.0.0.1:8787`. Use Serve, not Funnel.

The existing pairing token from the old server will rotate exactly once when upgrading because old servers never stored it. After v1.3 boot, the new tokens remain stable across restarts under the same Windows user. One QR scan pairs Android. QR generated in memory; if it fails to open, first confirm `tailscale serve status`, the Windows desktop supports Tkinter, and the QR dependency installed.

## Security, data and controls

- Windows tokens: DPAPI under the WingerAPP user, in ignored runtime folder. Reinstalling Windows/changing Windows user may require re-pairing.
- Android tokens: Keystore-backed encrypted secure storage. Clearing app data or reinstalling the APK may erase the saved pairing. Never store tokens as plain preferences, screenshots or server-side logs.
- Two **distinct** random secrets: read-only token and demo signal pause/resume token. QR contains both—treat it as a secret.
- All broker trading remains **disabled** in `--dry-run --require-demo`. Phone controls only pause/resume signal calculations. The manual Windows kill switch is independent.
- No public Internet or cloud QR generator. Read-only demo figures hide if stale and never use fabricated values.
- More devices can be paired only by scanning the private QR on a trusted phone; long-term production deployment needs per-device revocation/credential lifecycle.

## Troubleshooting

- **App says Disconnected after days:** check PC power, MT5 DEMO connection, Python process, private HTTPS `tailscale serve status`, and Android Tailscale; the app will auto-retry with saved credentials when online.
- **401 unauthorized:** Windows tokens were rotated or app saved older credentials. Use Connection settings / Forget this bot and scan the new private QR.
- **Missing QR on Windows:** inspect Tailscale Serve, terminal output *without showing credentials*, Tkinter install, and `pip install -r requirements.txt`. No plaintext tokens should be printed.
- **Lost Windows profile/DPAPI:** original encrypted files cannot be decrypted under a different user; stop processes and rotate credentials securely before re-pairing.
- **Pause/resume:** remains DEMO simulation only; verify remote_paused in /v1/status after action.

Reference app branch: `feature/secure-auto-reconnect-2026-11`.
