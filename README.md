# promotion-assistant

Multi-channel product promotion that quantifies its own funnel and self-tunes — dry-run by default, compliance fail-closed.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ Read this first — the design philosophy

**Methodology is constant, signals adapt; compliance is engineering not goodwill; dry-run is the
default, not an option.** The channel matrix, six-layer funnel, bandit and compliance gate are fixed
method; every platform limit, audience and piece of copy lives in a per-product config repo. No
outbound action ever leaves the machine unless the product is explicitly set live **and** that
channel is individually authorized — the safe state is the one you fall into by doing nothing.

📜 **[Read the full design philosophy -> PHILOSOPHY.md](PHILOSOPHY.md)**

---

## What it is (and isn't)

**Is:** a thin, product-agnostic orchestrator for promoting a *shipped* product across many channels
with quantified feedback — blast (bulk email + multi-platform posting) and precision (forum replies +
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
git clone https://github.com/DaizeDong/promotion-assistant.git ~/.claude/plugins/promotion-assistant
```

Then create a per-product config repo (fork the `companion config kit` template, Mode B secrets) and
point the skill at it: `export PROMO_CONFIG_DIR=~/CodesSelf/<product>-promo-config`.

## Quick start

```bash
cd skills/promotion-assistant
python scripts/selftest.py                          # E1-E12 acceptance gate (no egress)
python scripts/cli.py doctor                          # health / compliance / dry-run status
python scripts/cli.py plan --campaign <C>             # content calendar -> schedule-reminder
python scripts/cli.py run  --campaign <C> --once      # gated dispatch (DRY-RUN by default)
python scripts/cli.py report --funnel                 # six-layer funnel
```

## How to invoke

Trigger words: promote / promotion / marketing automation / outreach / bulk email / social posting /
growth / funnel / multi-account. (Or run the CLI directly.)

## Example output

`run --once` in dry-run prints e.g. `{"status":"ok","dispatch":{"status":"simulated",...},"arm":"armA"}`
and appends a `simulated` event + a `dry-run.jsonl` line — zero network egress until per-channel live
authorization.

## Limitations

- Going live is **per-channel, deliberate, and out of scope for build/test** (dry-run only).
- Several channels ship as **deferred-gaps** (Mastodon/Bluesky/Reddit/X/PH/HN) — registered, not
  silently dropped; live transports today are email (via `send-gmail.ps1`) and own-server Discord,
  both still behind per-channel authorize.
- Platform ToS grey areas cannot be eliminated; the throttle/humanize layer lowers, not removes, ban
  probability.

## Languages

English (`README.md`, authoritative) · 中文 (`README_CN.md`)

## Roadmap · Contributing · License

See [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE) (MIT).
