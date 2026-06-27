# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [0.1.1] - 2026-06-27
### Changed
- **Discord egress unified through Agent Center relay**: pushes now prefer schedule-reminder's
  `relay.py send --stream promotion` (per-stream identity in the Agent Center server) when the base
  is installed, and **fall back to the Big Brother relay (send.py) when it is not** — fully
  pluggable, no behaviour change when the base is absent. Existing env/arg overrides still win.

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
