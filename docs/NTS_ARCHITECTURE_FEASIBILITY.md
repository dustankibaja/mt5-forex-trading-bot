# E.1 NTS architecture feasibility

## Decision: NO-GO for native approved-Windows deployment today

NTS is a stronger practical direction than operating two custom JSON-signing
authorities, but no maintained, supported NTS client was verified for the
required native Windows host. This is an operational compatibility blocker, not
a reason to downgrade to unauthenticated NTP or move silently to another host.
No architecture replacement is made by this document.

## Verified provider matrix

| Provider | Public NTS evidence | NTS-KE / authenticated NTP | Independence | Host requirements / diagnostics | Limitation |
| --- | --- | --- | --- | --- | --- |
| Cloudflare | Official Time Services documentation says `time.cloudflare.com` supports NTS and names Chrony, NTPsec and ntpd-rs clients. | Standard RFC 8915: TLS NTS-KE followed by authenticated NTP extension fields. NTS-KE TCP/4460; NTP UDP/123. Validate the normal TLS service identity; do not pin an observed certificate without a key lifecycle plan. | Cloudflare-operated. | Approved outbound TCP/4460 and UDP/123; retain TLS/NTS transcripts and local monotonic timings. | Provider documentation does not turn the NTS handshake into proof of local clock accuracy. |
| Netnod | Official configuration guide lists `nts.netnod.se` plus regional endpoints and describes the two protocol phases. | TLS NTS-KE followed by UDP timestamping; its guide distinguishes KE and timestamping server addresses and documents `chronyc`/`ntpq` diagnostics. | Netnod-operated, separate from Cloudflare and Meta. | Same outbound ports; record the negotiated endpoint/certificate, cookies only as protected transient material, and client delay/offset/dispersion diagnostics. | Its guide covers Linux clients and explicitly says Windows/Docker are not covered. |
| Meta | Official Meta engineering announcement says `nts.meta.com` is live and implements RFC 8915. | NTS-authenticated packets; RFC 8915 standard ports/protocol expectations apply. | Meta-operated, separate from Cloudflare and Netnod. | Same outbound ports; approved host must independently test certificate validation and measurement output. | Recent service; no host reachability or operational SLO is claimed here. |

RFC 8915 requires TLS 1.3 or later for NTS-KE, ALPN `ntske/1`, and uses TCP
4460 for key establishment. It then uses NTS extension fields and authenticated
NTP packets; it is not an Ed25519 signature over Emtifize JSON. Treat source
families as independent only after governance, infrastructure, network-path and
failure-correlation review by the host operator.

## Windows client assessment

| Candidate | Assessment |
| --- | --- |
| W32Time | Not selected. Microsoft documents NTP peers, not RFC 8915 NTS-KE/extension-field evidence or the raw authenticated measurement interface Emtifize needs. |
| Chrony | Not viable for native Windows: Chrony's FAQ explicitly says `chronyd` is not portable to Windows and has no plan to support it. It remains a mature NTS implementation on supported Unix-like platforms. |
| ntpd-rs | Technically promising: maintained Rust NTP/NTS implementation with observability of delay/dispersion. Its published 1.9.0 binaries are Linux deb/rpm packages; no supported Windows deployment was verified. |
| NTPsec | Netnod documents NTS configuration and diagnostics, but its official guide is Linux-focused; no maintained Windows deployment was verified. |

Therefore no software will be installed and no system service will be changed.
An approved Windows-native NTS client with reviewed package provenance, a
read-only measurement API, TLS/NTS transcript retention, and lifecycle support
must be identified before an administrator can proceed.

## Offline adapter prototype

`src/execution/nts_evidence_adapter.py` is deliberately not an NTS packet
implementation. It models the adapter boundary after a future collector has
already authenticated NTS-KE/TLS and NTP extension fields. It requires:

- two distinct authorities and source families;
- host/DEMO-account/epoch equality;
- request and receipt monotonic ordering, expiry and round-trip limits;
- bounded uncertainty and disagreement rejection; and
- an interval expanded by the **full** request/receipt round trip to avoid an
  unjustified symmetric-delay assumption.

It returns a non-certifying candidate only. It does not invoke the custom
Ed25519 path and cannot mint `UtcEvidence`; recorded fixtures cannot certify a
quote or risk state.

## Option comparison

| Option | Security / availability | Windows practicality | Recommendation |
| --- | --- | --- | --- |
| Retain custom Ed25519 protocol | Strong local design, but no confirmed independent public authorities signing the exact canonical assertion. | Requires operating or contracting two authorities and a key lifecycle. | Do not deploy without real authorities. |
| RFC 8915 NTS adapter | Standards-track authenticated protocol with multiple documented public providers. | Native approved-Windows client evidence is presently missing. | Preferred strategic direction, **not approved for implementation/deployment** until Windows client selection and security review are complete. |

## Approved-host prerequisites after a separate architecture decision

1. Select and security-review a supported Windows NTS client or explicitly
   authorize a different host architecture; do not substitute one silently.
2. Permit only needed NTS egress: TCP/4460 and UDP/123 to approved providers.
   Preserve the sandbox firewall boundary; do this only on the approved host.
3. Define certificate validation, trust-store/key-update policy, bootstrap
   failure handling, process restart, sleep/resume, clock-step and expiry rules.
4. Provide a read-only authenticated measurement export with raw request/receipt
   monotonic timestamps, NTS authentication status, provider identity, offset,
   delay, root dispersion and source status.
5. Retain raw transcripts/diagnostics and independently anchored audit
   checkpoints. Then bind the resulting evidence to the approved host and DEMO
   account before collecting fresh MT5 build-6327 observations.

No prerequisite authorizes a Windows Time change, firewall change in this
sandbox, MT5 modification, or order operation.
