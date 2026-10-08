# promotion-assistant

Multi-channel product promotion that quantifies its own funnel and self-tunes, dry-run by default, compliance fail-closed.

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

## What it is (and isn't)

**Is:** a thin, product-agnostic orchestrator for promoting a *shipped* product across many channels
with quantified feedback, blast (bulk email + multi-platform posting) and precision (forum replies +
DMs), daily multi-account upkeep, a six-layer conversion funnel, and a Thompson-Sampling bandit that
self-tunes tactics. All product copy/audiences/credentials live in a **separate private config repo**.

**Isn't:** a spam cannon, a scheduling engine (it delegates to `schedule-reminder`), or a market-
research tool (that's `market-intel`). It will not bypass platform ToS or send to real audiences
during build/test.

## Install

```
/plugin install github:DaizeDong/promotion-assistant
```

Or clone manually:

```bash
git clone --recurse-submodules https://github.com/DaizeDong/promotion-assistant.git ~/.claude/plugins/promotion-assistant
cd ~/.claude/plugins/promotion-assistant
```

Then create a separate committed Git companion with PRIVATE fetch and push destinations on every
remote (fork the `companion config kit` template with versioned private credentials), and point the skill at it: `export PROMO_CONFIG_DIR=~/CodesClaude/<product>-promo-config`.

Use Python 3.11 or newer, Git, and a fresh PRIVATE visibility receipt at
`~/.pii-guard/visibility.json`. The pinned Guards API checks that local receipt and the actual Git
configuration; runtime storage checks do not call `gh` or refresh missing/stale evidence. See the
[companion contract](guards/COMPANION.md#verifying-a-companion) before initializing or refreshing
the receipt. JSON configuration needs no extra Python package; YAML configuration also needs PyYAML.
Run the commands below from the cloned repository. For reminders, set `PROMO_REMINDER_PY` to the
installed base's `reminder.py`, then check `python "$PROMO_REMINDER_PY" ensure --help` and initialize
its local store with `python "$PROMO_REMINDER_PY" init`. The bridge requires `creation-preflight`
and `ensure`; a legacy `add`-only helper is incompatible. Managed installations should use their
current runtime's Python and reminder path. [Integration setup](skills/promotion-assistant/reference/integration.md).

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

Product settings and runtime DATA belong in a separate PRIVATE companion with committed history.
See [CONFIG.md](CONFIG.md) for schema, credential keys and recovery. Selection order is explicit
`--config`, `PROMO_CONFIG_DIR`, `PROMOTION_ASSISTANT_CONFIG`, `PROMOTION_ASSISTANT_CONFIG_DIR`,
`~/.promotion-assistant-config`, then `~/.config/promotion-assistant-config`. Invalid selections fail.

Run from the repository root:

```bash
python skills/promotion-assistant/scripts/init_config.py --out <private-companion>
python skills/promotion-assistant/scripts/verify_config.py --config-dir <private-companion>
```

Fill product/registry `schema_version: 1`, product name and channel slug/platform; commit the
companion and establish PRIVATE proof. The generated skeleton is not ready. Provider resources
and credentials come from the selected `secrets/runtime.env` as `KEY=VALUE`. Dispatch binds that
mapping per call without inheriting another product's ambient credentials or changing global env.
`apply` now performs the local doctor check; it does not run the old companion helper or modify
`~/.claude.json`.

Clear stale higher-priority selectors before switching to B and rerun doctor. Live authorization
remains the separate process-local `PROMO_LIVE_AUTHORIZED_<CHANNEL>` gate. READY establishes
schema, PRIVATE and local-resource checks only; the email helper must implement reviewed-email-v1
and live delivery requires separate verification. Restore credentials through the selected private
backup policy or reauthorize. Real values never belong in the public source.

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
- Platform ToS grey areas cannot be eliminated; the throttle/humanize layer lowers, not removes, ban
  probability.

## Languages

English (`README.md`, authoritative) · 中文 (`README_CN.md`)

## Roadmap · Contributing · License

See [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE) (MIT).
