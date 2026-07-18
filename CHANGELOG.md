# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [0.1.3] - 2026-07-18
### Added
- **Discord own-server live transport (was a deferred-gap).** `DiscordOwnServerProvider.publish`
  now, in live mode, posts one announce message to a configured own-server channel via the Discord
  REST API (stdlib urllib, no new dependency). Credentials come from the channel secret in the
  environment (`PROMO_DISCORD_BOT_TOKEN` + `PROMO_DISCORD_ANNOUNCE_CHANNEL_ID`), never the repo, and
  from a dedicated promo bot separate from the alert relay. A real 200 maps to `sent` (with the
  message id), a 429 to `throttled` so the caller's AIMD reacts to a real rate-limit, other HTTP
  codes to `error`. The two-switch fail-closed gate is unchanged: reaching this path already means
  `send_mode=live` AND `PROMO_LIVE_AUTHORIZED_DISCORD_OWN` both passed. `tests/test_discord_live.py`
  (7 cases, network mocked) covers not-live, missing/invalid creds, success, empty body, 429, 403.

## [0.1.2] - 2026-07-06
### Security
- **Compliance-matcher evasion hardening.** Banned-claim/body matching now NFKC-normalizes, strips
  zero-width/format chars, and folds common Cyrillic/Greek homoglyphs; suppression matching folds
  `+tag` aliases + case/unicode; CAN-SPAM checks fire when a payload is *email-like* (recipient is an
  email or channel says so), not only when `transport=="smtp"`, so a mislabeled transport can no
  longer skip CAN-SPAM. An adversarial review had bypassed all four; guarded by
  `tests/test_compliance_hardening.py` (7 cases). `check()` API unchanged.
### Fixed
- CLI: every subcommand now surfaces a friendly "no usable config" message instead of an uncaught
  `ConfigError` traceback when `$PROMO_CONFIG_DIR` is unset.
### Added
- `CONTRIBUTING.md` (Skill Repo Spec completeness, was the sole missing required file).
- ROADMAP now separates "built + tested, pending wire-in" (contextual bandit / OPE / deliverability /
  segmentation / sequential-A-B / delayed-reward, implemented libraries not yet in the live `run`
  loop) from externally-blocked "planned" (live OAuth providers), so the shelf-ware status is explicit.

## [0.1.1] - 2026-06-27
### Changed
- **Discord egress unified through Agent Center relay**: pushes now prefer schedule-reminder's
  `relay.py send --stream promotion` (per-stream identity in the Agent Center server) when the base
  is installed, and **fall back to the Big Brother relay (send.py) when it is not**, fully
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
