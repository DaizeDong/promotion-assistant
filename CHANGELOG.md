# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [0.1.0] - 2026-06-25
### Added
- Initial release. Product-agnostic multi-channel promotion skill (six layers, two repos).
- Engine: config locator, append-only event store, compliance gate (CAN-SPAM/GDPR/suppression),
  token-bucket+AIMD throttle with warmup state machine, discounted Thompson-Sampling bandit,
  six-layer funnel + attribution + reward, single fail-closed dry-run dispatch exit, anti-fingerprint
  (spintax + similarity), schedule-reminder bridge, Discord-relay alerts, CLI, and the E1-E12
  acceptance gate (`selftest.py`, all passing).
- Channels: email (send-gmail.ps1) + own-server Discord as live transports; Mastodon/Bluesky/Reddit/
  X/Product Hunt/Hacker News registered as explicit deferred-gaps.
