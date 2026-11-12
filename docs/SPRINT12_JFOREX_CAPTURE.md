# JForex DEMO capture and acceptance v1

Use an account issued through the [official JForex DEMO form](https://www.dukascopy.com/swiss/english/forex/demo-fx-account/). The collector masks both fields in an interactive terminal, or opens a masked Windows dialog when launched with `javaw.exe`. Do not pass either value on the command line or in chat. No automatic login, production endpoint or broker order path exists. The vendor SDK requires credentials as strings at its API boundary; process memory should be treated accordingly. Vendor console logging is suppressed during authentication. A non-identifying `demo_account_connected` marker comes from the SDK account callback after the fixed DEMO connection; no account identifier or balances are recorded. Market callbacks are gated on the connected account state.

Install Java 17 and Maven 3.9.9 from their official distributions. With the working directory at the repository root, build:

```powershell
mvn -B -ntp -f research-jforex/pom.xml compile dependency:copy-dependencies
java -cp 'research-jforex/target/classes;research-jforex/target/dependency/*' ai.emtifize.DemoCollector 'C:/private-research/new-session.tsv' 604800
```

Run interactively from a directory whose ACL permits only the operator and trusted administrators/system. Use a new spool path each time, on a disk with monitored free space. Keep SDK logs private. The collector uses the [official DEMO client procedure](https://wiki.dukascopy.com/en/development/get-started-api/use-jforex-sdk/sdk-client/) and pins SDK 3.6.51 and API 2.13.99. Reconnect uses the existing SDK session only, with three waits of 5, 10 and 20 seconds, followed by resubscription; failed initial login is not retried. Reauthentication requires operator intervention. The application heartbeat is a client state observation, not a provider heartbeat or a quote.

The local append-only ASCII TSV schema has: schema version `1`, source (`jforex_demo` or `synthetic`), producer version `collector-1`, run UUID, local sequence, kind, raw provider epoch ms (or zero for control events), host receipt UTC ms, elapsed process monotonic ns, cumulative queue drops, and `EURUSD`. Ticks add bid and ask; H1 adds bid O/H/L/C then ask O/H/L/C; the raw H1 stamp denotes the shared open. Events use immutable UUID:sequence IDs. Queue capacity is 8,192, and full queues leave explicit sequence and drop counters. The writer forces batches to disk. An abrupt kill may lose the unforced tail; preserve it for forensics and begin a new UUID. An incomplete spool cannot be imported as a sealed run. Never append to an existing spool.

From `mt5-ai-bot`, run `python -B -m src.research.jforex_capture <closed.tsv> <dedicated.sqlite>`. Imports are atomic, preserve original bytes, replay in sequence order and reject conflicting IDs. Exact spool re-import is idempotent. The database is research-only; the trust result remains quarantined even if automated thresholds pass. Java and Python share only user-local files. There is no adapter route into fills.

Use `python -B -m src.research.jforex_capture <spool.tsv> --preview` for a bounded diagnostic of an active spool. It ignores an incomplete trailing line and does not write a journal. On the first authenticated EUR/USD tick, the collector requests the prior 220 completed H1 bars per side and writes aligned pairs to a separate `.warmup.csv` file with `jforex_live_origin_warmup` provenance. Pass `--no-warmup` after the duration for the acceptance cohort, so the historical request does not block the timing callbacks.

### Desktop DEMO recorder

Open `research-jforex/desktop/EmtifizeDemoCapture.java` from **View → Code Editor → Open → Computer**, compile it, then start **Local Run** in the Navigator. The recorder requires a DEMO account and writes a new `diagnostic-desktop-*.tsv` in the existing private JForex capture folder. JForex requests strategy filesystem access because the recorder writes that local file. The recorder uses bid/ask and completed H1 callbacks, and has no order code.

Run `python -B -m src.research.jforex_capture <spool.tsv> <private.sqlite> --active-prefix` to checkpoint complete lines without stopping Desktop. The command emits timing, sequence, loss, and candle diagnostics as JSON. Re-running it on the growing spool imports only new IDs, rejects edits and truncation, and ignores an unfinished trailing line. Omit the option when importing a completed capture with its end marker. Store reports and journals outside Git when they include run IDs or quote records.

After a network interruption or sleep, check JForex connection and whether file size and tick sequence advance. If the file advances, preserve the same run and treat the interrupted interval as missing coverage. If JForex or the strategy stops, preserve and checkpoint the old file, sign in to Desktop DEMO if needed, and start Local Run again to get a new file. A write error needs free space and working access to the private folder before restarting. Never concatenate files or count time between ticks as confirmed active coverage. Desktop does not record a verified reconnect when the platform silently recovers; use a separately documented controlled reconnect for acceptance.

### Sprint 13 continuity and clock evidence

The Desktop recorder tagged `collector-2` writes a heartbeat every 15 seconds and records observed account disconnect and reconnect callbacks. It waits for an actual EUR/USD tick before marking the subscription resumed. If the platform stops the strategy, inspect the existing file before starting one new Local Run. The earlier `collector-1` spool is still supported. Do not restart a working capture just to replace it with the newer version.

Use `python -B -m src.research.jforex_capture <spool.tsv> --health` to inspect a bounded tail without reading the full spool. A heartbeat without a recent tick is missing market coverage. Use `--expected-closure` only for an independently verified scheduled closure. A quiet tail without a heartbeat is unverified. Keep Windows awake during target sessions. Check the active AC and battery sleep settings, lid behavior, and connectivity before a qualified run.

On import, diagnostic timing segments split at a 60-second intertick gap or a 100 ms divergence between wall and monotonic elapsed time. These are reporting boundaries and do not revise the acceptance policy. Reconstructed OHLC is reported both for all observed valid ticks and for ticks passing the raw age gate, with the number of ticks and distance from the hour boundaries. Clock eligibility must be confirmed independently.

Run `w32tm /query /status` and `w32tm /stripchart /computer:<reference> /samples:6`. For root delay, dispersion and individual sample errors, use `python -B scripts/probe_jforex_utc.py --samples 6 tz.pool.ntp.org time.cloudflare.com time.google.com time.windows.com`. A positive offset means reference UTC leads host UTC. The diagnostic allowance includes path asymmetry, advertised upstream delay and dispersion, reference precision and a host sampling margin. This remains an unauthenticated measurement. Retain all samples and require repeatable corroboration before recording an acceptance start.

Compression Release first permits evaluation at index 210 and uses midpoint EMA200, EMA50, previous ATR14, and 12 prior highs and lows. Prepare at least 211 aligned, contiguous completed bid/ask H1 bars immediately preceding the frozen prospective start, allowing documented market closures. The 220-bar historical warm-up request provides a small margin over this minimum. Record the seed window because EMA200 depends on prior history. Keep historical live-origin data separate from captured DEMO quotes and never use warm-up to fill an observation gap.

Before capture, record an independent host UTC reference and uncertainty at most 100 ms; corroborate during each target day and after the controlled reconnect. Provider time and receipt time are separate. Preserve device and reference evidence privately. Use at least five weekday market dates with all 11 target hours (07–17 UTC) fully covered; start before the first target hour and continue past the last close. Compare completed provider bid/ask H1 OHLC exactly with OHLC of eligible observed ticks; report missing or mismatched hours and never fill them with historical data. A match does not prove every intrabar tick arrived. Live-origin history is warm-up only. Document the controlled reconnect outside target hours where possible; the analyzer reports observed disconnect-to-first-eligible-tick time.

Frozen thresholds: reject ages below −100 ms or above 2,000 ms, invalid/crossed quotes and backward provider timestamps; separately count negative ages, exact same-time/price repeats, order anomalies, stale values, bad candles and explicit loss. Preserve same-time price changes. Require target-hour nonnegative delivery p99 ≤1,000 ms, using distinct valid ordered observations including stale values capped at 2,001 ms for the threshold computation. Missing sequence numbers, queue loss, provider timestamp-unit failures, UTC/monotonic inconsistency or ambiguous candles block automated passage. An independent clock and controlled-reconnect review remain mandatory. Do not adjust these rules after seeing authenticated data. There is no paper freeze until that review passes.

Offline reproduction: substitute `ai.emtifize.Fixture` and omit the duration, using a fresh file. The resulting spool must stay synthetic and contains a deliberate duplicate, stale/out-of-order tick and reconnect. Run Python tests for malformed/partial spools, idempotency, conflicting IDs, and quote classification.

## Sprint 14 Desktop recovery

Seal and ingest the old spool before switching the local Desktop strategy. Use a unique spool per start, and pass `--active-prefix` for repeatable snapshots of the active writer. In JForex Desktop, run the recorder locally in the authenticated DEMO session. Clear the **Retrieve historical warm-up once** checkbox for continuous recording. The recorder binds the account in memory and can recognize recovery from the first EUR/USD tick when the positive account callback is delayed or absent. Keep the sequence from disconnect through the first returning eligible tick when measuring recovery.

Run the separate `EmtifizeWarmupExport` helper locally to isolate IHistory requests from continuous capture. It starts on the first EUR/USD callback, requests BID and ASK histories for completed H1 bars and validates pairing before export. Any resulting CSV belongs in the private JForex directory with warm-up provenance. A history failure leaves warm-up pending.

Record the active Windows Time configuration before trialing a peer. The supported commands used in the Windows NTP client trial and rollback were:

```powershell
w32tm /config /manualpeerlist:time.cloudflare.com,0x8 /syncfromflags:manual /update
w32tm /resync /rediscover
# Restore the original standalone workstation configuration.
w32tm /config /manualpeerlist:time.windows.com,0x9 /syncfromflags:manual /update
w32tm /resync /rediscover
```

Collect independent reference samples and bound uncertainty after a successful resync. Keep Windows sleep gaps and clock steps out of qualifying coverage. Leave the acceptance start unset until the frozen prerequisites pass.
