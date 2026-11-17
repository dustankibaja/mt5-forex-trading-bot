# Emtifize AI — quant research and execution certification report

**Date:** 2026-11-05 (Tanzania)  
**Scope:** EURUSD H1, Windows MetaTrader 5 DEMO, Flutter phone control.
**Current capital deployment decision:** REAL MONEY = NO; unattended broker orders = NO.

## Executive conclusion

Android-to-Windows MT5 DEMO monitoring works based on observed user-device
verification. GitHub CI verifies new Python and Flutter source, not a physical
broker execution. No strategy currently meets a precommitted evidence
threshold for profitable long-run automated trading. Never imply that
a validated historical simulation guarantees future net profitability.

The single most promising FIXED pre-registered hypothesis is **compression_release**,
but its 2025 validation contains **only 49 trades**, below the minimum gate of
50, and no fresh 2026 holdout or genuine MT5 DEMO forward-trade series exists.
Therefore it is an **experimental candidate for further research only**,
not an approved automated capital-deployment strategy.

## Data and hypothesis study 1 (older OHLC)

- Frozen source: ejtraderLabs EURUSD H1, SHA256
  1b29ca23bdc7b2645ae48a0ccb06108263b69e586bdc7d0ba40e66d1e5966eb9
- 57,600 H1 records from 2012-11 to 2022-03.
- Out-of-sample simulated EURUSD 2020-2022 after 1.2 pip modeled spread,
  $7/lot roundtrip commission and 0.2 pip adverse slippage **per side**:

| Strategy | Test trades | Net return | Profit factor |
|---|---:|---:|---:|
| ATR breakout | 684 | -10.96% | 0.95 |
| Donchian breakout | 702 | -12.88% | 0.95 |
| EMA crossover | 235 | -4.49% | 0.94 |
| RSI reversal | 354 | -23.13% | 0.78 |

ALL FAIL. For ATR, zero-cost +35.22% became -10.96% at modeled base
trading costs, illustrating why spread/slippage matter.

## Data and hypothesis study 2 (new verified H1 BID/ASK)

- EV Trading Labs: https://evtradelabs.com/data
- Files obtained via published public catalog API, SHA256 per 2022/23/24/25
  annual source in the CI report artifact manifest.
- 24,935 EURUSD H1 bid-and-ask candles, 2022-2025.
- Data distributor is independent, but price series originate from
  Dukascopy, not independently from the MetaQuotes-DEMO user's own broker.
- Fixed pre-registered, zero-retuning hypotheses:
  session_breakout, trend_pullback, compression_release.
- Conservative next-bar entry on executable ask/bid, 0.5% equity nominal
  risk, 1.5 ATR stop, 2R target, stop-first ambiguity, 48-bar maximum hold,
  max 3 new trades/day, $7/lot roundtrip commission, +0.2 pip adverse
  slippage on both entry and exit, historical spread allowed up to 2 pips.
- An intrabar hindsight defect was fixed: an existing trade that exits
  **inside** bar i can never trigger a retroactive new trade at that bar's
  opening quote. Synthetic regression test added.

| Hypothesis | 2022-24 dev return | Dev PF | 2025 validation trades | 2025 net return | 2025 PF | 2025 max DD |
|---|---:|---:|---:|---:|---:|---:|
| session_breakout | -27.68% | 0.831 | 158 | -12.29% | 0.762 | 13.76% |
| trend_pullback | -15.71% | 0.845 | 104 | -7.00% | 0.794 | 8.79% |
| compression_release | +11.90% | 1.188 | 49 | +7.00% | 1.515 | 3.10% |

For compression_release in 2025, a more adverse cost scenario (0.5 pip
slippage each side and $10/lot roundtrip commission) still simulated +5.86%,
PF 1.431, DD 3.17%. This is NOT live or broker-certified performance;
swap/funding, order depth, live fill reliability and margin were omitted.

**Pre-registered gate:** >=50 validation trades, net >0, PF >1.0 and DD <=15%.
compression_release has 49, so the published gate is **NOT PASSED**.
Do not move the threshold to 49 because results were already seen.
The 2026 sealed holdout remains uninspected, exactly as the protocol specifies.

No 2025-tested strategy is approved for funded or unattended strategy orders.

## Execution engineering source state (never mistaken for broker fills)

- Private Android v1.3 scan-once pairing, encrypted Android Keystore storage,
  Tailscale Serve over HTTPS; actual connected phone verified by user.
- Windows read-only MT5-DEMO balance/equity/position/closing-deal feed.
- DEMO signal PAUSE/RESUME uses separate token, never places orders.
- The unattended ATR worker has been hard-locked to
  --dry-run --require-demo AND execution.dry_run=true. A config change
  cannot turn it into funded broker execution.
- Source-only DEMO smoke firewall developed in draft PR #18:
  pinned broker account identity, checks immediately before send;
  max 0.25% hypothetical equity risk (broker minimum lot with buffered
  stop risk + fee reserve); spread and stale quote checks; no other
  EURUSD exposure, server-side SL/TP on entry, kill-switch checks,
  durable SQLite one-intent-per-day ledger, no blind retry on uncertain
  result, and separate locally armed CLI. Synthetic CI tests passed.
- No production broker-side demo order has been placed or verified from
  this chat. No Windows desktop/MT5 terminal control is available here.

## Release gate scoreboard

| Gate | Evidence | Decision |
|---|---|---|
| Android → private Windows MT5 status | User-shared real screenshot | PASS (connectivity) |
| Read-only broker account metrics | Windows API and source tests | PASS (code), user account values not independently audited |
| DEMO smoke execution safety | Synthetic GitHub tests | SOURCE PASS; actual broker smoke NOT RUN |
| Historical strategy edge | 7 frozen strategies, cost-aware research | FAIL / unqualified |
| Recent independent holdout | 2026 sealed | NOT RUN |
| Months-long forward DEMO order statistics | None | NOT RUN |
| Funded execution risk/regulatory audit | None | NOT RUN |
| Real-money approval | All gates required | **NO** |

## Proposed conditional next work

- Keep the positive but undersampled compression_release hypothesis
  under observation; do not retroactively relax sample or cost gates.
- Independently replay through a genuinely different broker quote feed,
  test 2026 holdout **only under frozen preregistration criteria**, and
  inspect actual broker spreads, swaps and quote/session-time alignment.
- Verify the dedicated DEMO-only one-shot order smoke test on an actual
  Windows MT5 terminal after explicit local broker approval, then
  reconcile actual deals, SL/TP, fees and outages.
- Only after a strategy passes evidence gates, run it frozen on genuine
  DEMO for months (and a statistically sufficient trade count) with
  drawdown, PF and net expected value reporting.
- Funded broker launch requires independent technical/security review,
  user capital-risk agreement, and jurisdictional/broker legal review;
  there is never a guaranteed profitable outcome.

## Reference build and research

- Phone persistence: https://github.com/dustankibaja/TradeX-Pro/pull/5
- Windows persistent bridge: https://github.com/dustankibaja/mt5-forex-trading-bot/pull/14
- Broker-readiness code: https://github.com/dustankibaja/mt5-forex-trading-bot/pull/15
- Demo order firewall: https://github.com/dustankibaja/mt5-forex-trading-bot/pull/18
- Independent research source + report: https://github.com/dustankibaja/mt5-forex-trading-bot/pull/17
- Verified public annual BID/ASK CI: https://github.com/dustankibaja/mt5-forex-trading-bot/actions/runs/42022621133

**Do not state or imply this report is a guarantee, investor advisory,
production deployment confirmation or a live-broker trading track record.**
