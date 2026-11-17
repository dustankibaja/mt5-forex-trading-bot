# Windows DEMO monitoring recovery

Run the supervisor in the same interactive Windows user session as the already installed and connected MT5 terminal. Use the original deployment's virtual environment and existing runtime. Stop the previous observer, API and dry-run worker after verifying their exact process identities. The supervisor refuses startup if it detects the legacy watcher or finds the loopback port occupied.

```powershell
$deployment = Join-Path $env:USERPROFILE 'mt5-forex-trading-bot/mt5-ai-bot'
& "$deployment/.venv/Scripts/python.exe" -B mt5-ai-bot/scripts/supervise_demo_monitoring.py --runtime "$deployment/runtime" --terminal "C:/Program Files/MetaTrader 5/terminal64.exe"
```

Use an absolute path to the supervisor when launching outside the source checkout. The only supervised children are the read-only observer and loopback status API. The observer publishes paused status and the existing redacted DEMO portfolio. The API uses the existing DPAPI read credential and has no control credential. Existing pairing reads continue to work. Simulation controls are unavailable in this monitoring mode. The pause flag and manual kill switch are preserved.

The observer checks the installed terminal path, DEMO mode, desktop Algo Trading state and the existing journal's salted account binding. It opens the original forward database in existing-file mode. A disconnected or absent terminal and failed IPC attachment retry. Missing account authorization, mismatched identity, funded mode and missing or corrupt journal state stop recovery. The supervisor does not launch MT5 or log into an account. After the operator restores the expected DEMO session, restart the supervisor if its retry budget was exhausted.

Each component retries independently after 5, 10, 20, 40, 80, 120, 120 and 120 seconds. Five minutes of stable operation replenishes its budget. A stale observer heartbeat after startup grace triggers worker recovery. The API's authenticated liveness check is separate from observer freshness. Windows byte locks prevent duplicate supervised runs and duplicate writers through the current observer entry points. A Windows job closes owned child processes when the supervisor exits. Logs contain component names, exit codes and redacted reasons.

Stop a foreground supervisor with Ctrl+C. For a detached supervisor, create `runtime/demo-supervisor.stop` under the existing deployment. The supervisor stops its children and publishes offline status. Remove only that marker before a deliberate restart. Logs and the canonical journal are preserved.

No scheduled task is installed. An interactive user-session task could invoke the same command once at sign-in after the terminal is opened. Use the same Windows user for DPAPI, the fixed source checkout and original runtime, and disable multiple instances. There is no unattended broker executor in this command.

## Paper journal benchmark

From the project root with its Python environment active, run:

```powershell
python mt5-ai-bot/scripts/benchmark_paper_fixture.py 1000 10000 30000 --scratch <existing-scratch-directory>
```

The benchmark uses temporary synthetic databases. It checks replay equality, times one append and restart reconciliation, runs SQLite integrity verification, and measures Python allocations in a separate traced replay.
