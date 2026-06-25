"""E21 (R10): off-policy evaluation (OPE) — de-bias a log collected by the behavior policy.

Pins a NEW capability the E1-E12 / batch-1 / batch-2 contract did not cover: estimating the value
of a *candidate target policy* from historical decisions logged under a *different* (behavior)
policy, using the stored propensity_p (ARCHITECTURE.md sec 7.4). The naive on-log reward mean is
badly biased toward the behavior policy's value; IPS/SNIPS/DR must recover the target policy's true
value. The contrast naive-vs-OPE proves the assertions are non-trivial (not satisfiable by any
estimator). Doubly-robust is checked to be consistent even with a wrong reward model, and SNIPS/DR
are checked to actually reduce variance vs raw IPS.

Deterministic (seeded RNG), pure stdlib. Red before scripts/ope.py existed; green after.
"""
import random
import statistics

from scripts import ope as O


# ground-truth environment: 3 arms, behavior policy biased toward the WORST arm.
TRUE_MEANS = {"A": 0.20, "B": 0.50, "C": 0.80}
BEHAVIOR = {"A": 0.70, "B": 0.20, "C": 0.10}   # logs over-represent the bad arm A
TARGET = {"A": 0.10, "B": 0.20, "C": 0.70}     # candidate policy we want to evaluate offline


def _gen_log(rng, n):
    """Sample n decisions ~ behavior policy; reward ~ Bernoulli(true_mean[arm]); store propensity."""
    arms = list(BEHAVIOR)
    cum = []
    acc = 0.0
    for a in arms:
        acc += BEHAVIOR[a]
        cum.append((acc, a))
    recs = []
    for _ in range(n):
        u = rng.random()
        arm = next(a for c, a in cum if u <= c)
        r = 1.0 if rng.random() < TRUE_MEANS[arm] else 0.0
        recs.append({"arm_id": arm, "reward": r, "propensity_p": BEHAVIOR[arm]})
    return recs


def test_ips_debiases_where_naive_fails():
    """IPS recovers the TARGET policy's true value; the naive on-log mean does not (non-trivial)."""
    truth = O.on_policy_value(TRUE_MEANS, TARGET)          # = .1*.2+.2*.5+.7*.8 = 0.68
    behavior_truth = O.on_policy_value(TRUE_MEANS, BEHAVIOR)  # = .32
    assert abs(truth - 0.68) < 1e-9 and abs(behavior_truth - 0.32) < 1e-9
    rng = random.Random(20260625)
    recs = _gen_log(rng, 8000)
    v_ips = O.ips(recs, TARGET)
    v_naive = O.naive_value(recs)
    # 1) IPS lands near the target policy's TRUE value
    assert abs(v_ips - truth) < 0.03, (v_ips, truth)
    # 2) the naive estimator is badly biased toward the BEHAVIOR value (assertion has teeth)
    assert abs(v_naive - behavior_truth) < 0.03, (v_naive, behavior_truth)
    assert abs(v_naive - truth) > 0.20, (v_naive, truth)
    # 3) IPS is dramatically closer to truth than naive
    assert abs(v_ips - truth) < abs(v_naive - truth) - 0.20


def test_snips_lower_variance_than_ips():
    """SNIPS has materially lower variance than raw IPS across independent log replicates."""
    truth = O.on_policy_value(TRUE_MEANS, TARGET)
    ips_est, snips_est = [], []
    for s in range(40):
        rng = random.Random(1000 + s)
        recs = _gen_log(rng, 1500)
        ips_est.append(O.ips(recs, TARGET))
        snips_est.append(O.snips(recs, TARGET))
    var_ips = statistics.pvariance(ips_est)
    var_snips = statistics.pvariance(snips_est)
    assert var_snips < var_ips, (var_snips, var_ips)
    # both stay approximately centered on truth (no gross bias introduced by self-normalization)
    assert abs(statistics.mean(snips_est) - truth) < 0.02, statistics.mean(snips_est)


def test_dr_consistent_with_wrong_reward_model():
    """Doubly-robust: even a deliberately WRONG q_hat still recovers truth (propensities are right)."""
    truth = O.on_policy_value(TRUE_MEANS, TARGET)
    rng = random.Random(7)
    recs = _gen_log(rng, 8000)
    bad_q = {"A": 0.5, "B": 0.5, "C": 0.5}   # constant, ignores the real arm ordering
    v_dr = O.dr(recs, TARGET, bad_q)
    assert abs(v_dr - truth) < 0.03, (v_dr, truth)


def test_dr_reduces_variance_with_good_model():
    """With a decent q_hat (fit from the log), DR has lower variance than IPS — the DR payoff."""
    ips_est, dr_est = [], []
    for s in range(40):
        rng = random.Random(5000 + s)
        recs = _gen_log(rng, 1500)
        q = O.fit_q_hat(recs)
        ips_est.append(O.ips(recs, TARGET))
        dr_est.append(O.dr(recs, TARGET, q))
    assert statistics.pvariance(dr_est) < statistics.pvariance(ips_est), (
        statistics.pvariance(dr_est), statistics.pvariance(ips_est))


def test_clipping_reduces_variance_under_extreme_weights():
    """Under a heavy distribution shift (extreme weights), clipped IPS has lower variance than raw."""
    # target concentrates on the arm the behavior policy almost never tried -> huge raw weights.
    extreme_target = {"A": 0.02, "B": 0.03, "C": 0.95}  # C had behavior prob only 0.10
    raw, clipped = [], []
    for s in range(40):
        rng = random.Random(9000 + s)
        recs = _gen_log(rng, 400)
        raw.append(O.ips(recs, extreme_target))
        clipped.append(O.clipped_ips(recs, extreme_target, clip=5.0))
    assert statistics.pvariance(clipped) < statistics.pvariance(raw), (
        statistics.pvariance(clipped), statistics.pvariance(raw))


def test_missing_propensity_is_rejected():
    """A logged decision without propensity_p must raise (sec 7.4: no propensity -> OPE impossible)."""
    bad = [{"arm_id": "A", "reward": 1.0}]  # no propensity_p
    try:
        O.ips(bad, TARGET)
    except ValueError:
        return
    raise AssertionError("expected ValueError for missing propensity_p")


def test_zero_propensity_is_rejected():
    """propensity_p must be strictly > 0 (division-by-zero / undefined weight guard)."""
    bad = [{"arm_id": "A", "reward": 1.0, "propensity_p": 0.0}]
    try:
        O.snips(bad, TARGET)
    except ValueError:
        return
    raise AssertionError("expected ValueError for zero propensity_p")
