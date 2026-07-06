# Roadmap

Current: **v0.1.2**

## v0.1.2 (current)
- Compliance-matcher evasion hardening: banned-claim/body matching now NFKC-normalizes, strips
  zero-width/format chars, and folds common Cyrillic/Greek homoglyphs; suppression matching folds
  `+tag` aliases + case/unicode; CAN-SPAM fires when a payload is email-like (recipient/channel),
  not only when `transport=="smtp"` (so a mislabeled transport can't skip it). Guarded by
  `tests/test_compliance_hardening.py`.
- CLI: all subcommands surface a friendly "no config" message instead of an uncaught traceback.
- Added `CONTRIBUTING.md` (repo-spec completeness).

## v0.1.1
- Six-layer architecture: config (Mode B) · orchestration (schedule-reminder + relay) · channel
  providers · compliance/throttle (fail-closed dry-run exit) · metrics (funnel + attribution) ·
  bandit (discounted Thompson Sampling).
- Dual-line engine: blast (email via send-gmail.ps1, multi-platform posting) + precision (forum/DM)
  with email + own-server Discord as live transports; Mastodon/Bluesky/Reddit/X/PH/HN as deferred-gaps.
- Acceptance gate E1-E12 (`selftest.py`) — all passing, zero egress.

## Built + tested, pending wire-in
These are implemented as stdlib libraries with their own acceptance tests today, but are NOT yet
wired into the live `run` loop (`orchestrate.run_once` currently drives context-free Thompson
Sampling only). Wiring each in is a self-evolve iteration gated on its signal:
- Contextual bandit (stdlib LinUCB, `ctxbandit.py`) → per-segment optimal arm. `tests/test_ctx_e2c.py`.
- Off-policy evaluator (IPS/SNIPS/Doubly-Robust, `ope.py`) → safe pre-launch policy comparison. `tests/test_ope_e21.py`.
- Deliverability-driven auto-throttle (inbox-placement + mailbox warmup, `deliverability.py`). `tests/test_deliverability_e22.py`.
- Auto-segmentation (RFM + k-means, `segment.py`). `tests/test_segment_e20.py`.
- Sequential A/B with always-valid p-values (mSPRT e-process, `seqtest.py`). `tests/test_seqtest_e19.py`.
- Delayed-conversion reward censoring (`delayed.py`). `tests/test_delayed_e16.py`.

## Planned (external dependencies)
- Mastodon/Bluesky/Reddit/X live providers → flip deferred-gaps to live transports (need real OAuth).
