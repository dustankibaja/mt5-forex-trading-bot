# Emtifize AI v1.3 — scan once, reconnect later

This is a DEMO-only MT5 monitoring and signal-simulation controller. The
Flutter APK **does not place demo or real-money broker orders**.

## Why this upgrade exists

Old Windows startup generated different bearer credentials on EVERY restart,
and the app forgot them when it closed. A returning user got HTTP 401 and
had to copy two long tokens and the HTTPS hostname again.

v1.3 resolves both sides:

- **Windows:** the two separate credentials are generated once and encrypted
  to the `WingerAPP` Windows login using DPAPI CurrentUser. They are stored as
  *encrypted ciphertext* in `runtime/pairing_keys.dpapi`, ignored by Git.
  Restarting the Python processes reuses them. No plaintext key file.
- **Android:** the app scans one QR and stores its host/credentials using
  Android Keystore-backed encrypted storage. On next launch it rehydrates
  credentials and connects immediately. It also refreshes upon foreground
  resume and every 15 seconds while the screen is open.
- **No background phone dependency:** the Python bot runs on Windows whether
  or not the phone app is running. Android does not need a permanent socket
  or continuous background execution.

## Upgrade your existing Windows installation

1. On Windows keep MetaTrader 5 desktop logged into your broker **DEMO**.
2. Stop the two old Python bridge processes from
   `mt5-ai-bot/runtime/demo-bridge-pids.json` after verifying their command
   lines match `serve_status.py` and `run_live.py`. Never indiscriminately
   kill every python.exe process.
3. In `C:\Users\WingerAPP\mt5-forex-trading-bot\mt5-ai-bot`,
   run:

```powershell
git status --short
git pull --ff-only origin feature/dpapi-persistent-pairing-2026-11
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_demo_phone_bridge.ps1
```

This single-branch clone can fast-forward from the current DEMO controls
branch to the new nested branch. Keep any unexpected local changes safe
before the `git pull`. The `.venv` directory is unaffected.

4. Leave the existing Tailscale Serve HTTPS port-8787 proxy configured,
   with Tailscale logged in on PC and Android.
5. After the successful DEMO check and fresh account heartbeat, the bridge
   opens a QR window on your Windows desktop (GUI requires local desktop,
   not a headless/noninteractive VPS).

No bearer tokens are printed in the normal PowerShell startup output.

## One-scan phone pairing

1. Install Emtifize AI `1.3.0+5` on Android.
2. Enable Android Tailscale; sign in to the same private tailnet.
3. Tap **Scan QR from Windows** inside Emtifize AI.
4. Point the phone at the **Emtifize AI Private pairing** QR window on your
   Windows desktop.
5. Confirm the shown **.ts.net** hostname belongs to your Windows PC.
6. The app tests the API, then saves credentials using encrypted Android
   storage. Your normal DEMO dashboard opens.
7. Close the Android app completely and reopen it: it reconnects without
   asking for URL/tokens. This also works days later if the Windows bot,
   MT5 and Tailscale are still running.

To reopen a QR **without restarting** a working Windows bridge:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\show_pairing.ps1
```

If Windows GUI scanning isn't available, use manual entry. To reveal
the private credentials **only on your own Windows screen**, explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\show_pairing.ps1 -NoQr -ShowTokens
```

Do not paste those values or QR screenshots into email, social media,
GitHub, or ChatGPT.

## Revoke a lost phone / rotate credentials

Existing tokens grant DEMO read access and pause/resume simulation on the
private tailnet. If a device is lost, compromised, or an untrusted person
saw its QR, stop the old API/worker processes, then restart with
`-RotateKeys`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_demo_phone_bridge.ps1 -RotateKeys
```

This deliberately invalidates all previously paired phones; scan new
QR(s). On the phone, use **Forget saved pairing** to erase local secrets.

## Realistic connection lifetime

- App closed or phone screen locked for days: credentials survive and the
  Android app reconnects on next launch (provided backend remains online).
- Windows bridge restart with the same Windows login: stored DPAPI tokens
  survive; *no re-pair* needed.
- Windows reboots or goes to sleep: it cannot answer requests while off.
  Windows still needs MT5 and the bridge restarted after reboot. **This
  change does not configure Windows autostart / unattended MT5 login.**
- Device reinstall / changing debug signing certificate may erase Android
  local encrypted secrets; re-scan QR if prompted.
- Android Tailscale VPN must be connected. If VPN or PC is offline, the
  app shows disconnected and hides broker balances, then retries when
  foregrounded. No fabricated account figures.

## Security notes

QR embeds BOTH high-entropy tokens: treat the QR like a password, do not
record, screenshot, publish or share it; display it in a private room.
Android QR scanner decodes locally; never uploads images or values.
Manual input uses the same private HTTPS host restriction; public HTTP and
unrelated sites are rejected.

DPAPI encryption is bound to the Windows *user profile*, so logging in
with another Windows account cannot decrypt the original stored keys.
Switching users is not equivalent to restarting the same user. Backups
and storage recovery of `pairing_keys.dpapi` require care.

This is still a single-user prototype; production should use per-device
revocable identities and stronger server-side device management.
