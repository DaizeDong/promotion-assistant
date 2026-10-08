# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [Unreleased]

### Storage review threshold
- Set a 64 MiB companion working-data review threshold. Required observations and
  recovery state stay protected when the threshold is exceeded.

### Fixed
- Bind provider resources to selected-root runtime.env, replace the unsupported companion apply bridge with local doctor validation, and reject incomplete schemas before READY.
- Authorize source-owned runtime writes and declare scheduling receipts, locks and staging with dependency-based recovery rules.
- Declare retained legacy consent and policy inputs without treating them as
  active sending permission; distinguish them from superseded documentation.

### Added
- Owned-account Mastodon and Bluesky adapters with identity checks and matching provider receipts; registered manual surfaces retain preparation workflows.
- Durable reviewed runs with per-destination payloads, delivery state and resume behavior.

### Changed
- Declare the selected companion apply and credential-capture helpers, and mark the superseded MCP verifier as an exact retirement candidate.
- Email requires the complete `reviewed-email-v1` helper request and receipt contract; a legacy helper or message ID alone is insufficient.
- Verify a separate PRIVATE companion with committed history through the pinned Guards API and its current visibility receipt.
- Credit linked observations using durable identities and receipts, preserving prior learning when migrating legacy state.
- Clarify the tradeoffs behind private configuration, reviewed dispatch and evidence-based feedback.

### Fixed
- Align the engine package version with the existing 0.1.3 plugin and documentation declarations.

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
