# L1, Orchestration + base integrations (reuse, never reimplement)

## schedule-reminder (the only scheduling surface)
`scripts/schedule_bridge.py` shells out to the schedule-reminder base CLI (`reminder.py <verb>` with the arguments listed in the bridge; its path is resolved from `$PROMO_REMINDER_PY`, default a generic per-tool location) and
requires JSON stdout. It does not pass `--json`; setup must verify installed helper compatibility.
Set `PROMO_REMINDER_PY` to the installed helper and run `python "$PROMO_REMINDER_PY" ensure --help`.
For managed installations, use the current runtime's Python and helper path. Initialize the store
with `python "$PROMO_REMINDER_PY" init`. Promotion uses that same Python interpreter for the bridge.
Creation calls `creation-preflight`, checks that the scan completed, then calls `ensure` with the
same fields. It passes no review overrides: ambiguous new obligations return `ERR_CREATION_REVIEW`
for operator review, while an unchanged request can replay even after its task is completed.
NEVER read its `.db` or build SQL. Each promo item:
- `--source promotion-assistant`
- `--idempotency-key promotion:<sha256 of product/campaign/arm/channel/account/action/date>` (same obligation/date retries use the same key; E12 requires an available compatible helper)
- `--ext '{"x_promotion_campaign_id":..,"x_promotion_arm_id":..,"x_promotion_channel":..,"x_promotion_utm":..}'`
- `--due-at <ISO>` drives the human-paced cadence; `transition` records funnel progress.
Cross-channel dependencies use `block/--blocker-id`. Do not assume the installed helper supports a flag or receipt format without checking it.

`plan --days` is a positive horizon for the campaign's existing slots, not a repetition count.
The first plan saves title, due_at, idempotency_key, ext and description in
`metrics/schedule-requests/<64-hex-digest>.json` in the PRIVATE companion before invoking the helper.
Same-date retries reuse the saved due time, identity and fields even after tasks complete.
Changed content or malformed requests stop with `ERR_SCHEDULE_CHANGED`; inspect the saved request
and existing reminder before changing the plan. Intentional date changes use update or snooze
on the existing task. Restore exact receipts with scheduler registrations before retrying.

Adjacent `.<digest>.json-<suffix>` staging and lock files are source-declared. Preserve interrupted
files until transaction and registration outcomes are known. Scheduling completes only after
successful JSON receipts with task IDs; failed or unavailable registration makes `plan` fail.

## Alerts (Discord relay, one-way Claude→phone)
Periodic `due` reminders ride schedule-reminder's own tick/relay. `scripts/alert.py` is ONLY for
promotion EXCEPTIONS that must page now: ban/shadowban, deliverability drop, unsub spike, a dry-run
that caught a would-be real send, a warmup milestone. It calls the local notifier (path resolved
from `$PROMO_NOTIFIER_PY`, default a generic per-tool location); keep it a dedicated push channel.

## Email transport
The email adapter requires the explicit [reviewed-email-v1 contract](email-helper-contract.md).
The helper path is resolved from PROMO_SEND_GMAIL; a legacy helper's mere presence is not readiness.
Sender, recipient, subject and complete rendered body are frozen in the request, and the helper
receipt must prove the matching request digest and sender. This repository does not establish that
a separately installed helper supports the contract. Automated dispatch still requires both live
gates and fresh compliance review.

## Long-run shape
Queue-over-bare-cron (Postiz-style): a repeatable job runs the daily calendar refresh + health
sweep; delayed jobs fire scheduled posts with jitter. Token failure does NOT retry, it alerts and
waits for re-authorization. A dead-man-switch heartbeat catches a missed daily sweep.
