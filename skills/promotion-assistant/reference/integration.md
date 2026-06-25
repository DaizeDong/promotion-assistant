# L1 — Orchestration + base integrations (reuse, never reimplement)

## schedule-reminder (the only scheduling surface)
`scripts/schedule_bridge.py` shells out to `~/.claude/skills/schedule-reminder/scripts/reminder.py
<verb> --json` and parses stdout. NEVER read its `.db` or build SQL. Each promo item:
- `--source promotion-assistant`
- `--idempotency-key promotion:<product>:<arm>:<yyyymmdd>` (replays never duplicate — verified by E12)
- `--ext '{"x_promotion_campaign_id":..,"x_promotion_arm_id":..,"x_promotion_channel":..,"x_promotion_utm":..}'`
- `--due-at <ISO>` drives the human-paced cadence; `transition` records funnel progress.
Cross-channel dependencies use `block/--blocker-id`. Contract api_version is additive-only → safe to pin.

## Alerts (Discord relay, one-way Claude→phone)
Periodic `due` reminders ride schedule-reminder's own tick/relay. `scripts/alert.py` is ONLY for
promotion EXCEPTIONS that must page now: ban/shadowban, deliverability drop, unsub spike, a dry-run
that caught a would-be real send, a warmup milestone. It calls `~/.claude/discord_relay/send.py`
(Big Brother bot) — do NOT mix with the Haptic scheduler bot.

## Email transport
`scripts/providers.py:EmailProvider` wires the machine's `~/.claude/scripts/send-gmail.ps1` SMTP link
(DPAPI-encrypted app password, no secret in any repo). It is reachable only through the live-gated
`dispatch()` exit; in build/test it never runs.

## Long-run shape
Queue-over-bare-cron (Postiz-style): a repeatable job runs the daily calendar refresh + health
sweep; delayed jobs fire scheduled posts with jitter. Token failure does NOT retry — it alerts and
waits for re-authorization. A dead-man-switch heartbeat catches a missed daily sweep.
