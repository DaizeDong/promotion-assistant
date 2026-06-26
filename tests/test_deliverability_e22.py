"""E22 — deliverability-driven auto-throttle (ROADMAP "Planned": mailbox-pool warmup +
inbox-placement probe -> deliverability-driven auto-throttle).

Red->green: hide scripts/deliverability.py -> this module is a collection error; restore -> green.
Each claim is checked against a NON-TRIVIAL control (placement-blind / no-warmup) so passing
proves the deliverability signal is load-bearing, not incidental. Pure-stdlib, deterministic.
"""
import pytest

from scripts import deliverability as DL


# ---- E22.1 placement_rate exact (list + dict forms) ----
def test_e22_placement_rate_exact():
    assert DL.placement_rate(["inbox", "inbox", "spam", "missing"]) == 0.5
    assert DL.placement_rate({"inbox": 9, "spam": 1, "missing": 0}) == 0.9
    assert DL.placement_rate(["inbox"] * 3) == 1.0
    assert DL.placement_rate(["spam", "missing"]) == 0.0


# ---- E22.2 CORE: degraded placement throttles where a placement-BLIND control does not ----
def test_e22_aware_throttles_vs_blind_control():
    base = 100.0
    aged = 30.0  # warmup ceiling >> base, so warmup does NOT bind -> isolates placement effect
    # degraded inbox placement -> aware ceiling strictly below the placement-blind ceiling
    aware_bad = DL.recommend_cap(base, inbox_rate=0.60, mailbox_age_days=aged)
    blind_bad = DL.blind_cap(base, mailbox_age_days=aged)
    assert aware_bad < blind_bad, "degraded placement must cut the cap below the blind control"
    assert aware_bad < 0.5 * blind_bad, "non-trivial: a real cut, not a rounding nudge"
    # healthy placement -> aware matches the blind control (no needless throttling)
    aware_ok = DL.recommend_cap(base, inbox_rate=0.95, mailbox_age_days=aged)
    assert aware_ok == DL.blind_cap(base, mailbox_age_days=aged)


# ---- E22.3 placement_multiplier monotone + HARD pause below floor ----
def test_e22_multiplier_monotone_and_pauses():
    assert DL.placement_multiplier(0.95) == 1.0          # healthy -> full
    assert DL.placement_multiplier(0.40) == 0.0          # below floor -> HARD pause
    assert DL.placement_multiplier(0.50) == 0.0          # at floor -> pause boundary
    grid = [i / 20.0 for i in range(21)]                 # 0.00 .. 1.00
    vals = [DL.placement_multiplier(r) for r in grid]
    assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:])), "must be non-decreasing in rate"
    assert all(0.0 <= v <= 1.0 for v in vals)


# ---- E22.4 warmup ramp monotone, fresh << steady, capped; non-trivial vs no-warmup ----
def test_e22_warmup_ramp_curve():
    ages = [0, 1, 2, 5, 10, 50]
    caps = [DL.warmup_ramp(a) for a in ages]
    assert all(b >= a - 1e-9 for a, b in zip(caps, caps[1:])), "warmup ceiling non-decreasing in age"
    fresh = DL.warmup_ramp(0)
    steady = DL.warmup_ramp(1000)
    assert fresh < 0.1 * steady, "a FRESH mailbox must not blast at the steady cap (warmup binds)"
    assert steady == 500.0, "ceiling capped at steady-state"
    # non-trivial vs a 'no warmup' control that would hand a day-0 mailbox the full steady cap
    assert fresh < steady


# ---- E22.5 recommend_cap: BOTH constraints bind (fresh mailbox + degraded placement) ----
def test_e22_recommend_cap_both_constraints_bind():
    base = 100.0
    cap = DL.recommend_cap(base, inbox_rate=0.70, mailbox_age_days=0.0)
    # warm(age0)=20, mult(0.70)=0.5 -> min(100,20)*0.5 = 10.0
    assert abs(cap - 10.0) < 1e-9
    assert cap < base                                    # below the raw base cap
    assert cap < DL.warmup_ramp(0)                       # below the warmup-only ceiling
    assert cap < base * DL.placement_multiplier(0.70)    # below the placement-only ceiling
    # placement floor breach pauses regardless of warmup headroom
    assert DL.recommend_cap(base, inbox_rate=0.45, mailbox_age_days=30) == 0.0


# ---- E22.6 deterministic reproducibility (pure functions) ----
def test_e22_deterministic():
    a = DL.recommend_cap(80.0, inbox_rate=0.77, mailbox_age_days=3.0)
    b = DL.recommend_cap(80.0, inbox_rate=0.77, mailbox_age_days=3.0)
    assert a == b
    ctrl = DL.DeliverabilityController(base_cap=80.0)
    r1 = ctrl.cap_for(probe=["inbox", "inbox", "spam", "missing"], mailbox_age_days=3.0)
    r2 = ctrl.cap_for(probe={"inbox": 2, "spam": 1, "missing": 1}, mailbox_age_days=3.0)
    assert r1["recommended_cap"] == r2["recommended_cap"]
    assert r1["inbox_rate"] == 0.5 and r1["paused"] is True  # rate 0.5 at floor -> paused


# ---- E22.7 input-domain guards ----
def test_e22_input_guards():
    with pytest.raises(ValueError):
        DL.placement_rate([])
    with pytest.raises(ValueError):
        DL.placement_rate(["inbox", "bogus"])
    with pytest.raises(ValueError):
        DL.placement_multiplier(1.5)
    with pytest.raises(ValueError):
        DL.placement_multiplier(0.8, floor=0.9, healthy=0.5)   # floor>=healthy
    with pytest.raises(ValueError):
        DL.warmup_ramp(-1)
    with pytest.raises(ValueError):
        DL.warmup_ramp(5, daily_growth=0.5)                    # growth < 1
    with pytest.raises(ValueError):
        DL.recommend_cap(-1.0, inbox_rate=0.9, mailbox_age_days=1.0)
