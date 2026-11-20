# Windows Time remediation proposal (not executed)

The current E.1 terminal remains blocked from quote-time certification. Prior
read-only diagnostics observed intermittent DNS failure for `time.windows.com`,
an unsynchronised Local CMOS source, and a stratum-zero status. A successful
Windows Time command alone is not enough to certify broker quote timestamps.

## Required operator authorization

The following is a minimal *proposal*, not an instruction that Emtifize may
execute automatically. It requires an administrator/operator to approve every
system change and to preserve before/after evidence.

1. Record `w32tm /query /status /verbose`, source, peers and configuration;
   retain relevant Windows Time events.
2. Restore reliable DNS resolution for the configured peer and confirm outbound
   UDP/123 reachability using the organisation's approved network controls.
3. Have the administrator review the active Windows Time policy and configured
   peer. Change policy, peer, service configuration, or the system clock only
   when the administrator has separately approved that specific change.
4. After a supported resynchronisation, require a non-CMOS selected source,
   nonzero stratum, current successful-sync timestamp, and measured bounded
   uncertainty from an independent UTC authority. Persist the source identity
   and synchronization epoch.
5. Only then collect a short, new native-MQL5/Python EURUSD/GBPUSD/USDJPY
   comparison. Preserve raw broker timestamps and receipt monotonic times; do
   not apply a timezone offset. Feed the resulting attestation through the
   read-only UTC evidence collector.

Failure at any point keeps quote-time certification false and invalidates the
current continuity chain. This remediation does not authorize MT5 orders,
change broker permissions, or qualify the UTC-day risk baseline.
