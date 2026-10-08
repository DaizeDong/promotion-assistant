# L0, Per-product private config repo

The skill is product-agnostic. All copy, audiences, channel policy and secrets live in a **separate
private config repo**, located via `PROMO_CONFIG_DIR` (or `~/.promotion-assistant-config`). Generate the structure with the source initializer. Provider binding is selected-root
`secrets/runtime.env`; [CONFIG.md](../../../CONFIG.md) lists supported keys and recovery rules.

```
<product>-promo-config/
  product.json            # profile + global send_mode gate (dry_run|live)
  registry.json           # one row per channel (slug/platform/transport/warmup_state/...)
  channels/<slug>/policy.json   # day/hour/week caps, min/max gap, warmup_curve, backoff(AIMD)
  copy/<campaign>.json    # arms: {id, channel, segment, hook, body, cta, utm, status}
  audiences.json          # segment definitions
  compliance/consent-ledger.jsonl   # versioned PRIVATE lawful-basis records
  metrics/                # versioned PRIVATE events, previews, suppression and runtime state
  metrics/runs/<id>.json   # versioned PRIVATE frozen intent and per-item receipts
  secrets/                # PRIVATE versioned <slug>.env credentials and recovery docs
  secrets/runtime.env    # provider resource mapping, never loaded as shell code
  runbooks/               # new-machine.md, live-authorize.md, ban-recovery.md
```

Key fields the engine reads (`scripts/config.py`):
- `product.json.send_mode`, the global dry-run gate (default `dry_run`).
- `product.json.aff_base`, conversion anchor; per-channel ref code = channel-level attribution.
- `product.json.banned_claims` / `compliance.physical_address` / `compliance.unsubscribe_url`.
- `registry.json.channels[].{slug,platform,transport,account_handle,warmup_state}`.
- Owned Mastodon/Bluesky channels also require `audience_mode: "owned_broadcast"` and an
  account-specific `destination`; both identity fields are frozen with the reviewed run.
  Mastodon binds the configured instance, authenticated account and returned post account.
  Bluesky binds the configured handle, authenticated session and returned record repository.
  See [the identity contract](../../../CONFIG.md#review-delivery-and-recovery) for accepted formats.
- `channels/<slug>/policy.json`, throttle policy (hot-swappable, never hardcoded in the skill).

`copy`/`audiences` load as `.json`; `.yaml` is also accepted when PyYAML is installed (the loader
falls back to a `.json` sibling otherwise, so the engine has zero hard third-party deps).
