# Emtifize AI v2 — real MT5 DEMO account dashboard (read-only)

The installed v1 phone status pairing already works via Tailscale Serve. This upgrade adds DEMO broker-reported financial data to the **Trading engine** screen, not the existing sample home/dashboard. NO trading action is available.

## Where the data come from

- The MT5 Windows Python worker is the only process that contacts the MT5 terminal.
- Only after a **fresh DEMO account check** and --dry-run --require-demo will it write an allowlisted atomic JSON snapshot to runtime/demo_account.json.
- The localhost-only authenticated API adds GET /v1/demo-account, guarded by a fresh dry_run engine heartbeat. A current, non-demo, disconnected, unsupported, or stale snapshot hides all money.
- The phone connects via the existing HTTPS Tailscale Serve host and the SAME read-only pairing token used for /v1/status.

Broker fields: currency, balance, equity, free margin, floating profit, up to 20 current open positions, up to 20 most recent closing-deal records in the last 7 days. Opening deals, deposits, commissions-only cash movements and cash transfers do not appear as closing trades; net closing deal P&L includes profit, commission, swap and fee.

**No** account number, broker username, broker server, password, ticket IDs, magic values or comments are sent. No order placement, start/stop remote controls, or trade modifications.

## Windows upgrade

From existing C:\Users\WingerAPP\mt5-forex-trading-bot\mt5-ai-bot:

~~~powershell
git fetch origin feature/read-only-demo-account-2026-11
git switch --track origin/feature/read-only-demo-account-2026-11
~~~

If you have local uncommitted edits or the branch already exists, avoid overwriting: first run git status. If git switch --track errors because branch exists, use git switch feature/read-only-demo-account-2026-11 then git pull --ff-only origin feature/read-only-demo-account-2026-11.

Stop the existing bridge's two Python processes safely (validate PID + CommandLine):

~~~powershell
$jobs = Get-Content .\runtime\demo-bridge-pids.json | ConvertFrom-Json
foreach ($entry in $jobs) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)"
    if ($proc -and $proc.CommandLine -match '(serve_status|run_live)\.py') {
        Stop-Process -Id $entry.pid -Force
    }
}
~~~

Keep MT5 open and on a broker-issued DEMO login. Start updated bridge:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_demo_phone_bridge.ps1
~~~

It should show SUCCESS with `dry_run` and `READ-ONLY DEMO PORTFOLIO: Available`. It rotates the token—keep the new token PRIVATE and enter it into the phone only. If history API is unavailable, the portfolio remains unavailable instead of showing fabricated values. Logs: runtime/logs and logs/bot.log.

The existing Tailscale Serve can remain on: HTTPS private URL -> 127.0.0.1:8787. Do NOT use Funnel or open firewall port 8787 publicly.

## Android upgrade

Install the v2 debug APK from the new TradeX-Pro build for branch feature/real-demo-dashboard-2026-11. Because GitHub Actions debug signing keys may differ between runs, Android might reject the update; uninstall the prior Emtifize AI Demo app before installing v2 if signing conflicts. Pairing input is in memory only, so re-enter your HTTPS URL and freshly generated token.

Open Trading engine, enter HTTPS Serve base URL and private token, tap Check connection. If RUNNING dry_run, a card entitled Real MT5 demo account will display available fields. It refreshes every 15 seconds. If engine unavailable, balances disappear and explain why; no fallback to mocked balances.

## Security and strategy warnings

- This is **only a demo account monitoring integration**; it does not prove strategy profitability and does not execute any orders.
- The worker's ATR breakout failed its earlier historical net-performance validation. Keep `--dry-run` and `--require-demo` in place.
- This uses one long-lived private token for a single operator on a private Tailscale network, not production-grade multiuser auth.
- Private broker data now flow into Tailscale between YOUR devices. Protect the account, both devices and token; the API is read-only but still reveals financial details.
- Broker API may return no recent closing deals; that's valid and not a data-error. `dry_run` means the bot won't create its own demo deals.
