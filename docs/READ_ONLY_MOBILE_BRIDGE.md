# APEX Trade ↔ MT5 AI Bot: v1 read-only status bridge

## Implemented
- Python MT5 worker writes a sanitized heartbeat atomically to
  `mt5-ai-bot/runtime/engine_status.json` (or `BOT_STATUS_PATH`).
- The worker writes `running`, `paused` (kill switch), and `offline`.
- API `GET /v1/status` reads the heartbeat, marks it offline if older than
  30 seconds, and never connects to MetaTrader itself.
- API `POST`/`PUT`/`DELETE`/`PATCH` return HTTP 405.
- Only data returned: schema version, state, configuration mode,
  whether live trading *would be configured*, strategy name, limited
  symbols, timestamp and stale flag. **No account number, balance,
  credentials, P&L, trades or personal data.**
- Token: `BOT_STATUS_READ_TOKEN` (minimum 32 characters) required for every GET;
  provided by the owner at phone pairing and kept only in the Flutter
  app's process memory in this proof of concept.

## Local demo setup (Windows)
From `mt5-ai-bot/`:

```powershell
$env:BOT_STATUS_READ_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(48))"
python scripts/serve_status.py --port 8787
```

In a second terminal with an installed and logged-in MT5 demo terminal:

```powershell
python scripts/run_live.py --dry-run
```

This second command **only** operates in dry-run; do not disable
`dry_run` in the current unprofitable research state.
The mobile status endpoint is reachable from the same computer only at
`http://127.0.0.1:8787/v1/status` unless a PRIVATE VPN or TLS
reverse proxy forwards it securely. Never expose port 8787 directly.

## Phone pairing / production requirements
The current Flutter integration takes a manually entered HTTPS base URL
and a read-only token. It does not ship any tokens or broker credentials.
For an actual phone, set up trusted HTTPS with proper TLS validation,
access limits and a private or scoped endpoint. Loopback URLs are for
local emulator tests only. The simple shared token is a single-operator
bridge, **not** a multi-user authentication system. Use OAuth/OIDC with
short-lived tokens, device binding, refresh and revocation before
shipping a commercial app.

Do not represent app's old hardcoded balances, quotes, history, signals
or analytics as real account data. They remain demo fixtures and need
separate authenticated APIs and reliable broker reconciliation.

## Broker deployment
- Run Python worker in a Windows host with MT5 terminal and broker demo account.
- Keep MT5 access isolated from phone and TLS front end.
- Publish only status via locally bound API and encrypted authenticated transport.
- API cannot start/stop a bot, place or cancel trades, change lots or close positions.
- Never store read-only API token inside git/Flutter assets.
- No enabled live-trading mode until independent strategy and demo certification.
