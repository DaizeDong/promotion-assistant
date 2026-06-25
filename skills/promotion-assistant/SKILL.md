---
name: promotion-assistant
description: Automate multi-channel product promotion (email/posts/forum/DM), track conversion funnel, self-tune via feedback.
---

# promotion-assistant

> Governing principle (full text in the repo's `PHILOSOPHY.md`): **methodology is constant, signals
> adapt; compliance is engineering not goodwill; dry-run is the default, not an option.** The channel
> matrix, six-layer funnel, bandit and compliance gate are fixed; every platform limit, audience and
> piece of copy lives in per-product config. No outbound action ever leaves the machine unless the
> product is explicitly set live AND that channel is individually authorized.

## When to use / when to stop

- **Use** when promoting a *shipped* product across many channels with quantified feedback: bulk
  email + multi-platform posting (覆盖式) and forum replies + DMs (精准式), with daily multi-account
  upkeep, funnel attribution, and self-evolving tactics.
- **Stop / route elsewhere:** a one-off single post → just post it. Pure market/competitor research
  → `market-intel`. Scheduling/reminders themselves → this skill *delegates* to the
  `schedule-reminder` base (it does not reimplement scheduling).

## Architecture (six layers, two repos — load `reference/<shard>.md` on demand)

| layer | job | shard |
|---|---|---|
| L0 config/creds | locate per-product config (`PROMO_CONFIG_DIR`, Mode B secrets) | `reference/config-schema.md` |
| L1 orchestration | plan→`schedule-reminder`; run `--once/--daemon`; alerts→Discord relay | `reference/integration.md` |
| L2 channels | one provider/platform (`publish/engage/dm/read_metrics`) | `reference/channels.md` |
| L3 compliance/throttle | fail-closed gate + token-bucket+AIMD + warmup + the dry-run exit | `reference/compliance.md` |
| L4 metrics | six-layer funnel + UTM/ref attribution + shadowban probe | `reference/metrics.md` |
| L5 decision | Thompson-Sampling bandit (discounted, non-stationary) | `reference/bandit.md` |

Two repos: this **public, product-agnostic** skill (no copy, no creds) + one **private per-product
config** repo. Everything product-specific is config.

## Three modules (one job, ≤3)

1. **覆盖式 (blast)** — bulk email (deliverability = pool + warmup + SPF/DKIM/DMARC, click/reply/conv
   not opens) and multi-platform posting graded by ban-risk (own Discord/Mastodon/Bluesky first).
2. **精准式 (precision)** — forum replies + DMs on an *activity-DNA behavioral baseline* (relative to
   the account's own history, not absolute volume); Discord/Telegram only via official bot + own
   channels (selfbot/stranger auto-DM = instant ban).
3. **指标闭环 (metrics loop)** — six-layer funnel + attribution feed a reward (ban/spam/unsub are
   STRONG NEGATIVE), the bandit picks the next arm; the loop is what "self-tune via feedback" means.

## CLI

```
python scripts/cli.py init                       # locate/verify the product config repo
python scripts/cli.py channels list              # registered channels + which have a live transport
python scripts/cli.py apply                       # secrets -> active config (delegates; never echoes)
python scripts/cli.py plan --campaign <C>         # content calendar -> schedule-reminder
python scripts/cli.py run  --campaign <C> --once  # gated dispatch (DRY-RUN by default)
python scripts/cli.py authorize --channel <X>     # the exact per-channel live-unlock steps
python scripts/cli.py report --funnel | --bandit  # funnel + arm convergence
python scripts/cli.py doctor                       # health / compliance / dry-run self-check
```

## Hard rules (never violate)

1. **dry-run is the default.** Every real send/post/DM goes through the single `dispatch()` exit,
   which fail-closed asserts `product.json.send_mode=="live"` **and** env
   `PROMO_LIVE_AUTHORIZED_<CHANNEL>`. Missing either → it simulates (full pipeline, `simulated`
   event + `dry-run.jsonl`, zero egress). Build/test never sends to real audiences.
2. **Compliance fail-closed.** No physical address / no unsubscribe / suppressed recipient / EU
   recipient without a lawful basis → the send is rejected, not warned. CAN-SPAM + GDPR are gates.
3. **Throttle + humanize.** token-bucket + AIMD (429 → halve + cooldown), warmup state machine (no
   level-skipping), lognormal jitter, per-account variants + content-hash dedup. Random delay alone
   is NOT safety.
4. **Secrets = Mode B.** Promo OAuth/SMTP creds are high blast-radius + auto-revoked → `secrets/*`
   is always gitignored in the config repo; never commit copy or creds into this skill.
5. **Don't reimplement the base.** Scheduling → `schedule-reminder` CLI only (never its .db/SQL);
   alerts → the existing Discord relay; email → the machine's `send-gmail.ps1` link.
6. **Failure = explicit gap.** A channel with no compliant automated transport is registered as a
   `deferred-gap`, never silently dropped.

## Acceptance / regression

`python scripts/selftest.py` runs E1-E12 (metrics exactness, bandit convergence + drift recovery,
throttle limits, compliance fail-closed, attribution, dry-run zero-egress, propensity completeness,
event schema, anti-fingerprint, delayed-conversion censoring, idempotency). All must pass before any
behavior change ships — this is the self-evolve gate.

## Progressive loading

This `SKILL.md` is the only always-loaded file. Read `reference/<shard>.md` on demand, one at a time.
