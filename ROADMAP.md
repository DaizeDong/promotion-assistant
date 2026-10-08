# Roadmap

Current: **v0.1.3**

## Current main

The declared release remains v0.1.3. [Unreleased changes](CHANGELOG.md#unreleased) record the
later durable run/resume protocol, reviewed email contract, owned-account adapters and private
storage requirements. Synthetic checks do not establish live publication.

Current main binds provider resources from the selected companion, checks required schema/name/channel fields before READY, and declares durable scheduling retries plus staging. These are local contracts; live integration acceptance remains separate.

## v0.1.3
- Discord own-server live transport, previously a deferred gap: `DiscordOwnServerProvider.publish`
  posts one announce message via the Discord REST API in live mode. Credentials come from the
  environment, never the repo, and the two-switch fail-closed gate is unchanged. A 429 maps to
  `throttled` so the caller's AIMD reacts to a real rate limit. Guarded by
  `tests/test_discord_live.py` (7 cases, network mocked).

## v0.1.2
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
- Acceptance gate E1-E12 (`selftest.py`), all passing, zero egress.

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

## External prerequisites and deferred work
- Mastodon and Bluesky owned-account adapters are implemented. Live acceptance still requires
  configured account credentials, per-channel authorization and confirmed provider receipts;
  local adapter tests do not establish successful real publication.
- X automated transport remains deferred. Reddit, JanitorAI-card, Product Hunt and Hacker News
  use implemented manual preparation paths; a human publishes their output.
