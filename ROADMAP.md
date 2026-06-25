# Roadmap

Current: **v0.1.0**

## v0.1.0 (current)
- Six-layer architecture: config (Mode B) · orchestration (schedule-reminder + relay) · channel
  providers · compliance/throttle (fail-closed dry-run exit) · metrics (funnel + attribution) ·
  bandit (discounted Thompson Sampling).
- Dual-line engine: blast (email via send-gmail.ps1, multi-platform posting) + precision (forum/DM)
  with email + own-server Discord as live transports; Mastodon/Bluesky/Reddit/X/PH/HN as deferred-gaps.
- Acceptance gate E1-E12 (`selftest.py`) — all passing, zero egress.

## Planned (each lights up a new acceptance signal)
- Stage-3 contextual bandit (Vowpal Wabbit) → per-segment regret beats no-context baseline.
- Mastodon/Bluesky/Reddit live providers → flip deferred-gaps to live transports.
- Mailbox-pool warmup + inbox-placement probe → deliverability-driven auto-throttle.
- Sequential A/B with always-valid p-values (mSPRT) → reportable causal claims.
- Off-policy evaluator (Doubly Robust) → safe pre-launch policy comparison.
