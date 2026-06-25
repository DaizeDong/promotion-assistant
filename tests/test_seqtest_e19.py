"""E19 (R8): always-valid sequential A/B test — Type-I control under continuous peeking.

This pins a NEW capability the prior E1-E12 / batch-1 contract did not cover: a *causal* sequential
test (separate from the bandit's *decision* optimization, per ARCHITECTURE.md sec 7.3) whose
false-positive rate stays at the nominal alpha EVEN when you peek every single step. A naive
fixed-sample z-test read with the same peeking blows past alpha — that contrast proves the
e-process is doing real work and the assertion is not trivially satisfiable.

Deterministic (seeded RNG), pure stdlib. Red before scripts/seqtest.py existed; green after.
"""
import math
import random

from scripts import seqtest as S


def _naive_z_peeking_reject(a_stream, b_stream, z_crit):
    """Naive two-proportion z-test read with continuous peeking (the WRONG way).

    Returns True if at ANY step t>=10 the two-sided z exceeds z_crit. This is the inflated-error
    baseline the always-valid test is supposed to beat.
    """
    sa = sb = na = nb = 0
    for t in range(len(a_stream)):
        sa += a_stream[t]; na += 1
        sb += b_stream[t]; nb += 1
        if na < 10:
            continue
        pa = sa / na
        pb = sb / nb
        p = (sa + sb) / (na + nb)
        denom = p * (1 - p) * (1.0 / na + 1.0 / nb)
        if denom <= 0:
            continue
        z = (pa - pb) / math.sqrt(denom)
        if abs(z) >= z_crit:
            return True
    return False


def test_type1_controlled_under_peeking():
    """Under H0 (equal rates) with peeking every step, e-process FPR <= alpha; naive >> e-process."""
    alpha = 0.10
    rng = random.Random(20260625)
    p = 0.35  # identical rate for both arms (null is TRUE)
    sims = 400
    T = 160
    e_false = 0
    naive_false = 0
    for _ in range(sims):
        a_stream = [1 if rng.random() < p else 0 for _ in range(T)]
        b_stream = [1 if rng.random() < p else 0 for _ in range(T)]
        t = S.SequentialABTest(alpha=alpha)
        rejected = False
        for i in range(T):
            snap = t.update(a_stream[i], b_stream[i])
            if snap["reject"]:
                rejected = True
                break
        if rejected:
            e_false += 1
        # naive peeking z at the same two-sided alpha=0.10 -> z_crit ~ 1.645
        if _naive_z_peeking_reject(a_stream, b_stream, z_crit=1.6449):
            naive_false += 1
    e_fpr = e_false / sims
    naive_fpr = naive_false / sims
    # 1) always-valid: empirical anytime Type-I stays at/under nominal alpha (small MC slack ok)
    assert e_fpr <= alpha + 0.02, (e_fpr, naive_fpr)
    # 2) non-trivial: the naive peeking test inflates well past alpha (so the assertion has teeth)
    assert naive_fpr > 0.20, naive_fpr
    assert e_fpr < naive_fpr, (e_fpr, naive_fpr)


def test_power_detects_true_effect_with_direction():
    """Under a real effect (A clearly better), the test rejects with direction 'A' in the large
    majority and NEVER in the wrong direction (always-valid tests are conservative by design)."""
    rng = random.Random(99)
    pa, pb = 0.55, 0.25
    sims = 60
    T = 1200
    hits = 0
    wrong = 0
    for _ in range(sims):
        t = S.SequentialABTest(alpha=0.05)
        res = None
        for _i in range(T):
            res = t.update(1 if rng.random() < pa else 0,
                           1 if rng.random() < pb else 0)
            if res["reject"]:
                break
        if res["reject"] and res["direction"] == "A":
            hits += 1
        elif res["reject"] and res["direction"] == "B":
            wrong += 1
    assert hits >= int(0.85 * sims), hits
    assert wrong == 0, wrong


def test_anytime_pvalue_monotone_nonincreasing():
    """The anytime-valid p-value never increases as more evidence arrives (1/running-max e-value)."""
    rng = random.Random(3)
    t = S.SequentialABTest(alpha=0.05)
    last = 1.0
    for _ in range(300):
        snap = t.update(1 if rng.random() < 0.6 else 0,
                        1 if rng.random() < 0.3 else 0)
        assert snap["p_value"] <= last + 1e-12, (snap["p_value"], last)
        last = snap["p_value"]


def test_reject_is_sticky_and_threshold_correct():
    """Once rejected it stays rejected; threshold is exactly 2/alpha (two-sided via alpha/2 union)."""
    t = S.SequentialABTest(alpha=0.05)
    assert abs(t.threshold - 40.0) < 1e-9
    # force a strong one-sided signal
    for _ in range(200):
        t.update(1.0, 0.0)
    assert t.reject is True and t.direction == "A"
    e_after = t.e_value
    # feeding contrary noise must NOT un-reject (sticky) and running-max e-value cannot drop
    for _ in range(50):
        t.update(0.0, 1.0)
    assert t.reject is True and t.direction == "A"
    assert t.e_value >= e_after - 1e-9


def test_input_domain_guarded():
    """Out-of-range paired diff is rejected (rewards must be in [0,1])."""
    t = S.SequentialABTest(alpha=0.05)
    try:
        t.update(2.0, 0.0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for out-of-range reward")
