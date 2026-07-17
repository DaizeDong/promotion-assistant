# promotion-assistant, Design Philosophy

> One test governs every change: **does it fix the framing, or just patch a symptom?**

Promotion tooling fails in three predictable ways: it hardcodes platform rules that rot, it treats
compliance/safety as an afterthought bolted on top, and it optimizes vanity metrics until it becomes
a spam machine that gets every account banned. Each principle below changes the *assumption
underneath* one of those failures, not the symptom on top.

## P1, Methodology is constant; signals adapt
- **Symptom patch:** ship the current X/Reddit/email limits and copy inside the tool; chase each
  platform policy change with a code edit.
- **Root cause:** the *method* (channel matrix, six-layer funnel, bandit, compliance gate) is stable;
  the *values* (caps, audiences, copy, thresholds) drift constantly. So they must live in different
  places.
- **Decision it produced:** a product-agnostic public skill + a private per-product config repo
  (`PROMO_CONFIG_DIR`). Quotas come from runtime response headers, not a baked table.

## P2, Compliance is engineering, not goodwill
- **Symptom patch:** a checklist and a "please remember to add an unsubscribe link."
- **Root cause:** anything left to discipline eventually leaks; the only reliable control is a gate
  that *cannot be bypassed*.
- **Decision it produced:** a fail-closed compliance gate (CAN-SPAM/GDPR/suppression) on the send
  path, and ban/spam/unsub encoded as **strong-negative reward** so the optimizer internalizes the
  red-lines instead of needing an external rule patch for every new evasion.

## P3, Dry-run is the default, not an option
- **Symptom patch:** a `--dry-run` flag the operator must remember to pass.
- **Root cause:** real outreach is irreversible, disturbs real people, and risks bans, the *safe*
  state must be the one you fall into when you do nothing.
- **Decision it produced:** a single `dispatch()` exit that fail-closed requires
  `send_mode=="live"` AND a per-channel authorize token; absent either, it runs the full pipeline and
  writes simulated events + `dry-run.jsonl` with zero network egress. The metrics loop trains without
  ever sending.

## P4, Own the seam, delegate the engines
- **Symptom patch:** reimplement scheduling, notification and SMTP inside the skill.
- **Root cause:** those are solved bases on this machine; duplicating them creates drift and bugs.
- **Decision it produced:** scheduling → the `schedule-reminder` CLI contract (never its DB), alerts →
  the existing Discord relay, email → the machine's `send-gmail.ps1`. The skill owns the promotion
  logic; nothing else.

## P5, Proven, not generated
- **Symptom patch:** "the code looks right."
- **Root cause:** a promotion system that silently miscounts a funnel, lets the bandit lock onto a
  stale arm, or leaks a real send is worse than none.
- **Decision it produced:** `selftest.py` (E1-E12) machine-judges metrics exactness, bandit
  convergence + drift recovery, throttle limits, compliance fail-closure, dry-run zero-egress,
  propensity completeness, anti-fingerprint, delayed-conversion censoring and idempotency. No
  behavior ships until they pass; a failure is an explicit gap, never a silent ship.
