# E.1 approved-host certification checklist

## Implementation completed in the sandbox

- The quote certifier fails closed for absent, untrusted, expired, excessive-
  uncertainty, non-sequential, cached and future-dated evidence.
- UTC evidence is internally issued only after an approved-host measurement,
  and is bound to an account identity, host identity, source identity and
  synchronization epoch.
- The approved-host UTC adapter rejects an untrusted reference record, an
  unapproved source fingerprint, source disagreement, host mismatch, expired
  calibration, sleep and host clock steps.
- Certification requires an MT5 observation host identity that equals the UTC
  evidence host identity. The future MT5 collector must supply that identity;
  the existing onboarding path supplies no evidence and remains uncertified.
- Risk samples stay `INCOMPLETE` or `INVALIDATED` without controlled UTC,
  complete broker history and uninterrupted coverage. `QUALIFIED` is not
  emitted by the current collector.

## Implementation still required before qualification can be possible

1. A reviewed local host transport verifier must authenticate independent UTC
   authorities and retain its raw measurement/transcript evidence. The private
   test factory is deliberately not an authority.
2. The MT5 native and Python collectors must write the same host identity,
   account binding, receipt monotonic time, raw provider fields and UTC epoch
   to a durable append-only observation record.
3. A durable qualification evaluator must enforce a UTC midnight boundary,
   complete account/deal/order/position history, balance-adjustment detection,
   reconnect/continuity handling, account/source/host changes and evidence
   expiry. It must not infer opening equity or continuous equity peaks.
4. Broker timestamp semantics must be independently attested using genuinely
   new native and Python observations. No timezone offset is assumed.

## Operations requiring the approved-host administrator

1. Use a separate Windows host with its own authorized MT5 DEMO login. Do not
   copy MT5 profile/account files, credentials, journals or sandbox evidence.
2. Obtain administrator-approved Windows Time/DNS/network remediation only on
   that host. Do not alter the Codex sandbox firewall or bypass its isolation.
3. Collect authenticated UTC measurements from at least two independent source
   families, record network delay/dispersion, source identities, monotonic
   receipt times, uncertainty, clock drift and a synchronization epoch.
4. Revoke the epoch on a clock change, synchronization loss, source conflict,
   excessive uncertainty or observation gap. Establish a new epoch only from
   a fresh bounded calibration.
5. With the same host and verified DEMO binding, collect fresh MT5 build-6327
   native and Python ticks. Preserve raw broker timestamps and compare them to
   the bounded UTC evidence without guessing a conversion.
6. Only after timestamp semantics pass, start a new uninterrupted UTC-day risk
   observation period. Record deposits, withdrawals, resets, external trades,
   exposure and reconnections as explicit invalidators.

## Current decision

Actual quote certification is **false** and risk qualification is
**INCOMPLETE**. Production reservations, order checks, order submission,
automation and broker trades remain prohibited.
