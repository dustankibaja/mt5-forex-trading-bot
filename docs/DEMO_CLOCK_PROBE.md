# Read-only MT5 clock probe

Compile `mt5-ai-bot/scripts/EmtifizeClockProbe.mq5` with the installed
MetaEditor. Place the resulting EX5 in the active terminal's `MQL5/Scripts`
directory. Refresh Navigator and attach the script to an active chart while
Algo Trading is off. Its default run records six samples one second apart.
The probe contains no order, account-switching, or position-management calls.

Capture Python's Unix time, UTC-aware datetime, monotonic time, and the
`symbol_info_tick()` values for EURUSD, GBPUSD and USDJPY while the script runs.
Collect the `EMT_CLOCK` lines from the Experts log. Keep the raw tick fields
alongside their UTC renderings and compare exact millisecond matches for each
symbol where the sampling intervals overlap. A tick can change between the
two readers. Treat a mismatched observation as inconclusive unless it can be
bracketed in time. Keep account identifiers out of the exported evidence.

`TimeCurrent()` reflects the last server time received with a quote.
`TimeTradeServer()` is a terminal estimate. `TimeGMTOffset()` is the local
computer's GMT offset. None establishes that a particular quote is fresh or
that the broker uses a permanent UTC offset. Repeat across probe restarts and
corroborate the host's UTC against an independent clock.

The current Python gate validates both raw timestamp fields against UTC. It
rejects future, stale, missing, and inconsistent timestamps. An observed
offset is diagnostic evidence and does not grant execution permission.

- [MQL5 TimeCurrent reference](https://www.mql5.com/en/docs/dateandtime/timecurrent)
- [MQL5 TimeTradeServer reference](https://www.mql5.com/en/docs/dateandtime/timetradeserver)
- [MQL5 TimeGMTOffset reference](https://www.mql5.com/en/docs/dateandtime/timegmtoffset)
