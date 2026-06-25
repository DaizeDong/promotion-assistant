# L3 — Compliance + throttle (fail-closed) and the dry-run exit

## Compliance gate (`scripts/compliance.py`, pre-send Side-A)
Returns `(ok, reasons)`; `dispatch()` rejects on any reason — there is no warn-and-send path.
- **CAN-SPAM** (email): real From/Reply-to, non-deceptive subject, real physical postal address,
  functional unsubscribe.
- **GDPR/PECR/CASL**: EU/EEA recipients must have a lawful basis in `compliance/consent-ledger.jsonl`.
- **Suppression** (`metrics/suppression.csv`): unsub + hard-bounce + complaint, checked every send,
  unsub recorded immediately and permanently.
- **Banned claims**: product `banned_claims` substrings rejected anywhere in subject/body.
Verified by E5 (5 violation classes all rejected, valid passes).

## Throttle (`scripts/throttle.py`, per account×platform×action)
- **token-bucket + AIMD**: friction-free → multiplicative-then-geometric growth; 429/warning/forced
  re-auth → cap ×0.5 + cooldown. Capacity = ~50-70% of the observed safe value, never a vendor number.
- **warmup state machine**: browse→like→follow_comment→nonpromo_post→normal; level-skipping forbidden;
  fresh accounts default to the full 14-day curve.
- **humanize**: lognormal inter-action jitter, work_window, per-account copy variants + content hash.
Verified by E4 (0 over-limit, 429 halves cap + cooldown).

## The dry-run exit (`scripts/dispatch.py`, the ONE outbound function)
fail-closed: real egress requires `product.json.send_mode=="live"` **AND** env
`PROMO_LIVE_AUTHORIZED_<CHANNEL>`. Missing either → SIMULATE: run the full pipeline (compliance →
throttle), write an `event_type=simulated` row + a `metrics/dry-run.jsonl` record (would-send content +
estimated recipients), and perform ZERO network egress. So the metrics stream + bandit train with no
real outreach. Verified by E7. **Going live is per-channel and deliberate** — see the config repo's
`runbooks/live-authorize.md`; the build/test phase is always dry-run.
