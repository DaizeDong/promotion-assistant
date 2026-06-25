"""E16 (R5): Demeter-style delayed-reward prediction — the predicted reward is CALIBRATED and
DISCRIMINATES against the backfilled true reward, AND training is censoring-correct per §7.1
stage-4. Both claims are checked against non-trivial controls.

Pins a NEW capability that E1-E12 / batch-1 (deeper roadmap) / batch-2 (E19 seqtest) / batch-3
(E21 OPE) / batch-4 (E2c ctxbandit) / batch-5 (E20 segment) did NOT cover: metrics.py only
*censors* delayed conversions (won't count an in-window non-conversion as a negative). It never
*predicts* the eventual reward from early signals. ARCHITECTURE §7.1 stage-4 wants both halves —
reward_partial (an early, calibrated estimate) + reward_final (backfill). scripts/delayed.py is
the predictive half.

E16 demands the predicted reward's CALIBRATION ERROR vs the backfilled true reward be small. The
bar is un-gameable because it requires TWO things at once that a single trick can't fake:
  (1) CALIBRATION: low ECE and a recalibration slope near 1.
  (2) DISCRIMINATION: Brier < the predict-the-base-rate baseline (which is calibrated-in-
      aggregate but useless) and AUC well above 0.5.
Plus the architecture-load-bearing CENSORING test: a censor-aware fit tracks the true base rate
while a fit that trains still-open impressions as NEGATIVES (the delayed-feedback bug) is biased
low and scores worse — proving §7.1 stage-4 is actually enforced, not just documented.

Mutation-killable: make fit_delayed ignore censor_aware (always train censored as negative) OR
make resolve_label return False instead of None for in-window rows -> the censoring contrast
collapses (aware == naive). Neuter the gradient update -> calibration/Brier/AUC collapse to the
base-rate floor. Red before scripts/delayed.py existed; green after. Pure stdlib, seeded RNG.
"""
import math
import random

import pytest

from scripts import delayed as D


# --------------------------------------------------------------- synthetic delayed-conversion world
# Eventual conversion follows a logistic law in two early-window features (x1=early engagement,
# x2=early click signal). The label is only revealed after a conversion window; converters convert
# at a random delay inside that window.
W = 100.0          # conversion_window_s
A, B1, B2 = -3.0, 5.0, 2.5   # true logit coefficients (steep -> high Bayes-optimal separability)


def _true_p(x1, x2):
    return D._sigmoid(A + B1 * x1 + B2 * x2)


def _resolved_cohort(n, seed):
    """Fully-resolved samples (window elapsed by now=0): clean pos/neg mix. Returns samples list."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        x1, x2 = rng.random(), rng.random()
        conv = rng.random() < _true_p(x1, x2)
        # send long ago so the window has fully elapsed at now=0
        s = {"features": [x1, x2], "send_ts": -200.0,
             "converted": conv,
             "convert_ts": (-200.0 + rng.uniform(1.0, W - 1.0)) if conv else None}
        out.append(s)
    return out


def _truth(samples):
    return [1.0 if s["converted"] else 0.0 for s in samples]


# ============================================================ (1) calibration + discrimination (E16)
def test_e16_calibrated_and_discriminates_vs_base_rate():
    train = _resolved_cohort(800, seed=1)
    holV = _resolved_cohort(600, seed=2)
    model = D.fit_delayed(train, now=0.0, conversion_window_s=W, censor_aware=True,
                          l2=1e-4, lr=0.5, epochs=800)

    probs = [model.predict_proba(s["features"]) for s in holV]
    y = _truth(holV)

    ece = D.expected_calibration_error(probs, y, bins=10)
    brier = D.brier_score(probs, y)
    a = D.auc(probs, y)
    slope = D.calibration_slope(probs, y)

    # CALIBRATION: low ECE + recalibration slope ~ 1 (neither over- nor under-confident).
    assert ece < 0.08, ece
    assert 0.6 < slope < 1.5, slope

    # DISCRIMINATION vs the non-trivial base-rate baseline (predict global mean for everyone):
    base = sum(y) / len(y)
    brier_base = D.brier_score([base] * len(y), y)     # calibrated-in-aggregate, zero discrimination
    assert brier < 0.9 * brier_base, (brier, brier_base)
    assert a > 0.80, a                                  # base-rate baseline AUC is exactly 0.5


# ====================================================== (2) censoring-correct training (§7.1 stage-4)
def test_e16_censor_aware_unbiased_vs_naive_negative_bug():
    """A cohort of recent HIGH-feature impressions are TRUE late-converters still inside their
    window. Censor-aware training drops them (unknown label); the naive bug trains them as
    NEGATIVES. The naive model then under-predicts; the censor-aware model tracks the true rate."""
    resolved = _resolved_cohort(700, seed=10)

    # open cohort: recent (window NOT elapsed at now=0), high-feature, eventual TRUE converters,
    # but convert_ts is in the FUTURE -> at now=0 they are CENSORED, not yet observed.
    rng = random.Random(11)
    open_rows = []
    for _ in range(250):
        x1 = 0.85 + rng.random() * 0.1
        x2 = 0.85 + rng.random() * 0.1
        open_rows.append({"features": [x1, x2], "send_ts": -10.0,
                          "converted": True, "convert_ts": +40.0})  # converts later, after now

    # sanity: every open row is censored at now=0, every resolved row is decided.
    assert all(D.resolve_label(r, now=0.0, conversion_window_s=W) is None for r in open_rows)
    assert all(D.resolve_label(r, now=0.0, conversion_window_s=W) is not None for r in resolved)

    train = resolved + open_rows
    aware = D.fit_delayed(train, now=0.0, conversion_window_s=W, censor_aware=True, l2=1e-4)
    naive = D.fit_delayed(train, now=0.0, conversion_window_s=W, censor_aware=False, l2=1e-4)

    # clean fully-resolved holdout with a known true base rate.
    hold = _resolved_cohort(800, seed=12)
    y = _truth(hold)
    true_rate = sum(y) / len(y)
    mean_aware = sum(aware.predict_proba(s["features"]) for s in hold) / len(hold)
    mean_naive = sum(naive.predict_proba(s["features"]) for s in hold) / len(hold)

    bias_aware = mean_aware - true_rate
    bias_naive = mean_naive - true_rate
    # censor-aware ~ unbiased; naive biased DOWN (delayed-feedback under-counting).
    assert abs(bias_aware) < 0.05, (mean_aware, true_rate)
    assert bias_naive < -0.05, (mean_naive, true_rate)
    assert abs(bias_naive) > 2.0 * abs(bias_aware), (bias_aware, bias_naive)
    # and censoring-correctness measurably improves the Brier score on the holdout.
    pa = [aware.predict_proba(s["features"]) for s in hold]
    pn = [naive.predict_proba(s["features"]) for s in hold]
    assert D.brier_score(pa, y) < D.brier_score(pn, y), (D.brier_score(pa, y), D.brier_score(pn, y))


# ====================================================================== (3) label resolution semantics
def test_e16_resolve_label_three_states():
    # observed positive: converted and convert_ts <= now
    assert D.resolve_label({"send_ts": -200.0, "converted": True, "convert_ts": -150.0},
                           now=0.0, conversion_window_s=W) is True
    # observed negative: not converted and window elapsed
    assert D.resolve_label({"send_ts": -200.0, "converted": False, "convert_ts": None},
                           now=0.0, conversion_window_s=W) is False
    # CENSORED: not converted yet and still inside the window
    assert D.resolve_label({"send_ts": -10.0, "converted": False, "convert_ts": None},
                           now=0.0, conversion_window_s=W) is None
    # converted but convert_ts in the future -> not yet observed -> censored
    assert D.resolve_label({"send_ts": -10.0, "converted": True, "convert_ts": +40.0},
                           now=0.0, conversion_window_s=W) is None


# ======================================================================== (4) predict_reward scaling
def test_e16_predict_reward_scales_by_value():
    m = D.fit_delayed(_resolved_cohort(300, seed=20), now=0.0, conversion_window_s=W)
    f = [0.7, 0.6]
    p = m.predict_proba(f)
    assert D.predict_reward(m, f, conversion_value=4.0) == pytest.approx(p * 4.0)
    assert D.predict_reward(m, f, conversion_value=0.0) == 0.0
    with pytest.raises(ValueError):
        D.predict_reward(m, f, conversion_value=-1.0)


# ===================================================================== (5) GD reduces training loss
def test_e16_training_loss_monotone_nonincreasing():
    train = _resolved_cohort(400, seed=30)
    m = D.fit_delayed(train, now=0.0, conversion_window_s=W, lr=0.4, epochs=300)
    tr = m.loss_trace
    assert len(tr) == 300
    for earlier, later in zip(tr, tr[1:]):
        assert later <= earlier + 1e-9, (earlier, later)   # full-batch GD on convex log-loss
    assert tr[-1] < tr[0] - 0.1, (tr[0], tr[-1])           # it actually learned, not flat


# ===================================================================== (6) deterministic under data
def test_e16_deterministic_fit():
    train = _resolved_cohort(300, seed=40)
    m1 = D.fit_delayed(train, now=0.0, conversion_window_s=W, l2=1e-4)
    m2 = D.fit_delayed(train, now=0.0, conversion_window_s=W, l2=1e-4)
    assert m1.w == m2.w and m1.b == m2.b


# =============================================================================== (7) input guards
def test_e16_input_guards():
    with pytest.raises(ValueError):
        D.LogisticReward(0)                                 # dim must be positive
    with pytest.raises(ValueError):
        D.fit_delayed([], now=0.0, conversion_window_s=W)   # no samples
    with pytest.raises(ValueError):
        D.expected_calibration_error([0.5], [1.0, 0.0])     # length mismatch
    with pytest.raises(ValueError):
        D.expected_calibration_error([], [])                # empty
    with pytest.raises(ValueError):
        D.brier_score([0.5], [])                            # length mismatch
    # all-censored training set has no resolvable rows -> explicit error
    allcensored = [{"features": [0.9, 0.9], "send_ts": -1.0, "converted": False, "convert_ts": None}]
    with pytest.raises(ValueError):
        D.fit_delayed(allcensored, now=0.0, conversion_window_s=W, censor_aware=True)
