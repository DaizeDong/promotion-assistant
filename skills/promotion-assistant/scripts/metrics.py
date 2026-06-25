#!/usr/bin/env python3
"""L4 metrics — six-layer funnel, attribution, and reward (all VIEWS over events.jsonl).

Funnel (unified for blast + precision):
  L1 sent -> L2 delivered -> L3 view/open -> L4 engage(like+comment+share+reply)
  -> L5 click -> L6 conversion.
Negatives are quantified equally: bounce/complaint/unsub/blocked/ratelimited/shadowban.

Attribution: prefer the product's own ref system (register?aff=<code>) which gives channel-level
signup attribution with no extra tracking; fall back to UTM taxonomy on the touch sequence. We
store only raw touch events (event sourcing) — the attribution model + reward function are
consumer-side and re-computable, never baked into storage.

Reward: multi-objective linear scalarization with weights from reward_config (hot-swappable),
with STRONG NEGATIVE terms (ban/spam/unsub/complaint) so the bandit internalizes compliance.
Delayed conversions: an arm with no conversion *yet* but still inside conversion_window is
CENSORED (not counted as a negative), so slow-but-high-quality channels aren't under-rewarded.
"""
from __future__ import annotations

DEFAULT_REWARD_WEIGHTS = {
    "view": 0.05, "open": 0.05,
    "like": 0.1, "comment": 0.2, "share": 0.3, "reply": 0.4,
    "click": 0.6, "conversion": 1.0,
    # strong negatives
    "bounce": -0.3, "unsub": -0.6, "complaint": -0.9, "blocked": -0.8,
    "ratelimited": -0.3, "shadowban": -0.7,
}

FUNNEL = {
    "L1_sent": {"sent", "simulated"},
    "L2_delivered": {"delivered"},
    "L3_view": {"view", "open"},
    "L4_engage": {"like", "comment", "share", "reply"},
    "L5_click": {"click"},
    "L6_conversion": {"conversion"},
}
NEGATIVES = {"bounce", "unsub", "complaint", "blocked", "ratelimited", "shadowban"}


def funnel(events, *, dims=("channel",)):
    """Return nested counts: {dim_tuple: {layer: count, ...negatives...}}."""
    out = {}
    for ev in events:
        key = tuple(ev.get(d) for d in dims)
        bucket = out.setdefault(key, {k: 0 for k in FUNNEL})
        for layer, types in FUNNEL.items():
            if ev["event_type"] in types:
                bucket[layer] += 1
        if ev["event_type"] in NEGATIVES:
            bucket[ev["event_type"]] = bucket.get(ev["event_type"], 0) + 1
    # rates
    for bucket in out.values():
        s = bucket["L1_sent"] or 0
        bucket["cr_click"] = (bucket["L5_click"] / s) if s else 0.0
        bucket["cr_conv"] = (bucket["L6_conversion"] / s) if s else 0.0
    return out


def attribute(events):
    """Last-non-direct-touch over an ordered touch sequence per (recipient/decision).

    Returns list of {conversion_event, attributed_arm, attributed_channel}.
    Uses ref/UTM content as the arm signal (ref code preferred via utm.content)."""
    # group touches by a subject key (account+recipient or decision lineage)
    seq = {}
    for ev in sorted(events, key=lambda e: e["ts"]):
        subj = ev.get("subject_key") or ev.get("recipient") or ev.get("decision_id") or "_"
        seq.setdefault(subj, []).append(ev)
    results = []
    for subj, touches in seq.items():
        last_touch = None
        for ev in touches:
            if ev["event_type"] in ("click", "view", "open", "sent", "simulated"):
                last_touch = ev  # non-direct touch
            if ev["event_type"] == "conversion":
                src = last_touch or ev
                results.append({
                    "conversion_event": ev["event_id"],
                    "attributed_arm": src.get("arm_id"),
                    "attributed_channel": src.get("channel"),
                    "utm": src.get("utm", {}),
                })
    return results


def reward_for_arm(events, arm_id, *, weights=None, conversion_window_s=None, now=None):
    """Scalar reward for one arm. Censored if inside conversion window with no conversion yet."""
    weights = weights or DEFAULT_REWARD_WEIGHTS
    rel = [e for e in events if e.get("arm_id") == arm_id]
    if not rel:
        return None, "no-data"
    total = 0.0
    has_conv = any(e["event_type"] == "conversion" for e in rel)
    last_send = max((e["ts"] for e in rel if e["event_type"] in ("sent", "simulated")), default=None)
    if (conversion_window_s and now is not None and last_send is not None
            and not has_conv and (now - last_send) < conversion_window_s):
        return None, "censored"  # delayed-conversion: do NOT count as negative yet
    for e in rel:
        total += weights.get(e["event_type"], 0.0) * float(e.get("value", 1.0))
    n_send = sum(1 for e in rel if e["event_type"] in ("sent", "simulated")) or 1
    # squash to [0,1] for the Beta update
    avg = total / n_send
    norm = 1.0 / (1.0 + pow(2.718281828, -avg))  # logistic
    return norm, "ok"
