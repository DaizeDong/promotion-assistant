# L0, Per-product config repo (Mode B)

The skill is product-agnostic. All copy, audiences, channel policy and secrets live in a **separate
private config repo**, located via `PROMO_CONFIG_DIR` (or `~/.promotion-assistant-config`). Fork the
structure from `companion config kit`'s template; secrets are **always gitignored** (Mode B, promo
OAuth/SMTP creds are high blast-radius and auto-revoked, so the market-intel "Mode A" rationale does
not apply).

```
<product>-promo-config/
  product.json            # profile + global send_mode gate (dry_run|sim|test_account|live)
  registry.json           # one row per channel (slug/platform/transport/warmup_state/...)
  channels/<slug>/policy.json   # day/hour/week caps, min/max gap, warmup_curve, backoff(AIMD)
  copy/<campaign>.json    # arms: {id, channel, segment, hook, body, cta, utm, status}
  audiences.json          # segment definitions
  compliance/consent-ledger.jsonl   # [gitignored] EU lawful-basis records
  metrics/                # [gitignored] events.jsonl, bandit-state.json, suppression.csv, dry-run.jsonl, throttle-state.json
  secrets/                # [gitignored] <slug>.env (only *.template + README committed)
  scripts/apply.py        # secrets -> active ~/.claude.json (never echoes values); forked from companion config kit
  runbooks/               # new-machine.md, live-authorize.md, ban-recovery.md
```

Key fields the engine reads (`scripts/config.py`):
- `product.json.send_mode`, the global dry-run gate (default `dry_run`).
- `product.json.aff_base`, conversion anchor; per-channel ref code = channel-level attribution.
- `product.json.banned_claims` / `compliance.physical_address` / `compliance.unsubscribe_url`.
- `registry.json.channels[].{slug,platform,transport,account_handle,warmup_state}`.
- `channels/<slug>/policy.json`, throttle policy (hot-swappable, never hardcoded in the skill).

`copy`/`audiences` load as `.json`; `.yaml` is also accepted when PyYAML is installed (the loader
falls back to a `.json` sibling otherwise, so the engine has zero hard third-party deps).
