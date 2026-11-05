# Emtifize AI — DEMO-to-LIVE release gates (2026-11-05)

## Non-negotiable current status

- Android + Tailscale + Python + MT5 broker DEMO readback are integrated.
- Current Windows worker is strictly `--dry-run --require-demo`: **no broker orders**.
- The phone can only PAUSE/RESUME signal simulation. It cannot send BUY/SELL requests.
- Research comparison of EURUSD H1 ATR breakout, Donchian, EMA crossover, and
  RSI reversion found **negative net 2020–2022 holdout returns** after modeled
  trading costs: -10.96%, -12.88%, -4.49%, -23.13%. No profitable edge certified.
- Pre-registered independent bid/ask experiment has NOT produced an approved
  result (provider HTTP 503 / cancelled CI runs). 2020–2022 test data are no
  longer unseen to strategy developers. Never optimize against that holdout.

## Stage 0 — mechanical audit: NOW (no orders)

Run the new *read-only* preflight in a Windows MT5 DEMO terminal:

```powershell
.\.venv\Scripts\python.exe scripts\check_demo_order_readiness.py
```

This checks DEMO account and Algo Trading permission; valid EURUSD broker
contract minimum lots, tick freshness, spread, simple 20-pip hypothetical stop
risk at broker minimum lot, and free margin. It uses broker calculation APIs
but NEVER `order_check` or `order_send` and cannot place a trade.

**A readiness PASS only says the broker mechanics are worth examining. It does
not authorize orders or mean the trading strategy is profitable.**

## Stage 1 — safely implement DEMO order execution (not enabled yet)

Requirements, all verified in synthetic tests and source audit:
- A separate **DEMO_EXECUTION** process/mode, never toggled by the phone's
  pause/resume signal-simulation control or by changing `config.yaml` alone.
- Explicit local opt-in from Windows operator: a new CLI mode plus
  second local authorization after broker/account verification. Automatic
  LIVE execution impossible in demo branch.
- At EVERY order_send boundary, verify the connected terminal and account
  are DEMO (fail closed on None, disconnect, switch, timeouts).
- Pin one DEMO account identity locally in a secret-safe fingerprint to catch
  same-type demo account switches, without exposing the account number in
  Flutter, logs, GitHub or QR.
- Dedicated order executor with explicit EURUSD symbol whitelist,
  DEMO only; one order per closed candle; durable idempotency/intent ledger
  surviving restarts; no blind retry after uncertain server response.
- One open bot position per symbol, exact magic number tagging; never modify
  unrelated manual positions or orders.
- Broker-valid size using `order_calc_profit`, `order_calc_margin`,
  contract minimum/step and stop-distance checks; protective broker-side
  SL/TP included AT OPEN. Reject any missing stop or unexpected server response.
- Independently configurable daily trade limit (max 1–2 for first smoke),
  max 0.25% equity risk per trade initially, max 1% daily equity loss,
  max 5% peak-to-trough equity drawdown; never increase lot to meet broker
  minimum if that breaks the risk budget. Hard and manual kill switches
  fail closed. No martingale, averaging down, grid, or adding to losers.
- Log every **decision, signal, request, rejection, accepted fill, actual
  spread/slippage, commissions, swaps, financing, margin, exit, P&L**,
  timestamps in UTC, and reconcile from MT5 broker history on restart.
- Backfill/replay after downtime must NOT trigger stale trades.
- Automated chaos tests: disconnected MT5, funded account, account switch,
  duplicate bar, partial fills, unknown order response, network outage,
  market closed, stale quotes, spread widening, missing SL/TP, restart,
  and manual kill-switch during a trade.

Actual order sending MUST NOT be exposed through public, Tailscale or phone
API endpoints until independently reviewed, and LIVE remains disabled.

## Stage 2 — broker DEMO smoke test

Only after Stage 1 source tests, two-person/code review where possible, and
explicit local human approval:
1. Run a single extremely small EURUSD **DEMO** trade, only if risk
   checks permit broker min lot.
2. Verify order is recorded at broker, server-side SL/TP active, stop or
   manual close functions, and complete journal / reconciliation.
3. Test disconnection, restart and kill-switch *without exposing funds*.
4. Compare expected vs actual fills and broker commission.

If the broker rejects the minimum lot under risk limits, **skip the trade**;
do not waive the risk budget. This stage validates execution mechanics only,
not the strategy's positive expectancy.

## Stage 3 — research and fresh-data profitable edge gate

- Finish verified independent 2022–2025 historical bid/ask dataset; retain
  separate untouched 2026+ holdout. Provider error is a failed data job, not
  a positive trading result.
- Freeze a small preregistered set of economic hypotheses and transaction
  cost/volume assumptions before test. Account for spread by session,
  commissions, slippage, swaps/overnight financing, DST, gaps and broker
  execution minimums. Match the exact actual production code strategy.
- Walk-forward evaluation and independent broker/tick-data replay, compare
  risk-matched buy-and-hold/no-trade/simple baselines; use an actual holdout
  ONCE after model selection. Correct for multiple strategy trials.
- Promotion targets (initial, conservative **team decisions**, not laws):
  net OOS expectancy >0 with uncertainty interval lower bound above 0,
  stressed-cost profit factor >=1.15, no material single-month
  dependence, max drawdown <=10%, sufficient trades (usually >=200 or
  a justified power analysis), and stability across regimes.
- Report failure honestly. If no robust edge exists, remain DEMO only.

## Stage 4 — untouched real-time DEMO forward performance gate

- After Stage 3 yields approved strategy, run that exact frozen production
  version on genuine broker DEMO fills, ideally 3–6 months **and** enough
  trades to assess statistical power; a sparse H1 strategy may need longer.
- Mandatory scoreboard: exact net after costs, average R/trade and
  interval, total trades, profit factor, drawdown, slippage, exposure,
  missed/duplicate fills, broker outages, win/loss distribution and
  per-period returns; no manual excluding losing trades.
- Halt/research again if confidence interval includes negative expectancy,
  risk limits trip or actual fills are systematically worse than simulation.
- No strategy edits while assessing holdout; edits restart the evaluation.

## Stage 5 — guarded real-money release, ONLY if all prior gates pass

- Independent security/code audit, broker regulatory and local legal checks,
  cost/funding review and explicit account-owner consent.
- New separately signed/deployed LIVE-only process, secret isolation,
  account allowlist, two-person/manual arming, impossible to toggle from
  DEMO phone app or DPAPI token. End-to-end rollback, alert and reconcile.
- Start with only capital fully affordable to lose, strict lower limits
  (suggest <=0.1% equity risk/trade, <=0.5% daily loss initially),
  no auto-scaling; canary period and manual approval to increase size.
- Keep independent loss caps and human override. Profit is NEVER certain,
  including after successful backtests and profitable demo runs.

## Ops / uptime

An always-on Windows VPS can reduce local laptop sleep/downtime **after**
security hardening. It does NOT improve strategy expectancy. Tailscale
private access + monitor/watchdog + broker reconciliation + durable logs are
needed for reliable operation. Automated start requires its own account
identity checks and must default to PAUSED.
