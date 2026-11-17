# Sprint 11 research protocol

Correction: Compression Release returned +11.90% in 2022–2024 development and +7.00% in 2025 validation (49 trades, PF 1.515, maximum marked drawdown 3.10%, descriptive expectancy interval includes zero). The 2026 historical holdout stays sealed.

Screen exactly three fixed EURUSD hypotheses. Use the hash-pinned 2022–2025 EV Trading Labs annual H1 bid/ask files (Dukascopy-derived); 2025 is previously accessed and exploratory here. Score calendar years separately in chronological order with earlier candles supplying warm-up. No fitting or parameter search. Require the next available candle to be exactly one hour later to avoid gap entries. Indicators use component-wise averages of bid and ask OHLC.

| Hypothesis | Rationale and entry on a completed candle | Expected failure |
|---|---|---|
| Trend resumption | Persistent order flow: 07–16 UTC, close above EMA50 above EMA200, previous close at/below EMA20 and current close above EMA20; mirror for shorts. Require ATR14 above its preceding 60-bar median. | Late entries and whipsaw after news. |
| London opening momentum | European participation may extend moves from the early session: only the 08 UTC candle, close outside the 05–07 UTC three-hour range with matching candle direction and absolute body at least 0.5 ATR14. | Seasonal DST misalignment, false breaks and thin prior range. |
| Quiet range reversion | Liquidity provision may reverse excursions in quiet, flat markets: 10–16 UTC, ATR14 at/below its prior 60-bar median and EMA50 within 0.5 ATR14 of EMA200. Previous close below previous EMA20 by at least previous ATR14 and rising current close; mirror for shorts. | Trend transitions can overwhelm reversion. |

Common execution: next hourly ask/bid open with observed spread no greater than 2 pips; stop 1.5 signal ATR14, target 2R, stop first on ambiguous candles, max hold 48 bars, 0.5% equity risk rounded down to 0.01 lot, one position, at most three entries daily, 2% realized daily loss brake. Baseline 0.2 pip adverse slippage per side and $7/lot round trip. Stress: 0.6 pip and $10/lot plus $10/lot per crossed 22 UTC boundary (flat adverse carry proxy, not a broker swap schedule).

Report annual return, trade count, PF, drawdown, expectancy, adverse-cost response and profit concentration. Use fixed-seed monthly block bootstrap over validation trade returns in R (descriptive only; one year and sparse trades limit power). Development screen: positive pooled net P&L in both cost scenarios, positive base return in at least three of four years, at least 50 exploratory 2025 trades and max annual marked drawdown ≤15%. Regardless of result no candidate qualifies without a separately frozen, unseen cohort; three hypotheses create selection bias. No broker orders or 2026 historical reads.
