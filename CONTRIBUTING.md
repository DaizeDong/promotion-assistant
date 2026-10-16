# Contributing to promotion-assistant

This public engine contains reusable promotion logic. Product copy, credentials and runtime
records belong in a separate PRIVATE companion. Changes must preserve the dispatch checks and
evidence requirements described in [PHILOSOPHY.md](PHILOSOPHY.md).

## Golden rules

1. **Dry-run is the default.** Every real send/post/DM goes through the single `dispatch()` exit,
   which fail-closed requires `product.json.send_mode=="live"` **and** env
   `PROMO_LIVE_AUTHORIZED_<CHANNEL>`. Never add a code path that bypasses that exit.
2. **Compliance / throttle gates are fail-closed**, no "warn and send". Matchers must resist
   evasion (unicode / homoglyph / `+tag` alias / mislabeled transport). Widen the confusable map / rules, never loosen them.
3. **Keep real data private.** Product copy and credentials never enter this public repository.
   `secrets/*.env` files are gitignored projections of an external credential store and are never
   versioned ([CONFIG.md](CONFIG.md#private-credentials-e6)). Adapters may read their selected
   credentials but must not log or echo them.
4. **Don't reimplement the base.** Scheduling → the `schedule-reminder` CLI only (never its .db);
   alerts → the configured relay through [integration.md](skills/promotion-assistant/reference/integration.md).

## Conventions

- Stdlib-first; the whole engine runs without third-party deps.
- Everything product-specific is config (`PROMOTION_ASSISTANT_CONFIG`); the skill ships no copy or creds.
- New advanced learning modules land as libraries first, then get wired into
  `orchestrate.run_once` in a later iteration (see ROADMAP "Built, pending wire-in").

## Version sync

`plugin.json.version` == README/README_CN Roadmap badge == `ROADMAP.md` "Current:" ==
`CHANGELOG.md` latest entry. Keep all four in lock-step on every bump.

License: MIT (see [LICENSE](LICENSE)).
