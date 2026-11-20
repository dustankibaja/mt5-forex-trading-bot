# E.1 beta continuation scope while certification is blocked

This is an evidence-based scope review of existing product code. It does not
approve an order workflow, claim profitability, or reclassify synthetic data.

| Capability | Existing evidence | Safe continuation boundary |
| --- | --- | --- |
| Strategy Studio / versioning | `src/product/strategy_spec.py` validates a versioned configuration/hash; `strategy_evaluator.py` evaluates completed candles only. | Continue authoring, versioning and explanation. Signals remain informational and `execution_enabled` is false. |
| Historical backtesting | `src/product/historical_backtest.py` requires dataset identity/provenance and `eligible_for_backtest`, records a manifest/hash, cost assumptions and warnings. | Continue only with identified datasets and visible assumptions. Historical simulation must not be described as a profit guarantee. |
| Signal generation / explanations | `strategy_evaluator.py` exposes completed-candle decisions, warm-up rejection, source and price basis, and explicitly excludes profitability/execution. | Continue read-only signal explanations and test coverage. Label any fixture/demo output as synthetic. |
| DEMO monitoring | `demo_readiness.py` is read-only/conservative and returns `order_execution_enabled: false`; quote certification remains fail-closed. | Continue account/market observation and blocker visibility only. Do not promote stale/cached quotes to certified data. |
| Backtest reports / export | Backtest manifests include strategy version/hash, dataset, date range, execution/cost model and warnings. | Continue report/export work if it preserves manifest and data-source labels. Do not label unqualified strategies profitable. |
| Readiness status | `product/onboarding.py` keeps `execution_allowed: false` and distinguishes pre/post-execution checks. | Continue improving clear blocker presentation, without weakening technical locks. |

## Explicitly out of scope for E.1 beta continuation

- broker execution, reservations, `order_check`, `order_send`, or automatic
  signal-to-order routing;
- presenting fixture/paper outcomes as broker fills or profit evidence;
- removing DEMO, time-certification, risk-qualification, account-binding or
  emergency-stop blockers; and
- repackaging or launching the Windows beta without a reviewed, meaningful
  application change.

The next product work may safely improve deterministic strategy authoring,
dataset provenance, backtest result readability/export, signal explanation and
readiness transparency. It must preserve the current execution boundary.
