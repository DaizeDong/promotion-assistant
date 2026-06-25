# L4 — Metrics: funnel, attribution, reward (event sourcing)

`scripts/events.py` is the append-only source of truth (`metrics/events.jsonl`); `scripts/metrics.py`
computes everything else as a re-computable VIEW, so weights stay hot-swappable.

## Six-layer funnel (blast + precision unified)
`L1 sent → L2 delivered → L3 view/open → L4 engage(like+comment+share+reply) → L5 click →
L6 conversion`, each with absolute count + rate, tagged channel/account/campaign/arm/segment.
**Negatives are first-class**: bounce/complaint/unsub/blocked/ratelimited/shadowban. Verified by E1.

## Attribution
Prefer the product's own ref system (`register?aff=<code>`) → channel-level signup attribution with no
extra tracking. Fall back to a UTM taxonomy (`utm_source/medium/campaign/content=arm/term=segment`).
Store only raw touch events; the attribution model (default last-non-direct-touch) is a consumer-side
view and re-computable. Verified by E6.

## Reward (multi-objective, anti-Goodhart)
`reward = Σ(metric × weight × sign)` from a hot-swappable `reward_config`. **Strong negatives**
(ban/spam/unsub/complaint) make the bandit learn to avoid compliance red-lines instead of maximizing
raw engagement. **Delayed conversions**: an arm with no conversion yet but still inside
`conversion_window` is CENSORED (not a negative) so slow-but-high-quality channels aren't
under-rewarded. Verified by E11.

## Propensity + shadowban
Every bandit decision stores `propensity_p` + `policy_version` (off-policy de-biasing needs them;
E8). A per-account daily shadowban probe (search/reply/hashtag visibility + impressions z-score)
writes a `shadowban` event that feeds a strong negative reward and flips the account to
cooldown/engage-only mode.
