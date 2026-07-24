# Participation copilot (`participate`)

A compliant, human-in-the-loop community-participation module. It exists for communities that
shadowban newcomers (the canonical case: posting in a subreddit's weekly megathread), where the
only path that both works and stays within the rules is a *real* account's *genuine* participation.
The copilot augments that participation; it never fabricates it.

## Governing invariant (do not weaken)

> A human is always the publisher and endorser. This module augments a real person's genuine
> participation, but never fakes participation and never evades a platform's safety systems.

Concretely this forbids, by construction: autonomous posting/voting (there is **no egress code
path** — every "publish" returns a draft), fabricated "I use product X" personas, karma farming,
multi-account operation, and anti-detection machinery (fingerprint browsers, proxies, warmup curves
whose only purpose is to survive behavioral classifiers). If participation is genuine — the real
person, honest content, expertise they actually hold — there is nothing to evade.

Synthesized from a survey of six participation/warmup/discovery skills: it borrows their *structure*
(opportunity scoring, typed reply frameworks, give-before-ask ledger, prepared→record attribution)
and discards their *intent* where that intent was detection-evasion or undisclosed autonomous
posting. It extends `ManualPrepProvider`'s compliance-by-construction (LIVE_TRANSPORT=False) from
"place copy on a hostile surface" to "help a real person participate genuinely."

## Pipeline (5 stages, human in the loop at every one)

| Stage | What it does | Egress |
|---|---|---|
| 0 auth | official Reddit OAuth (a script app, YOUR account, documented read endpoints + rate limits); degrades to `site:reddit.com` search via your tooling (tavily/brightdata). Never scrapes. | read-only |
| 1 discover | scan a sub's new posts → 8-field extraction → 5-dim score → 4-label ladder; surface a ranked queue | read-only |
| 2 draft | for `immediate` threads, `llmcall` writes a genuine-help reply grounded in the person's real expertise; over-claim guard checks it | **none (draft-only)** |
| 3 readiness | give-before-ask (9:1) ledger + account standing + verifiable graduation criteria + courtesy pacing | none |
| 4 attribution | after the human posts by hand, `record` writes a `sent` event (actuator=human) tying their real permalink to the draft | none |

## Algorithms

**Opportunity score** (`score_opportunity`): five dimensions —
`expertise_fit` (0.40 weight, load-bearing), `need_intensity` (0.20, intent-weighted:
recommendation/troubleshooting=1.0), `freshness` (0.15, `1/(1+age_h/24)`), `unanswered`
(0.15, `1/(1+num_comments/5)`), `community_fit` (0.10). A **red-flag phrase** (rant, drama,
"no self-promo", politics, …) is a HARD veto → `skip`. Labels: `immediate` requires BOTH
`total≥0.62` AND `expertise_fit≥0.5` (never steer the person to answer outside their knowledge);
else `monitor`/`build`/`skip`. Default: *when in doubt, skip.*

**Draft prompt** (`build_draft_prompt`): picks a typed reply framework by intent
(recommendation/troubleshooting/comparison/workflow), grounds it in the person's declared expertise.
Warming (not graduated) → **pure help, zero product mention, zero link**. Graduated → 90/10, answer
first, product mentioned last *only if it genuinely fits*, with a mandatory `Full disclosure: I work
on it` line and soft phrasing. The generated draft is passed through `compliance.check` (over-claim
floor).

**Readiness** (`readiness`): graduation is *proposed with evidence*, never self-declared. Criteria:
account age ≥ N days, karma ≥ N, in-community accepted non-promo contributions ≥ N (global karma in
a sub you've never engaged doesn't count), give:ask ratio holds 9:1 over the window, zero mod
strikes. All account numbers are three-valued-labeled (Measured/User-provided/Estimated) by the
caller.

**Courtesy pacing** (`pacing_ok`): per-day and per-sub caps + a post-removal 7-day per-sub circuit
breaker. This is etiquette (don't spam, don't over-post), explicitly *not* classifier evasion — no
inter-post timing jitter tuned to survive detection.

## Files

- `scripts/participation.py` — pure functions (scoring, red-flag veto, draft prompt, ledger,
  readiness, pacing). No network.
- `scripts/reddit_read.py` — read-only access: `site:reddit.com` query construction, official OAuth
  token + `fetch_new`, listing→schema parsing. Network calls are injectable (testable).
- `orchestrate.record_participation(url)` — attribution loop (a `drafted` event → the human's real
  `sent` permalink).

## Setup

Register a Reddit "script" app at reddit.com/prefs/apps; put credentials in a **gitignored**
`secrets/reddit.env`: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`,
`REDDIT_PASSWORD`, `REDDIT_USER_AGENT`. Without it, `discover` degrades to emitting search queries
you run through your own tooling. The copilot never stores or echoes secrets.
