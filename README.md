# promotion-assistant

Plan product promotion across channels, review each destination, and track funnel feedback with a Thompson-Sampling bandit. Dispatch defaults to dry-run.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.3-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## Design Philosophy

Promotion policy changes with the product and channel, while the funnel, selection rule and
dispatch checks can remain stable. The tool therefore keeps reusable orchestration in the public
repository and product copy, audiences and operational records in a PRIVATE companion. This adds
configuration work, but lets a channel policy change without embedding a real campaign in the tool.

Every destination needs a complete reviewed payload, consent and suppression checks, and explicit
channel authorization before live dispatch. Dry runs preserve previews and simulated events for
review. A simulation cannot prove delivery, and an uncertain provider response must be reconciled
before retrying. These restrictions trade unattended convenience for control over irreversible outreach.

The bandit uses recorded feedback, so event identity and attribution matter as much as the selection
formula. Durable run and observation receipts let retries reuse the same decision without knowingly
crediting the same observation twice. Synthetic checks can verify this bookkeeping; account setup,
provider acceptance and actual conversion remain separate evidence.

[Read the full design philosophy](PHILOSOPHY.md).

## Scope

The orchestrator supports promotion of shipped products through bulk email, platform posts,
forum replies and direct-message preparation. It includes account activity planning, a six-layer
conversion funnel and a Thompson-Sampling bandit for selecting tactics from recorded feedback.
Product copy, audiences and credentials belong in a separate PRIVATE companion.

Scheduling uses `schedule-reminder`; market and competitor research uses `market-intel`.
Builds and tests run without sending to real audiences. Platform terms and the supported
channel requirements continue to apply to authorized live activity.

## Install

```
/plugin install github:DaizeDong/promotion-assistant
```

Or clone manually:

```bash
git clone --recurse-submodules https://github.com/DaizeDong/promotion-assistant.git ~/.claude/plugins/promotion-assistant
cd ~/.claude/plugins/promotion-assistant
```

Use Python 3.11 or newer and Git. JSON configuration needs no extra Python package;
YAML also needs PyYAML. Configure the separate PRIVATE companion below before running the
quick start. Runtime storage verifies the local PRIVATE receipt at
`~/.pii-guard/visibility.json`; it does not call `gh` or refresh missing/stale evidence.
Follow the [companion contract](guards/COMPANION.md#verifying-a-companion) for that proof.

Planning requires a compatible `schedule-reminder` installation. Follow
[integration setup](skills/promotion-assistant/reference/integration.md#schedule-reminder-the-only-scheduling-surface)
to select `PROMO_REMINDER_PY`, verify `creation-preflight` and `ensure`, and initialize the store
using the current runtime's Python. An older `add`-only helper is incompatible.

## Quick start

```bash
cd skills/promotion-assistant
python scripts/selftest.py                          # E1-E12 acceptance gate (no egress)
python scripts/cli.py doctor                          # health / compliance / dry-run status
python scripts/cli.py plan --campaign <C>             # content calendar -> schedule-reminder
python scripts/cli.py run  --campaign <C> --once      # gated dispatch (DRY-RUN by default)
python scripts/cli.py report --funnel                 # six-layer funnel
```

## Config

Create a separate committed PRIVATE companion, then point `PROMO_CONFIG_DIR` at it.
[CONFIG.md](CONFIG.md) owns the complete discovery order, schema, credential keys and switching
rules; [DATA.md](DATA.md) owns retention and recovery.

Run from the repository root:

```bash
python skills/promotion-assistant/scripts/init_config.py --out <private-companion>
python skills/promotion-assistant/scripts/verify_config.py --config-dir <private-companion>
```

The skeleton needs product/registry `schema_version: 1`, product name and channel slug/platform,
plus PRIVATE fetch/push proof and the selected provider resources. It is not ready immediately
after initialization. The initializer still emits obsolete credential exclusions; apply the
[documented companion-only correction](CONFIG.md#first-time-setup-e3) before versioning required
`secrets/*.env` files. Provider mappings come from the selected `secrets/runtime.env` as `KEY=VALUE`.

Clear stale higher-priority selectors before switching and rerun doctor. `init` checks an existing
configuration, with global `--config` placed before the subcommand; `apply` performs the local
doctor check without executing historical companion helpers or changing `~/.claude.json`.
READY covers schema, PRIVATE and local-resource checks. The separate process-local
`PROMO_LIVE_AUTHORIZED_<CHANNEL>` gate and provider receipts determine authorized live delivery;
email also requires a `reviewed-email-v1` helper.

## How to invoke

Trigger words: promote / promotion / marketing automation / outreach / bulk email / social posting /
growth / funnel / multi-account. (Or run the CLI directly.)

## Example output

`run --once` returns `run_id`, `status`, `counts` and the full reviewed `items`. Each destination
includes its complete payload, consent/suppression disposition, receipt and retryability. Dry runs
write private previews and events; their status is `simulated`, and no provider effect occurs.
See [CONFIG.md](CONFIG.md) for PRIVATE storage and run/resume behavior.

## Limitations

- Going live is **per-channel, deliberate, and out of scope for build/test** (dry-run only).
- Email, own-server Discord, Mastodon and Bluesky have automated adapters. Registered manual
  surfaces use `prep`; X and unknown platforms remain deferred. All automated delivery requires
  per-channel authorization and a matching remote receipt. `channels list --json` distinguishes
  implementation, local configuration and live proof; synthetic tests never count as live proof.
- Platform terms and account restrictions still apply. The throttle/humanize layer is intended
  to limit activity risk; this does not establish platform approval or a measured reduction in bans.

## Languages

English (`README.md`, authoritative) · 中文 (`README_CN.md`)

## Roadmap · Contributing · License

See [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE) (MIT).
