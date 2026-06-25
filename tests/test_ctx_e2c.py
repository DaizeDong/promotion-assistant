"""E2c (R1): contextual bandit (LinUCB) — per-segment regret beats a context-free baseline.

Pins a NEW capability that E1-E12 / batch-1 (deeper roadmap) / batch-2 (E19 seqtest) / batch-3
(E21 OPE) did NOT cover: ARCHITECTURE.md sec 7.1 stage-3. When the optimal arm DEPENDS on the
audience segment, a context-free bandit (the existing Beta-TS in scripts/bandit.py) can only learn
one global winner and is wrong on every segment whose local optimum differs -> linear per-segment
regret. LinUCB puts the segment on the feature side (theta . phi(segment, arm)) and learns the
per-segment optimum.

Non-triviality is proved by TWO controls that share LinUCB's algorithm but lack context:
  (1) the pooled Beta-TS bandit, and
  (2) a context-BLIND LinUCB (blind_features drops the segment block).
Both must suffer ~linear regret while context-aware LinUCB's regret is far lower; this isolates the
win to *context*, not to "LinUCB is just a better optimizer". Mutation-killable: break the feature
builder (drop the segment one-hot) or the A/b update and the context win collapses.

Deterministic (seeded RNG), pure stdlib. Red before scripts/ctxbandit.py existed; green after.
"""
import random

from scripts import ctxbandit as C
from scripts.bandit import Bandit


# 3 segments x 3 arms. The optimal arm is DIFFERENT in each segment (the case context-free loses on).
# rows = segment, cols = arm.  diag is the per-segment optimum (0.85); off-diag low (0.15).
TRUE = [
    [0.85, 0.15, 0.15],   # segment 0 -> arm 0 best
    [0.15, 0.85, 0.15],   # segment 1 -> arm 1 best
    [0.15, 0.15, 0.85],   # segment 2 -> arm 2 best
]
N_SEG, N_ARM = 3, 3
ROUNDS = 1200


def _opt(seg):
    row = TRUE[seg]
    return max(range(N_ARM), key=lambda a: row[a])


def _bernoulli(rng, p):
    return 1.0 if rng.random() < p else 0.0


def _run_ctx(alpha=1.0, feature_fn=None, seed=7):
    rng = random.Random(seed)
    cb = C.ContextualBandit(N_SEG, N_ARM, alpha=alpha, feature_fn=feature_fn,
                            rng=random.Random(seed + 1))
    regret = 0.0
    tail_correct = {s: [] for s in range(N_SEG)}
    for t in range(ROUNDS):
        seg = rng.randrange(N_SEG)
        arm = cb.select(seg)["arm_id"]
        r = _bernoulli(rng, TRUE[seg][arm])
        cb.update(seg, arm, r)
        regret += TRUE[seg][_opt(seg)] - TRUE[seg][arm]
        if t >= ROUNDS * 3 // 4:
            tail_correct[seg].append(1 if arm == _opt(seg) else 0)
    return cb, regret, tail_correct


def _run_pooled(seed=7):
    """Context-free Beta-TS: ignores the segment, can only chase one global winner."""
    rng = random.Random(seed)
    bnd = Bandit(None, gamma=1.0, rng=random.Random(seed + 2))
    arms = [str(a) for a in range(N_ARM)]
    regret = 0.0
    for _ in range(ROUNDS):
        seg = rng.randrange(N_SEG)
        arm = int(bnd.select(arms, samples_for_propensity=1)["arm_id"])
        r = _bernoulli(rng, TRUE[seg][arm])
        bnd.update(str(arm), r)
        regret += TRUE[seg][_opt(seg)] - TRUE[seg][arm]
    return regret


# ---------------------------------------------------------------- the headline contrast (non-trivial)
def test_e2c_contextual_beats_pooled_and_blind():
    _, r_ctx, _ = _run_ctx(alpha=1.0)
    r_blind = _run_ctx(alpha=1.0, feature_fn=C.blind_features(N_SEG, N_ARM))[1]
    r_pool = _run_pooled()

    # context-aware regret is far below BOTH context-free controls (win attributable to context).
    assert r_ctx < 0.5 * r_blind, (r_ctx, r_blind)
    assert r_ctx < 0.5 * r_pool, (r_ctx, r_pool)
    # the two context-free controls are both near the "always pay 0.70 on 2/3 of rounds" floor:
    # only the global-best arm is ever right, so >= ~ (2/3)*ROUNDS*0.70 regret accrues.
    floor = (2.0 / 3.0) * ROUNDS * 0.70 * 0.6
    assert r_blind > floor and r_pool > floor, (r_blind, r_pool, floor)


def test_e2c_recovers_per_segment_optimum():
    cb, _, tail = _run_ctx(alpha=1.0)
    # learned greedy argmax matches the true per-segment optimum for EVERY segment.
    for s in range(N_SEG):
        assert cb.best_arm(s) == _opt(s), (s, cb.best_arm(s), _opt(s))
        # and in the converged tail it plays the right arm the large majority of the time.
        frac = sum(tail[s]) / max(1, len(tail[s]))
        assert frac > 0.85, (s, frac)


def test_e2c_regret_is_sublinear():
    # average per-round regret in the last quartile << first quartile (learning, not linear).
    rng = random.Random(11)
    cb = C.ContextualBandit(N_SEG, N_ARM, alpha=1.0, rng=random.Random(12))
    first, last = [], []
    for t in range(ROUNDS):
        seg = rng.randrange(N_SEG)
        arm = cb.select(seg)["arm_id"]
        r = _bernoulli(rng, TRUE[seg][arm])
        cb.update(seg, arm, r)
        inst = TRUE[seg][_opt(seg)] - TRUE[seg][arm]
        if t < ROUNDS // 4:
            first.append(inst)
        elif t >= ROUNDS * 3 // 4:
            last.append(inst)
    avg_first = sum(first) / len(first)
    avg_last = sum(last) / len(last)
    assert avg_last < 0.3 * avg_first, (avg_first, avg_last)


def test_e2c_deterministic_under_seed():
    r1 = _run_ctx(seed=99)[1]
    r2 = _run_ctx(seed=99)[1]
    assert r1 == r2


def test_e2c_exploration_bonus_is_load_bearing():
    # The UCB bonus must actually be used: with alpha>0 the A^-1 quadratic-form term is non-zero on a
    # fresh model, so an unseen arm outscores a seen-but-mediocre one (drives exploration).
    fn = C.hybrid_features(N_SEG, N_ARM)
    m = C.LinUCB(fn.dim, alpha=2.0)
    # teach arm 0 in segment 0 a mediocre reward several times.
    for _ in range(5):
        m.update(fn(0, 0), 0.3)
    feats = {a: fn(0, a) for a in range(N_ARM)}
    pick = m.select(feats)["arm_id"]
    assert pick != 0, pick           # exploration prefers the untried arms over the mediocre known one
    # with alpha=0 (pure greedy) the same state exploits the only positive-mean arm instead.
    m0 = C.LinUCB(fn.dim, alpha=0.0)
    for _ in range(5):
        m0.update(fn(0, 0), 0.3)
    assert m0.select(feats)["arm_id"] == 0


def test_e2c_input_guards():
    import pytest
    with pytest.raises(ValueError):
        C.LinUCB(0)
    with pytest.raises(ValueError):
        C.LinUCB(4, alpha=-1.0)
    with pytest.raises(ValueError):
        C.hybrid_features(0, 3)
    fn = C.hybrid_features(N_SEG, N_ARM)
    m = C.LinUCB(fn.dim)
    with pytest.raises(ValueError):
        m.select({})                                   # no candidate arms
    with pytest.raises(ValueError):
        m.update([0.0, 1.0], 1.0)                       # wrong feature dim
