# Emtifize AI v1.2 — minimal Android-to-MT5 DEMO control center

This supersedes the earlier status-only pairing experience. The previous
Flutter mock trading screens were removed on branch
`feature/minimal-bot-console-2026-11`.

## Exact safety boundaries

- **No order-placement endpoint exists.** No remote BUY/SELL, account login,
  deposit, broker credential, stop-loss or risk-parameter commands.
- Source worker runs with **both** `--dry-run --require-demo`.
- Each session starts **PAUSED by default**; the bot keeps reading MT5 demo
  portfolio values while paused but performs no signal evaluation.
- Android may **PAUSE** at any time with the separate control token, even
  when the worker is offline (fail-safe for its next startup).
- Android may **RESUME dry-run signal evaluation** only when:
  (a) fresh status says dry_run and demo_guarded,
  (b) trading_enabled is false,
  (c) broker account snapshot is fresh and type DEMO.
- Resume ONLY clears the phone-controlled remote pause. It cannot clear the
  separate Windows `KILL_SWITCH` and does not place demo orders.

## Security model

Local Python HTTP server binds `127.0.0.1:8787`. Access the Windows PC through
existing private Tailscale Serve HTTPS URL (NOT public Funnel).
Two separately generated 48-byte random tokens:
- **READ-ONLY pairing token** for GET `/v1/status` and GET `/v1/demo-account`.
- **DEMO control token** for POST `/v1/demo-control/pause` and
  POST `/v1/demo-control/resume`. The read-only token must not authorize POST.
Tokens should NEVER be posted in GitHub, email or ChatGPT, nor screenshotted.

## Windows upgrade from previously working branch

In `C:\Users\WingerAPP\mt5-forex-trading-bot\mt5-ai-bot`:

1. Keep MT5 desktop signed in to the **DEMO** broker account.
2. Stop the old API and bot worker processes after checking the recorded PIDs'
   command lines. This step avoids port 8787 conflicts.
3. From the existing single-branch clone, fast-forward directly to v1.2:

```powershell
git status --short
git pull --ff-only origin feature/safe-demo-control-2026-11
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_demo_phone_bridge.ps1
```

`git status --short` must show no unexpected tracked edits. The runtime/
folder is intentionally ignored; local balances and pairing data are
NEVER committed.

4. Wait for SUCCESS and READ-ONLY DEMO PORTFOLIO: Available (if broker
   history data can be read). The CLI displays two PRIVATE tokens;
   use them directly on the phone, do not share them in chat.

5. Previous Tailscale Serve hostname remains valid if `tailscale serve status`
   still points HTTPS 443 to local port 8787.

## Android v1.2 pairing

Install version 1.2.0+4 debug APK from the successful Flutter Android build.
If Android complains about incompatible debug signing, uninstall previous
Emtifize AI Demo first, then install v1.2 (clears previous local inputs).

On the ONLY screen:
- HTTPS address: the SAME private `.ts.net` hostname as before.
- Read token: freshly generated from updated bridge.
- Control token: the DIFFERENT second token (optional for monitoring only).
- Tap Connect securely.
- View real worker state, demo balance/equity/P&L and expanded broker records.
- Pause demo simulation to stop signal evaluation. Resume requires explicit
  on-phone confirmation and guarded broker checks.

The fields collapse after pairing and can be reopened from the sliders icon
at the top. Secrets exist in the active screen's memory only (not saved).

## Privacy and limitations

The account panel is live **DEMO** broker data; no account number or broker
password is exposed. The app continues to rely on a Windows PC that remains
on and connected to MT5 and Tailscale. A confirmed phone-to-engine connection
is NOT evidence of profitable forex trading. Independent strategy validation
is still incomplete.

When the worker exits or loses broker access, status is marked offline and
account figures are hidden. If no positions/deals exist, the lists are
correctly empty, not automatically populated with fabricated trades.
