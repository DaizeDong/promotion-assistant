# promotion-assistant, Config

`promotion-assistant` is **config-bearing**. The skill itself is product-agnostic: all product copy,
audiences, per-channel policy, runtime metrics and credentials live in a **separate, private
companion config repo** (Mode B). This file is the authoritative config contract (config-spec E1);
the in-engine field reference is [`skills/promotion-assistant/reference/config-schema.md`](skills/promotion-assistant/reference/config-schema.md).

## Discovery convention (how the skill finds your config), E2

`scripts/config.py` resolves the config dir in this order; the first that exists wins:

1. `$PROMO_CONFIG_DIR`, **primary**, recommended (the canonical name this skill uses).
2. `$PROMOTION_ASSISTANT_CONFIG`, config-spec canonical alias (accepted).
3. `$PROMOTION_ASSISTANT_CONFIG_DIR`, config-spec canonical alias (accepted).
4. `~/.promotion-assistant-config/`, dotfile-in-home fallback.
5. `~/.config/promotion-assistant-config/`, XDG-style fallback (Linux/macOS).

If none resolves, the engine fails closed with a clear message (it never invents a default product).

## Schema (E1)

```
<product>-promo-config/
  product.json                  # profile + the GLOBAL send gate
  registry.json                 # one row per channel
  channels/<slug>/policy.json   # throttle policy (hot-swappable; never hardcoded in the skill)
  copy/<campaign>.json|.yaml    # campaign arms
  audiences.json|.yaml          # segment definitions
  compliance/consent-ledger.jsonl   # [gitignored] lawful-basis records
  metrics/                      # [gitignored] events.jsonl, bandit-state.json, suppression.csv, dry-run.jsonl, throttle-state.json
  secrets/<slug>.env            # [gitignored] real creds; only *.env.template + README committed
  scripts/apply.py              # secrets -> active ~/.claude.json (forked from companion config kit; never echoes values)
  runbooks/                     # new-machine.md, live-authorize.md, ban-recovery.md
```

**`product.json`**

| field | type | required | notes |
|---|---|---|---|
| `schema_version` | int | yes | config contract version (init stamps `1`); lets the engine migrate older configs |
| `name` | str | yes | product name |
| `send_mode` | enum `dry_run`\|`sim`\|`test_account`\|`live` | no (default `dry_run`) | **global send gate**; live also needs `PROMO_LIVE_AUTHORIZED_<CHANNEL>` |
| `aff_base` | str | no | conversion anchor; per-channel ref = channel attribution |
| `banned_claims` | list[str] | no | compliance lint blocklist |
| `compliance.physical_address` | str | no (recommended) | CAN-SPAM footer |
| `compliance.unsubscribe_url` | str | no (recommended) | CAN-SPAM footer |

**`registry.json`** carries its own `schema_version` (int, **required**; init stamps `1`) alongside
**`channels[]`** (each row): `slug` (str, **required**), `platform` (str),
`transport` (str), `account_handle` (str), `warmup_state` (str), `live_authorize_token` (str,
optional, when set, the live second factor is strengthened to a constant-time equality check).

**`channels/<slug>/policy.json`**: `day`/`hour`/`week` caps, `min`/`max` gap, `warmup_curve`,
`backoff` (AIMD). Hot-swappable, loaded at runtime, never baked into the skill.

**`copy`/`audiences`** load as `.json`; `.yaml` is accepted when PyYAML is installed, otherwise the
loader falls back to a `.json` sibling (zero hard third-party deps).

## First-time setup (E3), succeeds on the first try

```bash
cd skills/promotion-assistant

# 1. Stamp a conformant, empty config skeleton (deterministic — E4):
python scripts/init_config.py             # -> ~/.promotion-assistant-config/  (or pass --out <dir>)

# 2. Point the skill at it (skip if you used the default path):
export PROMO_CONFIG_DIR=~/.promotion-assistant-config

# 3. Fill product.json + registry.json + channels/<slug>/policy.json, add secrets/<slug>.env,
#    fork scripts/apply.py from companion config kit, then confirm it is ready:
python scripts/verify_config.py           # doctor: PASS/FAIL per check, names what is missing
```

`init_config.py` is template-driven and deterministic, re-running it (same `--out`) produces a
byte-identical skeleton, so two operators generate the same structure (E4). It intentionally does
**not** generate `apply.py`: that single mechanism is forked from `companion config kit`, keeping one
source of truth (no conflicting second bridge).

## Switching between configs (hot-swap), E5

A config dir is self-contained (`config.py` reads everything relative to the config root, no
hardcoded paths). Keep as many product configs as you like and switch by repointing the env var ,
no other change:

```bash
export PROMO_CONFIG_DIR=~/configs/product-a     # config A
export PROMO_CONFIG_DIR=~/configs/product-b     # config B — same skill, different product
```

Verify a swap: `python scripts/init_config.py --out ~/configs/product-a` and `--out ~/configs/product-b`,
run `python scripts/verify_config.py --config-dir <each>`, then flip `$PROMO_CONFIG_DIR`, both must
report READY.

## Secrets, Mode B (E6)

The companion config repo is **separate and private**, and `secrets/*` there is **gitignored** ,
promo OAuth/SMTP creds are high blast-radius and auto-revoked, so they never enter git (the
market-intel "Mode A" rationale does not apply). Only `*.env.template` + README are committed; back
real values up out-of-band. Credentials are bridged into the active `~/.claude.json` by the config
repo's own `scripts/apply.py`, which never echoes values. This public skill repo also gitignores
`secrets/`, `*.env`, `metrics/` and `.claude.json` defensively, it must never hold product secrets.
