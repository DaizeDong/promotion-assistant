# Roadmap

Current: **v0.1.3**

## Current main

The declared release remains v0.1.3. [Unreleased changes](CHANGELOG.md#unreleased) record the
later durable run/resume protocol, reviewed email contract, owned-account adapters and private
storage requirements. Synthetic checks do not establish live publication.

Current main binds provider resources from the selected companion, checks required
schema/name/channel fields before READY, and retains durable scheduling requests and staging.
Email uses the reviewed helper contract. Discord own-server, Mastodon and Bluesky adapters
require the existing live gates and verified provider receipts. Compliance handles normalized
claim text, suppression aliases and email-like payloads even when transport labels differ.
These are local contracts; live acceptance remains separate.

Version-specific behavior and test counts are retained in [CHANGELOG.md](CHANGELOG.md).
The initializer's credential exclusions still require the adjustment documented in
[CONFIG.md](CONFIG.md#first-time-setup-e3) before the companion meets the current storage contract.

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
