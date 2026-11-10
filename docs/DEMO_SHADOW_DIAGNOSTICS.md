# Read-only DEMO shadow diagnostics

From `mt5-ai-bot` with the project environment active, run one observation:

```powershell
python scripts/run_shadow_diagnostics.py --terminal "C:/Program Files/MetaTrader 5/terminal64.exe" --journal runtime/shadow.sqlite3
```

Add `--watch` to poll every 15 seconds. Ctrl+C detaches the Python process from MT5. A failed or changed DEMO connection stops polling. Restart with the same journal to preserve observations. Use a separate journal for each broker feed.

```powershell
python scripts/run_shadow_diagnostics.py --journal runtime/shadow.sqlite3 --export
```

The observer requests completed H1 EURUSD bars starting at position 1. It evaluates the frozen Compression Release rules on chart OHLC as a bid-price proxy and uses raw broker-hour labels for the session filter. Both differ from the certified inputs a future forward simulator would need. SQLite stores the first observation per raw bar, including zero-direction decisions. The journal covers sampled bars. It does not reconstruct missed opportunities during downtime.

The mode is diagnostics only even if a raw timestamp passes the existing UTC checks. No simulated entries, exits, cost estimates, P&L or broker order routes exist in this command. The exported observations are not an evaluation of the sealed historical holdout.
