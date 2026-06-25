#!/usr/bin/env python3
"""L5 stage-3 — contextual bandit (LinUCB) so the optimal arm can depend on context.

ARCHITECTURE.md sec 7.1 stage-3: a context-free bandit treats every (audience-segment x time x
platform-health) combination as an independent arm -> the full Cartesian product is thousands of
sparse arms that never converge ("组合爆炸"). The fix is a linear model f(x, a) = theta . phi(x, a)
that puts the context on the FEATURE side and shares statistical strength across arms, so it learns
a per-segment optimum from far fewer pulls.

This is a disjoint/hybrid LinUCB (Li et al. 2010): keep A = lambda*I (d x d) and b (d); at decision
time theta = A^-1 b and each candidate arm scores theta.x + alpha * sqrt(x^T A^-1 x) (mean +
exploration bonus); after observing reward r for the played feature x: A += x x^T, b += r x.

`hybrid_features` builds phi(segment, arm) = [ one-hot(arm) (SHARED across segments, pools strength) ]
                                         ++ [ one-hot(segment x arm) (per-cell deviation) ].
`blind_features` drops the segment block -> a context-BLIND control that collapses to a global-mean
linear bandit; the E2c test uses it (and the existing pooled Beta-TS) to prove the per-segment regret
win comes from *context*, not merely from LinUCB.

Pure stdlib (a tiny Gauss-Jordan inverse for the small d), deterministic under an injected RNG so the
acceptance gate (E2c) can measure per-segment regret + convergence reproducibly.
"""
from __future__ import annotations

import math
import random

POLICY_VERSION = "linucb-1"


# ----------------------------------------------------------------------------- linear algebra (stdlib)
def _identity(d, scale=1.0):
    return [[scale if i == j else 0.0 for j in range(d)] for i in range(d)]


def _inv(mat):
    """Gauss-Jordan inverse of a square matrix (d small; LinUCB A is SPD so this is stable)."""
    n = len(mat)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(mat)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError("singular matrix in LinUCB inverse")
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col]
        a[col] = [x / pv for x in a[col]]
        for r in range(n):
            if r == col:
                continue
            f = a[r][col]
            if f:
                a[r] = [x - f * y for x, y in zip(a[r], a[col])]
    return [row[n:] for row in a]


def _matvec(m, v):
    return [sum(mij * vj for mij, vj in zip(row, v)) for row in m]


def _dot(u, v):
    return sum(a * b for a, b in zip(u, v))


# ----------------------------------------------------------------------------- feature builders
def hybrid_features(n_segments, n_arms):
    """phi(segment, arm) -> shared one-hot(arm) ++ per-(segment,arm) one-hot. dim = K + S*K."""
    if n_segments <= 0 or n_arms <= 0:
        raise ValueError("n_segments and n_arms must be positive")
    dim = n_arms + n_segments * n_arms

    def fn(segment, arm):
        if not (0 <= segment < n_segments) or not (0 <= arm < n_arms):
            raise ValueError("segment/arm out of range")
        x = [0.0] * dim
        x[arm] = 1.0                                   # shared arm dimension (pools across segments)
        x[n_arms + segment * n_arms + arm] = 1.0       # segment-specific deviation
        return x

    fn.dim = dim
    return fn


def blind_features(n_segments, n_arms):
    """Context-BLIND control: phi(segment, arm) = one-hot(arm) only (segment ignored). dim = K."""
    if n_segments <= 0 or n_arms <= 0:
        raise ValueError("n_segments and n_arms must be positive")

    def fn(segment, arm):
        if not (0 <= segment < n_segments) or not (0 <= arm < n_arms):
            raise ValueError("segment/arm out of range")
        x = [0.0] * n_arms
        x[arm] = 1.0
        return x

    fn.dim = n_arms
    return fn


# ----------------------------------------------------------------------------- LinUCB core
class LinUCB:
    def __init__(self, dim, *, alpha=1.0, lam=1.0):
        if dim <= 0:
            raise ValueError("dim must be positive")
        if alpha < 0:
            raise ValueError("alpha (exploration) must be >= 0")
        self.d = dim
        self.alpha = float(alpha)
        self.A = _identity(dim, lam)
        self.b = [0.0] * dim

    def theta(self):
        return _matvec(_inv(self.A), self.b)

    def select(self, arm_feats: dict):
        """arm_feats: {arm_id: feature_vec}. Returns {arm_id, score, propensity_p, policy_version}."""
        if not arm_feats:
            raise ValueError("no candidate arms")
        Ainv = _inv(self.A)
        th = _matvec(Ainv, self.b)
        best, best_score = None, -float("inf")
        for aid, x in arm_feats.items():
            if len(x) != self.d:
                raise ValueError("feature dim mismatch")
            mean = _dot(th, x)
            bonus = self.alpha * math.sqrt(max(0.0, _dot(x, _matvec(Ainv, x))))
            score = mean + bonus
            if score > best_score:
                best_score, best = score, aid
        # LinUCB is deterministic given state -> the chosen arm has propensity 1 (for OPE bookkeeping).
        return {"arm_id": best, "score": best_score, "propensity_p": 1.0,
                "policy_version": POLICY_VERSION}

    def greedy_arm(self, arm_feats: dict):
        """Pure exploitation (alpha=0): argmax theta.x — used to read the learned per-segment optimum."""
        th = self.theta()
        return max(arm_feats, key=lambda a: _dot(th, arm_feats[a]))

    def update(self, feat, reward):
        if len(feat) != self.d:
            raise ValueError("feature dim mismatch")
        r = float(reward)
        for i in range(self.d):
            xi = feat[i]
            if xi:
                self.b[i] += r * xi
                row = self.A[i]
                for j in range(self.d):
                    xj = feat[j]
                    if xj:
                        row[j] += xi * xj


class ContextualBandit:
    """Convenience wrapper: pick over a fixed arm set given an integer segment context."""
    def __init__(self, n_segments, n_arms, *, alpha=1.0, lam=1.0, feature_fn=None, rng=None):
        self.n_segments = n_segments
        self.n_arms = n_arms
        self.feature_fn = feature_fn or hybrid_features(n_segments, n_arms)
        self.model = LinUCB(self.feature_fn.dim, alpha=alpha, lam=lam)
        self.rng = rng or random.Random()

    def _feats(self, segment):
        return {a: self.feature_fn(segment, a) for a in range(self.n_arms)}

    def select(self, segment):
        d = self.model.select(self._feats(segment))
        d["segment"] = segment
        return d

    def update(self, segment, arm, reward):
        self.model.update(self.feature_fn(segment, arm), reward)

    def best_arm(self, segment):
        return self.model.greedy_arm(self._feats(segment))
