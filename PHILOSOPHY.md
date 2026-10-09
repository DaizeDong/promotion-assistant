# promotion-assistant, Design Philosophy

Promotion combines changing platform policies, irreversible outreach and feedback-driven
selection. The design separates these concerns so product changes can be reviewed without
copying the engine or treating simulated results as delivery evidence.

## P1: Separate stable methods from product policy

The channel matrix, six-layer funnel, selection rule and compliance gate are reusable methods.
Caps, audiences, copy and thresholds change with products and platforms. Keep reusable code in
the public skill and product values in the PRIVATE companion selected by `PROMO_CONFIG_DIR`.
Per-channel policy supplies limits; observed rate-limit responses inform throttling.
Provider resources bind to that selected companion on every dispatch, so switching products
does not inherit another product's ambient credentials. Source-owned artifact admission makes
each new output kind an explicit design decision.

## P2: Check compliance on each dispatch

A reminder to include an unsubscribe link does not enforce a sending requirement. Supported live
dispatch paths therefore apply fail-closed CAN-SPAM, GDPR and suppression checks. Ban, spam and
unsubscribe feedback contributes strong-negative reward to the optimizer, alongside the explicit
send gate. Deployment still needs independent validation; reward design cannot replace that gate.

## P3: Default to simulated dispatch

Outreach affects real recipients and cannot be fully reversed. The single `dispatch()` exit
requires both `send_mode=="live"` and per-channel authorization. Without both, it runs the
pipeline and writes PRIVATE simulated events and previews without provider dispatch. Those
records exercise orchestration; they do not establish delivery or real conversion.

## P4: Reuse scheduling, alerts and email contracts

Separate engines own scheduling, notification and mail delivery. Calling their supported
interfaces avoids maintaining competing copies of their state and behavior. Scheduling uses the
`schedule-reminder` CLI, never its database; alerts use the configured Discord relay; email uses
an explicitly configured helper implementing the complete `reviewed-email-v1` request and receipt
contract. A legacy email helper alone does not establish readiness.

## P5: Require measured regression evidence

Incorrect funnel counts, stale-arm selection and unintended sending can invalidate the system's
results. `selftest.py` (E1-E12) checks metrics exactness, bandit convergence and drift recovery,
throttle limits, compliance fail-closure, dry-run zero-egress, propensity completeness,
anti-fingerprint, delayed-conversion censoring and idempotency. Applicable checks must pass before
behavior changes ship. Report failures and missing coverage explicitly; successful synthetic
checks do not establish live integration behavior or campaign outcomes.
