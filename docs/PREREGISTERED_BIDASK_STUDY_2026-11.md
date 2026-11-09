# Stage 3 preregistration — EURUSD bid/ask, November 2026

**Recorded before downloading or inspecting the new study period.**

## Scientific question
Can any simple, explainable EURUSD H1 strategy retain positive net expectancy after
actual historical bid/ask spread and adverse slippage, without fitting parameters
to the final 2026 test? This is **not** a claim of superiority to human traders.

## Historical data and partition
Source: Dukascopy historical monthly hourly BID and ASK candles, public feed.
Expected 2022-04-01 to 2026-10-01 UTC. Do not include partial October 2026.
- Discovery/development: April 2022 to end of December 2024
- Validation: January through December 2025
- Unseen test: January through September 2026, **access exactly once after code freeze**
GitHub CI must log source URLs, coverage, file hashes, missing periods, and
the complete assumptions. Market-timezone reference: UTC.

If the source cannot be fetched or fails quality checks, report BLOCKED; do not
backfill with synthetic prices, shift period boundaries, or silently skip missing months.

## Three prespecified hypotheses, hourly bars
All use strictly completed candle i, and enter at next bar's actual bid/ask
opening quote. No parameter search or reuse of 2026 outcomes to change rules.

1. **Session-volatility trend breakout**: new 20-bar close breakout in EMA50 slope
   direction; ATR14 above its trailing 60-bar *median*; signal hour UTC 07–17;
   skip entry if current bid/ask spread > 2.0 pips.
2. **Trend pullback**: EMA20 > EMA50 > EMA200 (long) or reverse (short);
   yesterday's *hourly* prior close at/below EMA20, current close recrosses
   EMA20; RSI14 between 45 and 65 long or 35 and 55 short; UTC 07–17.
3. **Compression-release continuation**: preceding 12-bar high-low range
   < 2.5x prior ATR14 (prior strictly closed), current close breaks
   preceding 12-bar extreme, EMA50 vs EMA200 agrees with direction;
   UTC 07–17.

All three: SL distance 1.5 ATR14 (derived from mid candles), TP 2R,
0.5% balance risk per trade with 0.01 lot step, maximum 3 entries per UTC
day, maximum one open position, 48-H1-bar time exit. Reject entries with
historical spread > 2.0 pips or invalid/negative spread. Commission $7
per standard EURUSD lot, round trip; adverse slippage 0.2 pip each side.
For stop/TP ambiguity, stop first. For gaps, adverse gap price. Liquidate
open positions at partition end and report separately.

## Acceptance protocol
- Positive net return and profit factor > 1 on 2025 validation is a prerequisite;
  only candidates meeting it qualify for 2026 once. Still report failed ones
  for transparency but **do not select based on 2026 results**.
- Then require 2026 net positive expectancy, PF > 1, no catastrophic drawdown,
  enough trades to interpret, and stress-cost consistency; only then a broker
  demo trial. No live deployment merely from this result.
- Run total-period coverage, spread distribution, by-year regime stability,
  absence of future data leakage, and transaction-cost sensitivity.
- Avoid automatic strategy-selection to optimize against unseen data.

## Data/model limitations
Hourly side candles do not reconstruct intrabar event ordering, market depth,
partial fills, swaps, overnight financing, weekend events, liquidity or
margin. Long-hours spread is time varying; fill uncertainty persists. Historical
Dukascopy quotes differ from any chosen MT5 broker, even if strategy passes.
No result guarantees profitability or establishes "better than most traders".
