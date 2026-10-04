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
remote (fork the `companion config kit` template, Mode B secrets), and point the skill at it: `export PROMO_CONFIG_DIR=~/CodesClaude/<product>-promo-config`.

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

`promotion-assistant` is **config-bearing**, it reads all product copy, audiences, per-channel
policy and credentials from a **separate, private** companion config repo. Full contract:
[CONFIG.md](CONFIG.md) (schema reference: [reference/config-schema.md](skills/promotion-assistant/reference/config-schema.md)).

- **Mount (discovery order):** `$PROMO_CONFIG_DIR` (primary) → `$PROMOTION_ASSISTANT_CONFIG` →
  `$PROMOTION_ASSISTANT_CONFIG_DIR` → `~/.promotion-assistant-config/` →
  `~/.config/promotion-assistant-config/`. An explicit path or highest nonempty environment selection is authoritative and must validate.
  Home directories apply only without an explicit/environment selection; a bad selection never falls through.
- **First time:**
  ```bash
  cd skills/promotion-assistant
  python scripts/init_config.py        # stamp a conformant skeleton (deterministic)
  export PROMO_CONFIG_DIR=~/.promotion-assistant-config   # or pass --out <dir> to init
  # Fill product/channel configuration and commit the separate PRIVATE companion first.
  python scripts/verify_config.py       # reports ready only after those prerequisites exist
  python scripts/cli.py doctor --json  # runtime boundary and local channel setup
  ```
- **Explicit selection:** `python scripts/cli.py --config /path/to/private-companion init` checks an
  existing config. Put `--config` before the subcommand; use `init_config.py --out` to create a skeleton.
- **Email setup:** the configured helper must implement the complete
  [reviewed-email-v1 contract](skills/promotion-assistant/reference/email-helper-contract.md).
  An installed legacy helper or a message ID alone does not prove sender/content or make email ready.
- **Switch configs (hot-swap):** point the env var at another config dir, configs are
  self-contained, no other change: `export PROMO_CONFIG_DIR=~/configs/product-a` ↔ `~/configs/product-b`.
- **Secrets:** Mode B, `secrets/*` is gitignored and never enters git; back up out-of-band.
  Credentials bridge into the active config via the config repo's forked `scripts/apply.py`.

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
