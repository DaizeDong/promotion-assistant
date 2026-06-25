"""E20 (R9): automatic audience segmentation (RFM + k-means) — discovered segments are STABLE and
carry a significant reward signal, both proven against a RANDOM-PARTITION control.

Pins a NEW capability that E1-E12 / batch-1 (deeper roadmap) / batch-2 (E19 seqtest) / batch-3 (E21
OPE) / batch-4 (E2c ctxbandit) did NOT cover: ARCHITECTURE.md ships `audiences.yaml` as a STATIC,
hand-authored segment list — there is no code that derives segments from behaviour. scripts/segment.py
builds an RFM feature per user from the raw event log and clusters it, so segmentation is data-driven.

Roadmap R9 -> E20 demands two things, and each is checked against a non-trivial control so the test
can't be passed by "any partition into K groups":
  (1) 段间 reward 差异显著 — discovered clusters explain a large fraction of reward variance
      (eta^2 high) while a RANDOM partition of the same points explains ~0.
  (2) 分段稳定性 — clustering two independent subsamples agrees (ARI high) while a random relabeling
      of the same points scores ~0.
Also: RFM aggregation is exact, planted clusters are recovered (purity >> 1/K random floor), k-means++
inertia is monotone non-increasing, and the fit is deterministic under a seed.

Mutation-killable: neuter standardize() (return the matrix unscaled) or the assignment step and the
recovered purity + reward eta^2 both collapse toward the random floor. Red before scripts/segment.py
existed; green after. Pure stdlib, deterministic (seeded RNG).
"""
import random

import pytest

from scripts import segment as S


# --------------------------------------------------------------------- synthetic RFM cluster generator
# 3 well-separated blobs in (recency, frequency, monetary) space. Each blob = one true audience.
CENTERS = [
    [2.0, 30.0, 500.0],     # segment 0: very recent, very frequent, high spend (whales)
    [40.0, 5.0, 40.0],      # segment 1: stale, infrequent, low spend (dormant)
    [10.0, 15.0, 150.0],    # segment 2: mid on all axes (regulars)
]
# Each true segment also has a distinct reward LEVEL (the bandit's eventual context signal).
SEG_REWARD = [0.80, 0.10, 0.45]
K = 3
PER = 80                    # points per blob


def _make(seed, noise=0.6):
    """Return (X rows, true_label per row, reward per row). Blobs are tight relative to spacing."""
    rng = random.Random(seed)
    X, truth, reward = [], [], []
    for s in range(K):
        cx = CENTERS[s]
        for _ in range(PER):
            X.append([cx[j] + rng.gauss(0.0, noise) for j in range(3)])
            truth.append(s)
            reward.append(max(0.0, min(1.0, SEG_REWARD[s] + rng.gauss(0.0, 0.05))))
    return X, truth, reward


# ------------------------------------------------------------------------------------- RFM extraction
def test_e20_rfm_aggregation_exact():
    events = [
        {"user": "u1", "ts": 100.0, "value": 5.0},
        {"user": "u1", "ts": 130.0, "value": 7.0},     # u1: last=130, n=2, sum=12
        {"user": "u2", "ts": 110.0, "value": 3.0},     # u2: last=110, n=1, sum=3
    ]
    users, mat = S.rfm_features(events, now=130.0)
    assert users == ["u1", "u2"]
    # recency = now - last_ts ; frequency = count ; monetary = sum(value)
    assert mat[0] == [0.0, 2.0, 12.0]
    assert mat[1] == [20.0, 1.0, 3.0]


# --------------------------------------------------------------- (recovery) planted clusters recovered
def test_e20_recovers_planted_clusters_beats_random_floor():
    X, truth, _ = _make(seed=1)
    Z = S.standardize(X)
    fit = S.kmeans(Z, K, rng=random.Random(7))
    purity = S.cluster_purity(fit["labels"], truth)
    assert purity > 0.95, purity                        # near-perfect recovery on separable blobs
    # non-trivial control: a RANDOM K-partition of the same points scores ~1/K.
    rng = random.Random(123)
    rand_labels = [rng.randrange(K) for _ in X]
    rand_purity = S.cluster_purity(rand_labels, truth)
    assert purity > 2.0 * rand_purity, (purity, rand_purity)


# ----------------------------------------------------- (1) 段间 reward 差异显著 vs random partition
def test_e20_reward_separation_significant_vs_random():
    X, _, reward = _make(seed=2)
    Z = S.standardize(X)
    fit = S.kmeans(Z, K, rng=random.Random(7))
    eta2 = S.reward_separation(fit["labels"], reward)
    assert eta2 > 0.7, eta2                             # discovered segments explain most reward variance
    # random partition explains ~0 of the reward variance (the non-trivial control).
    rng = random.Random(321)
    rand_labels = [rng.randrange(K) for _ in X]
    eta2_rand = S.reward_separation(rand_labels, reward)
    assert eta2_rand < 0.05, eta2_rand
    assert eta2 > 10.0 * max(eta2_rand, 1e-3), (eta2, eta2_rand)


# ------------------------------------------------------- (2) 分段稳定性 (ARI) vs random relabeling
def test_e20_segment_stability_ari_vs_random():
    X, _, _ = _make(seed=3)
    Z = S.standardize(X)
    n = len(Z)
    rng = random.Random(50)
    idx = list(range(n))

    def subsample():
        s = sorted(rng.sample(idx, int(n * 0.8)))
        fit = S.kmeans([Z[i] for i in s], K, rng=random.Random(7))
        return dict(zip(s, fit["labels"]))

    a, b = subsample(), subsample()
    common = sorted(set(a) & set(b))
    assert len(common) > 30
    ari = S.adjusted_rand_index([a[i] for i in common], [b[i] for i in common])
    assert ari > 0.8, ari                               # two independent subsamples agree strongly
    # non-trivial control: ARI of a random relabeling of the same points is ~0.
    full = S.kmeans(Z, K, rng=random.Random(7))["labels"]
    rng2 = random.Random(99)
    rand_relabel = [rng2.randrange(K) for _ in full]
    ari_rand = S.adjusted_rand_index(full, rand_relabel)
    assert abs(ari_rand) < 0.1, ari_rand
    assert ari > 5.0 * max(abs(ari_rand), 1e-2), (ari, ari_rand)


# ------------------------------------------------------------------------ k-means++ convergence + det.
def test_e20_inertia_monotone_nonincreasing():
    X, _, _ = _make(seed=4)
    Z = S.standardize(X)
    fit = S.kmeans(Z, K, rng=random.Random(7))
    trace = fit["inertia_trace"]
    assert len(trace) >= 2
    for earlier, later in zip(trace, trace[1:]):
        assert later <= earlier + 1e-9, (earlier, later)   # Lloyd never increases inertia
    assert fit["inertia"] == trace[-1]


def test_e20_deterministic_under_seed():
    X, _, _ = _make(seed=5)
    Z = S.standardize(X)
    f1 = S.kmeans(Z, K, rng=random.Random(7))
    f2 = S.kmeans(Z, K, rng=random.Random(7))
    assert f1["labels"] == f2["labels"]
    assert f1["inertia"] == f2["inertia"]


def test_e20_input_guards():
    with pytest.raises(ValueError):
        S.kmeans([[1.0, 2.0]], 0)                        # k must be positive
    with pytest.raises(ValueError):
        S.kmeans([], 2)                                  # empty data
    with pytest.raises(ValueError):
        S.kmeans([[1.0]], 2)                             # k > n points
    with pytest.raises(ValueError):
        S.kmeans([[1.0, 2.0], [3.0]], 1)                 # ragged matrix
    with pytest.raises(ValueError):
        S.rfm_features([])                               # no events
    with pytest.raises(ValueError):
        S.adjusted_rand_index([0, 1], [0])              # length mismatch
    with pytest.raises(ValueError):
        S.reward_separation([0, 1], [1.0])              # length mismatch
