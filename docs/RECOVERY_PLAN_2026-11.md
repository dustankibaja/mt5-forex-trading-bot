# MT5 AI Trading Bot recovery plan — November 2026

## Purpose
Recover the January 2026 MT5 Python bot and connect it to the June 2026 Flutter app
[dustankibaja/TradeX-Pro](https://github.com/dustankibaja/TradeX-Pro) (APEX Trade).

**Status: not ready for funded trading.** Existing strategy is ATR/EMA rule-based,
not a validated ML predictor. No profitable live track record has been established.
Default configuration remains `execution.dry_run: true`.

## Verified starting point
- `mt5-ai-bot/scripts/run_live.py`: MT5 live loop, ATR breakout, MT5 order adapter.
- `mt5-ai-bot/src/execution/`: risk manager, order builder, broker safeguards.
- `mt5-ai-bot/scripts/backtest.py`: local historical backtesting runner.
- `TradeX-Pro/apex_trade`: Flutter screens, but still simulated auth, signals, quotes,
  P&L and trade history. It has no verified engine-control API.
- Older sibling repo implementations (`mt-trading-bot`, MQL5 adaptive-straddle EAs)
  are alternatives; do not mix them into the engine until independently tested.

## Recovery sprint 1 — initial safety repair (this PR)
- Correct order_check success condition (0, not TRADE_RETCODE_DONE).
- Interpret symbol trade mode correctly (FULL, not DISABLED).
- Interpret broker filling-mode bitmask correctly and block unsupported modes.
- Refuse an order if the minimum lot breaches risk or tick-size math is invalid.
- Verify stop-loss risk using MT5 `order_calc_profit` before order submission.
- Remove the fallback that submitted unprotected orders after INVALID_STOPS.
- Build trade count / daily net P&L from MT5 broker history, not just in-memory state,
  and reject trades when current positions cannot be inspected.
- Evaluate only closed candles; normalize journal path before writing.
- Add regression tests and Windows-based CI.

**Still required before demo certification:** run CI and a broker-connected DRY_RUN
session; confirm each order-check and broker response; review partial fills,
position identifiers, netting versus hedging, daily boundary, reconnection behavior
and magic-number separation. These changes alone are NOT proof of trading safety.

## Recovery sprint 2 — scientific strategy certification
1. Repair historical engine assumptions: use a closed candle to generate signals,
   execute at the next achievable price with spread/slippage, and handle gaps.
2. Validate data: chronological UTC OHLC, accurate broker timezone, symbol specifics,
   no future leakage, correct spread/commission/swap and tick value per instrument.
3. Walk-forward testing across independent out-of-sample periods and market regimes.
   Include parameter stability and bootstrap/Monte Carlo drawdown estimates.
4. Report net return, expectancy, profit factor, maximum drawdown, losing streak,
   turnover and per-symbol/session performance. Include failures, not just winners.
5. Compare simple ATR breakout to other strategies on the same data. Add ML only if
   it improves out-of-sample risk-adjusted outcomes, repeatedly.
6. Keep live trading disabled if no robust positive edge survives realistic costs.

## Recovery sprint 3 — phone-to-bot architecture
Mobile app **must not** run MetaTrader locally or store broker credentials.

```text
APEX Trade (Flutter)
  - authenticated account and device
  - real balances, positions, orders and trading journal
  - notifications, pause/resume and risk settings
  - emergency STOP NEW ORDERS
           |
           | HTTPS + authenticated real-time data
           v
Secure API (FastAPI or equivalent)
  - per-user authorization and audit log
  - signed, timestamped, idempotent commands
  - explicit bot status and command acknowledgments
  - encrypted config storage and strict ownership checks
           |
           | outbound worker connection / secure command pull
           v
MT5 Python worker (Windows VPS + logged-in MT5 terminal)
  - strategy and risk engine
  - local kill switch always wins over remote commands
  - broker execution / reconcile state on reconnect
  - publishes account, positions, signals, status
```

Start with **one demo account and one operator**. Remote PAUSE blocks *new orders*;
it does not silently liquidate existing positions. Closing positions requires an
explicit separate confirmed action. The app must display stale/online state rather
than presenting hardcoded numbers as live. No public unauthenticated endpoint may
issue trade actions. Keep secrets off GitHub and off the handset.

## Recovery sprint 4 — demo forward-trading gate
- Run the same frozen strategy for several weeks in a broker demo account; collect
  broker statements, rejected requests, missed ticks, slippage and out-of-hours cases.
- Reconcile UI positions, broker positions and journal, including manual interventions.
- Test restart, network loss, VPS reboot, broker outage, stale API commands,
  daily loss trigger, minimum lots, unexpected partial fills and emergency stop.
- Require controlled drawdown and stable positive *net* expectancy before even
  considering funded use. A positive result is evidence, **not a profit guarantee**.

## Security / commercialization
- Never put MT5 account passwords or terminal access tokens into Flutter assets,
  Git commits, mobile logs or unencrypted API tables.
- Keep the mobile account token separate from the broker's execution session.
- Before managing other users' funds or providing a commercial trading service,
  obtain applicable legal/regulatory review and broker permission.

## Next concrete actions
1. Get the safety PR passing Windows CI and broker-connected DRY_RUN.
2. Eliminate backtest lookahead; produce the first clean, reproducible baseline report.
3. Introduce a read-only FastAPI account/status endpoint behind authentication.
4. Replace Flutter mock data screen by screen; then add audited controls.
5. Demo-certify end-to-end integration before live enablement.
