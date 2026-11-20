# E.1 approved-host deployment feasibility gate

Status as of backend checkpoint `a98edea`: **not deployable for certification**.
The code is suitable for an independent security review and controlled host
integration, but no two compatible production authorities have been confirmed.

## Decision

| Gate | Decision | Evidence / boundary |
| --- | --- | --- |
| Ed25519 integration | PASS (offline) | Pinned authority/key adapter, rotation and revocation rejection, plus disposable-key and public RFC test-vector coverage. |
| Host timestamp capture | PASS (offline) | The runner generates challenges and captures request/receipt monotonic times internally. Test clock injection is available only through `for_test`. |
| Two compatible independent time authorities | UNCONFIRMED | No reviewed authority has been established that signs the exact `emtifize-signed-utc-v1` canonical payload. |
| External audit checkpoint destination | MISSING | The ledger can export/verify checkpoint heads but no independent destination has been configured. |
| Native/Python MT5 bridge | IMPLEMENTED MODEL ONLY | The bridge preserves/binds read-only fields but has not collected authenticated build-6327 observations. |
| UTC-day risk qualification | INCOMPLETE | No genuine bounded UTC interval, verified midnight baseline, complete history, or uninterrupted observation period exists. |

## Source feasibility finding

The custom Ed25519 assertion protocol is **not currently deployable** against
ordinary public time services. Google Public NTP explicitly says it supports
neither Autokey nor NTS, while NIST’s authenticated service uses prearranged
shared keys and says NTS-KE is not yet supported. Neither service signs the
Emtifize canonical assertion or provides its Ed25519 public-key lifecycle.

The standards-track alternative is Network Time Security (NTS, RFC 8915): it
uses TLS-authenticated NTS-KE and authenticated NTP extension fields. NTS has
a different key model and packet protocol, so it cannot be inserted behind the
custom assertion adapter. Moving to NTS is likely more practical than operating
two custom signing authorities, but requires a separately approved architecture
decision, source/provider qualification, and an implementation/security review.

## Minimum approved Windows host checklist

Development-complete components:

- Install the reviewed Python dependency set including `cryptography`.
- Deploy an approved stable host identity and a read-only, verified local MT5
  DEMO account binding; do not copy sandbox credentials, profiles, or journals.
- Deploy pinned public keys, authority identifiers, rotation/revocation policy,
  and the verified authority-bound Ed25519 adapter through an administrator
  controlled key-management process.
- Use a dedicated local SQLite evidence store with restricted ACLs and an
  external, independently controlled checkpoint destination.
- Provide a read-only MT5 adapter that supplies raw native/Python tick fields
  to the build-6327 bridge; it must not expose trading calls.

Operator-controlled prerequisites (not performed here):

1. Approve network egress to two independently operated, reviewed signed-time
   authorities **or** approve an NTS architecture decision and suitable NTS
   providers. Record protocol, authentication, ownership/family, public-key or
   certificate provisioning, network paths, and operational support terms.
2. Approve the external audit-checkpoint destination and retention/access
   policy. Exported local checkpoint data is not sufficient.
3. Establish genuine bounded UTC measurements on that host. Revoke on source
   disagreement, expiry, network uncertainty, sleep/resume, monotonic anomaly,
   host/account/epoch change, or unavailable evidence.
4. With a read-only connected DEMO terminal, collect fresh build-6327 native and
   Python EUR/USD observations from the same host/account. Preserve raw values;
   do not infer a timezone offset.
5. Obtain authenticated broker-history coverage and observe an uninterrupted
   UTC-day boundary before beginning risk qualification.

No action in this checklist authorizes Windows Time, firewall, DNS, MT5
permission, credential, broker, or execution changes. `order_check`,
`order_send`, reservations, and automated trading remain prohibited.
