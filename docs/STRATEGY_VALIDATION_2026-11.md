# Milestone 2 — Historical EURUSD strategy validation (2026-11-04)

## Decision
**No strategy passed the profitability screen. Live-trading approval: NO.**

This compares fixed hypotheses on an H1 EURUSD OHLC research dataset.
It is not broker certification, a profitable live track record, or evidence
that an automated system beats most discretionary traders.

## Reproducibility
- Engine: `mt5-ai-bot/src/research/backtest.py`; signals: `src/research/signals.py`
- Run: `cd mt5-ai-bot && python scripts/validate_strategies.py --out validation_report`
- GitHub Actions: `MT5 historical strategy validation`, report attached to PR #6
- Public data: `ejtraderLabs/historical-data`, EURUSDh1.csv at commit
  `fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd`
- SHA256 (original CSV): `1b29ca23bdc7b2645ae48a0ccb06108263b69e586bdc7d0ba40e66d1e5966eb9`
- 57,600 bars from 2012-11-16 00:00 UTC to 2022-03-04 23:00 UTC.
  Original vendor raw prices divided by 100,000 to quote EURUSD.
- Data timestamp timezone is ASSUMED UTC, not independently certified.
  No redistribution of source data is included in this repository.

## Prespecified strategy candidates
1. Original ATR(14)-filtered 20-bar breakout, EMA(50) slope trend filter
2. 20-bar Donchian breakout
3. EMA(20/50) crossover
4. RSI(14) crossing below 30 / above 70, countertrend

All use 1.5 ATR SL, 2R TP and maximum 48-bar hold, without parameter sweeps.
Cost model: spread 1.2 pips; adverse slippage 0.2 pip/side;
$7 per 1.00 lot round trip; 0.5% balance risk; 0.01-lot step;
at most 3 entries per UTC day. Signals use previous closed candle;
orders enter next bar open. Ambiguous same-bar fills choose stop first;
stop gaps fill no better than the gap open.

## Audited reproducible first-pass output (GitHub Actions)
| Period | ATR breakout | Donchian | EMA crossover | RSI mean reversion |
|---|---:|---:|---:|---:|
| Development 2012–2017 | -50.88% | -56.24% | -25.85% | -43.39% |
| Validation 2018–2019 | -17.64% | -21.86% | -12.89% | -18.26% |
| Historical test 2020–Mar 2022 | -10.96% | -12.88% | -4.49% | -23.13% |

The EMA crossover lost the least in validation and the historical test:
235 trades, win rate 33.6%, profit factor 0.94, marked max drawdown
12.2% in historical test. That is a **failure**, not a candidate to trade.

**Important:** The 2020–2022 test results have been viewed and discussed.
They are now CONSUMED as historical research evidence. They must not
be called a sealed, unseen holdout during further tuning. A new future
unseen dataset is required to validate any new hypotheses.

## Remaining biases and controls
- Historical mid OHLC cannot resolve tick order within a candle.
- Fixed spread, slippage and commission exclude actual broker variation.
- Swap, margin requirements, leverage, stop-loss rejection/requotes,
  position netting, account restrictions, liquidity and execution latency
  are not included. Quoted prices differ by broker.
- Data quality and clock origin require independent cross-provider checks.
- No independent audit of human-trader outcomes exists; cannot quantify
  superiority to "most traders".
- The older `src/backtest/engine.py` has separate lookahead and cost-model
  problems and must NOT be used to claim superior results.

## Next scientific experiment (pre-register before running)
- Secure 2022–2026 broker-style tick/bid/ask data from at least two providers,
  including volatile/quiet regimes. Keep a final segment uninspected.
- Design plausible market-mechanism hypotheses: volatility-regime breakout,
  trend continuation after pullbacks, and time-of-day filtering.
- Limit candidate count, fix all parameters in development, pick on
  validation only, and run one final untouched test.
- Evaluate cost sensitivity, bootstrap confidence intervals, monthly
  stability, adverse fill stress, max exposure, and a simple risk-matched
  benchmark. Publish all negative results.
- If nothing beats 0 net expectancy consistently after costs, stop.
  Improving bot automation cannot manufacture a trading edge.
- Only then consider demo forward trading with tracked statements.
