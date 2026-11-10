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

The audit reads a consistent SQLite snapshot and checks that each indexed decision has a matching, adjacent observed rollover. It counts neutral decisions, restarts, gaps, quote blockers and integrity issues. It reports the observation span, longest same-session interval and age of the last poll. A last poll more than 45 seconds old is flagged separately from structural integrity so archived journals can still pass the audit. The first rollover record, when present, includes the witnessed bar transition, both observation windows and associated market prices. The audit omits the private account binding and session identifiers. A failed integrity or decision check returns a nonzero exit status.

The mode is diagnostics only even if a raw timestamp passes the existing UTC checks. Clock trust remains uncertified. The export contains observations and signals without fills or P&L.

## Synthetic performance replay

`src/monitoring/synthetic_performance.py` exercises a hypothetical single-position lifecycle using immutable, explicitly synthetic inputs. It has no terminal, journal or CLI adapter. A fixture carries the strategy model ID, decision ID, timestamp, direction, position size, protection distances, initial equity and costs. The first strictly later bid/ask observation determines entry. A stop gap takes the worse executable price and a target is capped before adverse slippage. Decimal arithmetic accounts for commission and explicit swap debits. The output distinguishes open from closed positions and records realized net P&L, nominal R and the maximum marked equity drawdown within that replay.

Replaying the same ordered inputs reconstructs the lifecycle without persistent simulated orders. Hourly OHLC is insufficient for the replay. A future prospective runner would need certified quote provenance, a journal of immutable input references and versioned execution assumptions, a persistent trade key, and a portfolio reconciliation layer before aggregating net expectancy or account drawdown. Actual broker fills belong in a separate reconciliation path.

The Windows deployment keeps its original DPAPI pairing files and pause flag under the original checkout's `mt5-ai-bot/runtime`. The smoke CLI resolves that same runtime under the current Windows profile independently of the working directory. Execution requires a pre-existing valid ledger, a reviewed pin, and all other order gates. The CLI refuses to provision an account pin pending canonical runtime and broker history review.
