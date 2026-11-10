# Read-only DEMO shadow diagnostics

From `mt5-ai-bot` with the project environment active, run one observation:

```powershell
python scripts/run_shadow_diagnostics.py --terminal "C:/Program Files/MetaTrader 5/terminal64.exe" --journal runtime/shadow.sqlite3
```

Add `--watch` to poll every 15 seconds. Ctrl+C detaches the Python process from MT5. A failed or changed DEMO connection stops polling. Restart with the same journal to preserve observations. Use a separate journal for each broker feed.

```powershell
python scripts/run_shadow_diagnostics.py --journal runtime/shadow.sqlite3 --export
```

The observer requests H1 EURUSD bars including the active bar as a rollover marker. It evaluates only the completed bar when consecutive polls in the same process observe an adjacent rollover. The frozen Compression Release rules use chart OHLC as a bid-price proxy and raw broker-hour labels for the session filter. Both differ from the certified inputs a future forward simulator would need.

SQLite stores each poll with host UTC bounds, monotonic time, raw broker timestamps, bid and ask. A separate unique bar key prevents duplicate rollover signals, including zero-direction decisions. Restarts, gaps in polling, and non-adjacent raw bar times are marked. Retrieved candles are indicator warm-up context. The journal preserves prior Sprint 5 rows in the JSON export's `legacy` array. New rows appear in `forward`. Add `--format csv` to export the new poll records as CSV.

Audit an existing journal while the observer is running:

```powershell
python scripts/run_shadow_diagnostics.py --journal runtime/shadow.sqlite3 --audit
```

The audit reads a consistent SQLite snapshot and checks that each indexed decision has a matching, adjacent observed rollover. It counts neutral decisions, restarts, gaps, quote blockers and integrity issues. The summary omits the account binding digest and quote prices. A failed integrity or decision check returns a nonzero exit status.

The mode is diagnostics only even if a raw timestamp passes the existing UTC checks. Clock trust remains uncertified. The export contains observations and signals without fills or P&L.

The Windows deployment keeps its original DPAPI pairing files and pause flag under the original checkout's `mt5-ai-bot/runtime`. The smoke CLI resolves that same runtime under the current Windows profile independently of the working directory. Execution requires a pre-existing valid ledger, a reviewed pin, and all other order gates. The CLI refuses to provision an account pin pending canonical runtime and broker history review.
