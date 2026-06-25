"""Deeper roadmap-capability assertions (batch-1 headroom).

These pin behaviors the existing E1-E12 gate does NOT cover: bandit *sub-linear regret* (not just
final best-share), attribution *boundaries* (multi-touch last-non-direct ordering + direct-only
fallback), throttle *stricter discipline* (warmup no-skip exactness, AIMD ramp ceiling, min-gap
pacing), delayed-conversion *window edge*, and reward *strong-negative ordering*. They assert
properties of the CURRENT implementation (all green), expanding the verifiable contract under the
mutation-killable A-tier gate without breaking any existing contract.
"""
import random

from scripts import bandit as B
from scripts import events as EV
from scripts import metrics as M
from scripts import throttle as TH


# ---- D1 bandit sub-linear regret (deeper than E2's final best-share) ----
def test_bandit_sublinear_regret():
    rng = random.Random(7)
    sim = random.Random(11)
    probs = {"a0": 0.3, "a1": 0.3, "a2": 0.7, "a3": 0.3}
    best = 0.7
    b = B.Bandit(None, gamma=1.0, rng=rng)
    n = 400
    half = n // 2
    regret_first = regret_last = 0.0
    for t in range(n):
        d = b.select(list(probs), samples_for_propensity=20)
        arm = d["arm_id"]
        r = 1.0 if sim.random() < probs[arm] else 0.0
        b.update(arm, r)
        inst = best - probs[arm]
        if t < half:
            regret_first += inst
        else:
            regret_last += inst
    # Learning => per-round regret in the back half is far below the front half (sub-linear growth),
    # and the converged regret rate is small relative to the all-suboptimal rate (0.4).
    assert regret_last < regret_first * 0.5, (regret_first, regret_last)
    assert regret_last / half < 0.1, regret_last / half


# ---- D2 attribution: direct-only conversion falls back to the conversion event ----
def test_attribution_direct_only_fallback():
    evs = [EV.make_event("email", "conversion", subject_key="u2", ts=5.0)]
    a = M.attribute(evs)
    assert len(a) == 1
    assert a[0]["attributed_channel"] == "email"
    assert a[0]["attributed_arm"] is None


# ---- D3 attribution: last NON-direct touch wins across multiple touches (E6 has only one) ----
def test_attribution_last_non_direct_ordering():
    evs = [
        EV.make_event("reddit", "sent", arm_id="X", subject_key="u", ts=1.0,
                      propensity_p=0.5, policy_version="v", utm={"content": "X"}),
        EV.make_event("mastodon", "click", arm_id="Y", subject_key="u", ts=2.0,
                      utm={"content": "Y"}),
        EV.make_event("reddit", "conversion", subject_key="u", ts=3.0),
    ]
    a = M.attribute(evs)
    assert len(a) == 1
    assert a[0]["attributed_arm"] == "Y"
    assert a[0]["attributed_channel"] == "mastodon"


# ---- D4 warmup state machine: no level-skipping, exact action gating ----
def test_warmup_no_skip_exact(tmp_path):
    thr = TH.Throttle(tmp_path / "s.json", rng=random.Random(1))
    pol = {"day_cap": 5, "min_gap_sec": 0}
    assert thr.allow("a", "reddit", "post", pol, account_stage="like")[0] is False
    assert thr.allow("a", "reddit", "comment", pol, account_stage="follow_comment")[0] is True
    assert thr.allow("a", "reddit", "post", pol, account_stage="follow_comment")[0] is False
    assert thr.allow("a", "reddit", "post", pol, account_stage="normal")[0] is True
    # unknown/garbage stage must degrade to the most restrictive (browse: no actions)
    assert thr.allow("a", "reddit", "like", pol, account_stage="???")[0] is False


# ---- D5 AIMD additive ramp-up is capped at base_cap * max_growth_mult ----
def test_throttle_rampup_ceiling(tmp_path):
    clock = [1000.0]
    thr = TH.Throttle(tmp_path / "s.json", clock=lambda: clock[0], rng=random.Random(1))
    pol = {"day_cap": 10, "rampup": {"stable_days": 1, "factor": 2.0}, "max_growth_mult": 3.0}
    thr._bucket("a", "reddit", "post", pol)  # initialize base_cap=10
    for _ in range(20):
        clock[0] += 2 * 86400.0  # advance two stable days each iteration
        thr.on_stable_period("a", "reddit", "post", pol)
    cap = thr.state["a|reddit|post"]["cap"]
    assert cap <= 10 * 3.0 + 1e-9, cap     # never exceeds the ceiling
    assert cap > 10.0, cap                  # but it did grow


# ---- D6 min-gap pacing blocks a too-soon second action ----
def test_throttle_min_gap_pacing(tmp_path):
    clock = [1000.0]
    thr = TH.Throttle(tmp_path / "s.json", clock=lambda: clock[0], rng=random.Random(1))
    pol = {"day_cap": 50, "min_gap_sec": 600}
    ok1 = thr.allow("a", "reddit", "post", pol)
    assert ok1[0] is True
    clock[0] += 1.0  # only one second later
    ok2 = thr.allow("a", "reddit", "post", pol)
    assert ok2[0] is False
    assert "min-gap" in ok2[1]


# ---- D7 delayed-conversion window edge (boundary E11 does not pin) ----
def test_delayed_conversion_window_edge():
    now = 100000.0
    # Exactly at the window edge: (now - last_send) == window -> NOT censored (strict <).
    edge = [EV.make_event("c", "sent", arm_id="z", ts=now - 1000.0,
                          propensity_p=0.5, policy_version="v")]
    r, s = M.reward_for_arm(edge, "z", conversion_window_s=1000, now=now)
    assert s == "ok" and r is not None, (s, r)
    # Just inside the window -> censored (not a negative).
    inside = [EV.make_event("c", "sent", arm_id="z", ts=now - 999.0,
                            propensity_p=0.5, policy_version="v")]
    r2, s2 = M.reward_for_arm(inside, "z", conversion_window_s=1000, now=now)
    assert s2 == "censored" and r2 is None, (s2, r2)


# ---- D8 reward strong-negative ordering (ban/complaint must rank below engagement) ----
def test_reward_strong_negative_ordering():
    pos = [EV.make_event("c", "sent", arm_id="p", propensity_p=0.5, policy_version="v"),
           EV.make_event("c", "click", arm_id="p"),
           EV.make_event("c", "conversion", arm_id="p")]
    neg = [EV.make_event("c", "sent", arm_id="n", propensity_p=0.5, policy_version="v"),
           EV.make_event("c", "complaint", arm_id="n"),
           EV.make_event("c", "blocked", arm_id="n")]
    rp, _ = M.reward_for_arm(pos, "p")
    rn, _ = M.reward_for_arm(neg, "n")
    assert rp > rn, (rp, rn)
    assert rn < 0.5, rn   # a net-negative arm squashes below the neutral midpoint
