# E.1 signed-time security review

Scope: the offline approved-host signed-time protocol and append-only evidence
ledger. This review is not evidence of a live UTC authority, Windows clock
synchronization, MT5 timestamp semantics, or risk qualification.

## Corrected, reproducible defects

| Severity | Finding | Resolution |
| --- | --- | --- |
| High | A valid assertion could previously be presented without a locally issued request. | `b828aa7` persists an authority/host/epoch-bound random challenge before acceptance and atomically consumes it. |
| High | A replay after a process restart could be ambiguous without durable consumption. | The SQLite consumption record is committed in the same transaction as acceptance; rollback tests prove a failed insert leaves the challenge unconsumed. |
| Medium | Host request/receipt time could be confused with authority-signed time. | The signed canonical payload contains only the authority assertion. Local monotonic timestamps remain host facts and determine the full request/receipt uncertainty interval. |
| Medium | Fixture callbacks could be mistaken for a cryptographic provider. | The Ed25519 keyring validates a pinned authority-to-public-key mapping, rejects revocation, and exposes no private-key support. The runner never returns a certified result. |
| Medium | A local hash chain cannot reveal a complete database rewrite. | Exportable checkpoint heads and offline verification were added. An independently retained checkpoint is still mandatory for that threat. |

## Remaining review concerns, not resolved by offline code

- A host administrator must establish at least two independent authorities that
  actually support the exact signed protocol and deliver their reviewed public
  keys through an approved key-management path. No arbitrary NTP endpoint is
  compatible merely because it reports time.
- Rotation and revocation policy must be operated by that approved deployment
  path. A revoked fingerprint is rejected by code, but no live revocation feed
  exists in this sandbox.
- Suspend/resume, monotonic discontinuity, network asymmetry, source
  disagreement, and authority availability require real approved-host
  measurements. The collection path must reject or revoke evidence on those
  conditions rather than infer a timezone correction.
- Audit checkpoints must be retained by an independent destination. Exporting
  one locally does not count as anchoring.
- The MT5 build-6327 bridge preserves raw MQL5/Python fields and locally flags
  repetition. It does not infer provider UTC semantics, and it does not call
  MetaTrader APIs.

## Threat model boundary

The ledger detects alteration, omission, and orphaning when compared with its
current chain or an independently retained checkpoint. An attacker able to
rewrite both the local database and every external checkpoint destination is
out of scope; protecting the latter requires independent operator-controlled
retention and access controls.
