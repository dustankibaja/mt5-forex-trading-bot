# Approved-host time-certification runbook (not executable in the sandbox)

This runbook is for an operator-approved Windows host outside the Codex sandbox
firewall boundary. It is not a request to weaken, bypass, disable, or alter
the `codex_sandbox_offline_block_*` rules. Do not transfer MT5 account files,
credentials, terminal data directories, or Emtifize journals from this host.

## Operator and administrator prerequisites

1. Use a permitted Windows host with reliable power and normal outbound UDP/123
   connectivity. The host administrator owns all Windows Time, DNS, firewall,
   and policy changes.
2. Record before-state diagnostics: `w32tm /query /status /verbose`, source,
   peers, configuration, DNS resolution, and bounded strip charts against at
   least two independently administered time-source families.
3. If the host is unsynchronised, the administrator may perform only approved
   Windows Time remediation and an elevated resynchronisation. Retain before
   and after output. A successful command alone is not UTC certification.
4. Confirm a selected non-CMOS source, nonzero stratum, recent successful sync,
   stable repeated NTP observations, and no clock-step/sleep interruption.

## Bounded UTC measurement record

An approved authority adapter must produce one record per measurement with:

- authority/source identity and independently administered source family;
- observed UTC value, host monotonic anchor, collection time, and expiry;
- measured network delay/asymmetry allowance and an explicit uncertainty bound;
- synchronization epoch identifier derived from the selected source/configuration
  and a retained before/after status snapshot;
- continuity sequence number and evidence of no host clock rollback.

Windows Time status, NTP peer strings, a raw offset, or a broker timestamp are
not by themselves uncertainty bounds. The adapter may issue Emtifize UTC
evidence only while the stated bound is within the frozen policy limit and the
source identity/synchronization epoch are unchanged. Any lost sample, source
change, sleep, clock step, expiry, or disagreement invalidates the chain.

## MT5 build-6327 timestamp comparison

After UTC evidence is live and before any risk period begins, use the existing
read-only native MQL5 clock probe and a read-only Python collector on the same
already-authenticated DEMO terminal. Neither component may login, switch
accounts, modify permissions, call `order_check`, call `order_send`, or submit
an order.

For EURUSD, GBPUSD, and USDJPY, retain raw native/Python `time` and `time_msc`,
bid, ask, provider timestamp, bounded UTC receipt interval, and host monotonic
receipt time. Mark repeated ticks as cached. Match exact ticks or bracket a
changed tick between receipts; do not infer a timezone from a recurring offset.
Only a prospective, evidence-backed semantics attestation may be passed to the
quote certifier. Failure or ambiguity leaves certification false.

## Risk-qualification start

Only after the above succeeds may a new collector, bound to the host's local
DEMO identity, begin a UTC-day observation period. It must record samples
bracketing a genuine UTC midnight, preserve uninterrupted continuity, review
broker history for balance operations/external activity/exposure, and keep
observed peak equity distinct from an unknowable continuous peak. Any gap,
restart, account/source change, cash movement, exposure, or incomplete history
invalidates the period. `QUALIFIED` remains unavailable until every condition
in `RISK_QUALIFICATION.md` is genuinely evidenced.
