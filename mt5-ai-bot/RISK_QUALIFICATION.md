# DEMO risk qualification

Read the latest risk_samples row for the pinned installation. An absent row or an expired sample cannot support readiness. Rows record the host UTC reading, monotonic reading, reader session, salted binding identifier, measured equity and reason. The host UTC date is provisional until independently certified.

INCOMPLETE means the available observations cannot establish opening equity. OBSERVING means consecutive measurements met the two-second sampling budget. INVALIDATED records an observed interruption, account change, unattributed trade, balance adjustment, open exposure or unavailable history. Reopening the reader starts a new session. A new UTC date starts a new observation period. A prior invalidation stays in the same day's audit history.

QUALIFIED is reserved for a future verified boundary observation. For a flat account this requires samples bracketing midnight with independently bounded UTC, matching identity and unchanged balance, complete broker records that exclude open exposure, trades and cash movements across the boundary, and uninterrupted coverage thereafter. Any reset requires a new baseline. For an exposed account the risk policy also needs a defensible bound on unobserved equity excursions. A sampled peak only bounds the continuous maximum from below.

The current collector cannot establish those conditions. It never emits QUALIFIED or authorizes reservations.
