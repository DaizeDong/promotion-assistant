# Contributing to promotion-assistant

A **public, product-agnostic** promotion engine — all copy and credentials live in a separate
**private per-product config** repo, never here. Compliance is engineering, not goodwill: the
fail-closed gates are non-negotiable. Read [`PHILOSOPHY.md`](PHILOSOPHY.md) before changing anything.

## Golden rules

1. **Dry-run is the default.** Every real send/post/DM goes through the single `dispatch()` exit,
   which fail-closed requires `product.json.send_mode=="live"` **and** env
   `PROMO_LIVE_AUTHORIZED_<CHANNEL>`. Never add a code path that bypasses that exit.
2. **Compliance / throttle gates are fail-closed** — no "warn and send". Matchers must resist
   evasion (unicode / homoglyph / `+tag` alias / mislabeled transport); see
   `tests/test_compliance_hardening.py`. Widen the confusable map / rules, never loosen them.
3. **Evaluation-driven.** Extend the `selftest.py` E1-E12 signals and `tests/` before the
   implementation. The suite must stay green — it is the self-evolve merge gate.
4. **Secrets never enter this repo.** No product copy, no creds. `secrets/*` is Mode B (gitignored)
   in the config repo; this skill must never read, log, or echo a token.
5. **Don't reimplement the base.** Scheduling → the `schedule-reminder` CLI only (never its .db);
   alerts → the Agent Center relay (`relay.py --stream promotion`, Big-Brother fallback).

## Run the suite

```bash
python -m pytest tests/ -q
python skills/promotion-assistant/scripts/selftest.py   # E1-E12 acceptance, zero egress
```

## Conventions

- Stdlib-first; the whole engine runs without third-party deps.
- Everything product-specific is config (`PROMO_CONFIG_DIR`); the skill ships no copy or creds.
- New advanced learning modules land as tested libraries first, then get wired into
  `orchestrate.run_once` in a later iteration (see ROADMAP "Built + tested, pending wire-in").

## Version sync

`plugin.json.version` == README/README_CN Roadmap badge == `ROADMAP.md` "Current:" ==
`CHANGELOG.md` latest entry. Keep all four in lock-step on every bump.

License: MIT (see [LICENSE](LICENSE)).
