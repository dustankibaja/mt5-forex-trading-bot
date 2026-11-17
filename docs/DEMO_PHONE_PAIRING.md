# Emtifize AI — Android + MT5 demo-only phone connection

Status: the currently installed APK supports an authenticated READ-ONLY status heartbeat. It cannot execute orders, show actual balances/trades, or remotely start the engine. Its other data is simulated and clearly labeled.

## Requirements
Windows with MetaTrader 5 desktop signed into a DEMO account; Python 3.11 (64-bit); Git; and Tailscale installed on both Windows and the Android phone, signed into the same private tailnet. Keep the PC on while testing.

## 1. Download the exact demo bridge branch
~~~powershell
git clone --single-branch --branch feature/demo-phone-pairing-2026-11 https://github.com/dustankibaja/mt5-forex-trading-bot.git
cd mt5-forex-trading-bot\mt5-ai-bot
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~
If you already cloned this repository, check out the named branch in your existing clean clone or clone into a different directory. Do not overwrite your current local changes.

## 2. Verify the DEMO MT5 account before any worker launch
Open MetaTrader 5 desktop on Windows and log in to your broker's DEMO account. No account number or broker password should be posted in chat, GitHub, or Flutter.
~~~powershell
.\.venv\Scripts\python.exe scripts\demo_preflight.py
~~~
The command must report 'MT5 connected to a DEMO account.' If not, stop and correct the terminal login. It rejects funded accounts.

## 3. Start safe, authenticated status API and dry-run worker
~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_demo_phone_bridge.ps1
~~~
This verifies the DEMO account again, generates a random pairing token, starts the local API on 127.0.0.1:8787, starts the worker with BOTH --dry-run and --require-demo, and confirms a fresh heartbeat. Treat the pairing token as a password; do not share it with anyone, including ChatGPT.

## 4. Create PRIVATE HTTPS connection on both devices
Install Tailscale on Windows and Android, log into the same tailnet and ensure both devices are connected. In Windows **Administrator PowerShell**, run:
~~~powershell
tailscale serve --bg 8787
tailscale serve status
~~~
Approve the HTTPS/Serve setup if prompted. The status command displays a real https://<your-node>.<your-tailnet>.ts.net address. Copy that exact HTTPS base URL. Do not use Funnel; it makes the endpoint public.

## 5. Pair Android app
Open Emtifize AI Demo > amber DEMO DATA ONLY banner > Trading engine. Paste the exact HTTPS base URL from Tailscale into Secure API address and the randomly generated token into Read-only pairing token. Tap Check connection.
A verified test should show RUNNING, mode dry_run, atr_breakout, EURUSD, recent heartbeat. A stale heartbeat turns OFFLINE automatically after 30 seconds. The connection is status-only and creates NO demo trades.

## 6. Diagnose connection problems
- 401 Unauthorized: incorrect read-only token.
- Cannot reach server: Windows PC asleep, wrong tailnet/URL, Tailscale off on Android, or Python API not running.
- Offline or stale: MT5 disconnected, demo account changed, Python worker stopped or heartbeat aged over 30 seconds.
- Windows logs: mt5-ai-bot/runtime/logs/.
- Local PowerShell API check in the SAME session that holds the token:
~~~powershell
Invoke-RestMethod -Uri http://127.0.0.1:8787/v1/status -Headers @{Authorization = "Bearer $env:BOT_STATUS_READ_TOKEN"}
~~~

## 7. Shutdown
Run 'tailscale serve off' in elevated PowerShell. Stop only the two Python processes previously launched, verifying their identity using Task Manager or runtime/demo-bridge-pids.json. Avoid blindly stopping old/reused PIDs. Restarting the demo bridge generates a fresh token; re-pair Android.

## Safety / profitability
No real-money trading. Even if status says RUNNING, the worker is DRY_RUN and does not send demo orders. Prior ATR/EMA backtests had negative net returns after modeled costs. More research, broker demo forward tests, and dedicated audited account-data/API modules are still needed before enabling trading control.

Official Serve reference: https://tailscale.com/docs/reference/tailscale-cli/serve
