#!/usr/bin/env python3
"""L4/L5 — automatic audience segmentation (RFM + k-means) so segments are *discovered*, not hand-typed.

ARCHITECTURE.md treats `audiences.yaml` as a hand-authored, static list of segments. That is brittle:
the analyst must guess the segment boundaries, and the bandit's per-segment context (see ctxbandit.py)
is only as good as those guesses. Roadmap R9 -> signal E20: derive segments from behaviour by building
an RFM (Recency / Frequency / Monetary) feature per user from the raw event log and clustering them, so
the segmentation is data-driven, reproducible, and quantitatively justified ("分段稳定性 + 段间 reward
差异显著").

What lives here (pure stdlib, deterministic under an injected RNG so the E20 gate is replayable):
  * `rfm_features`  — aggregate the append-only event log into one (recency, frequency, monetary) row/user.
  * `standardize`   — column z-score (RFM dims have wildly different scales; k-means is scale-sensitive).
  * `kmeans`        — k-means++ seeding + Lloyd iteration, n_init restarts, returns the lowest-inertia fit
                      with the full monotone-decreasing inertia trace (so convergence is checkable).
  * `adjusted_rand_index` — chance-corrected label agreement, used to measure SEGMENT STABILITY across
                      independent subsamples (a random relabeling scores ~0, so the floor is meaningful).
  * `reward_separation`   — eta^2 = SS_between / SS_total of a per-user reward across the discovered
                      clusters: how much of reward variance the segmentation explains. A random partition
                      explains ~0; real structure explains a lot. This is the "段间 reward 差异显著" half.

The E20 test proves non-triviality with a RANDOM-PARTITION control on both axes (ARI and reward eta^2):
discovered clusters must beat a random split by a wide margin, isolating "real structure found" from
"any partition of K groups". Mutation-killable: break standardize() or the assignment step and both the
recovered-purity and the reward-separation collapse toward the random floor.
"""
from __future__ import annotations

import math
import random

ALGO_VERSION = "rfm-kmeans-1"


# ----------------------------------------------------------------------------- RFM feature extraction
def rfm_features(events, *, now=None, user_key="user", ts_key="ts", value_key="value"):
    """Aggregate an event list into per-user RFM rows.

    events: iterable of dicts, each with a user id, a numeric timestamp, and a numeric value.
    Returns (user_ids, matrix) where matrix[i] = [recency, frequency, monetary] for user_ids[i]:
      recency   = now - last_ts        (smaller = more recently active)
      frequency = number of events
      monetary  = sum of value
    user_ids is sorted for deterministic row order. `now` defaults to the max ts seen.
    """
    agg = {}
    max_ts = None
    for e in events:
        try:
            u = e[user_key]
            ts = float(e[ts_key])
            val = float(e.get(value_key, 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed event {e!r}: {exc}")
        max_ts = ts if max_ts is None else max(max_ts, ts)
        if u not in agg:
            agg[u] = {"last": ts, "n": 0, "sum": 0.0}
        a = agg[u]
        a["last"] = max(a["last"], ts)
        a["n"] += 1
        a["sum"] += val
    if not agg:
        raise ValueError("no events to aggregate")
    ref = max_ts if now is None else float(now)
    users = sorted(agg)
    mat = [[ref - agg[u]["last"], float(agg[u]["n"]), agg[u]["sum"]] for u in users]
    return users, mat


def standardize(matrix):
    """Column-wise z-score. k-means uses Euclidean distance, so unscaled RFM (recency in seconds vs
    frequency in single digits) would let one axis dominate; standardizing makes the dims comparable.
    A zero-variance column is left centred (std treated as 1) instead of dividing by zero."""
    if not matrix:
        raise ValueError("empty matrix")
    d = len(matrix[0])
    if d == 0 or any(len(row) != d for row in matrix):
        raise ValueError("ragged or zero-width matrix")
    n = len(matrix)
    means = [sum(row[j] for row in matrix) / n for j in range(d)]
    stds = []
    for j in range(d):
        var = sum((row[j] - means[j]) ** 2 for row in matrix) / n
        stds.append(math.sqrt(var) if var > 1e-12 else 1.0)
    return [[(row[j] - means[j]) / stds[j] for j in range(d)] for row in matrix]


# ----------------------------------------------------------------------------- k-means (stdlib)
def _sqdist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _kpp_init(X, k, rng):
    """k-means++ seeding: spread initial centroids proportional to squared distance from chosen ones."""
    n = len(X)
    first = rng.randrange(n)
    centroids = [list(X[first])]
    d2 = [_sqdist(x, centroids[0]) for x in X]
    while len(centroids) < k:
        total = sum(d2)
        if total <= 0:                       # all remaining points coincide with a centroid
            centroids.append(list(X[rng.randrange(n)]))
        else:
            target = rng.random() * total
            acc, idx = 0.0, 0
            for i, w in enumerate(d2):
                acc += w
                if acc >= target:
                    idx = i
                    break
            centroids.append(list(X[idx]))
        c = centroids[-1]
        for i, x in enumerate(X):
            nd = _sqdist(x, c)
            if nd < d2[i]:
                d2[i] = nd
    return centroids


def _assign(X, centroids):
    labels = []
    inertia = 0.0
    for x in X:
        best, bd = 0, _sqdist(x, centroids[0])
        for ci in range(1, len(centroids)):
            dd = _sqdist(x, centroids[ci])
            if dd < bd:
                bd, best = dd, ci
        labels.append(best)
        inertia += bd
    return labels, inertia


def _update(X, labels, k):
    d = len(X[0])
    sums = [[0.0] * d for _ in range(k)]
    counts = [0] * k
    for x, lb in zip(X, labels):
        counts[lb] += 1
        row = sums[lb]
        for j in range(d):
            row[j] += x[j]
    cents = []
    for ci in range(k):
        if counts[ci] == 0:
            cents.append(None)               # empty cluster: caller re-seeds it
        else:
            cents.append([s / counts[ci] for s in sums[ci]])
    return cents


def kmeans(X, k, *, rng=None, max_iter=100, n_init=8):
    """k-means++ with n_init restarts; returns the lowest-inertia fit.

    Returns dict: {labels, centroids, inertia, inertia_trace, n_iter, algo_version}.
    inertia_trace is the per-iteration inertia of the winning run (monotone non-increasing).
    Deterministic given `rng` (pass random.Random(seed))."""
    if k <= 0:
        raise ValueError("k must be positive")
    n = len(X)
    if n == 0:
        raise ValueError("empty data")
    if k > n:
        raise ValueError("k cannot exceed number of points")
    d = len(X[0])
    if any(len(row) != d for row in X):
        raise ValueError("ragged feature matrix")
    rng = rng or random.Random()

    best = None
    for _ in range(max(1, n_init)):
        centroids = _kpp_init(X, k, rng)
        trace = []
        labels, inertia = _assign(X, centroids)
        trace.append(inertia)
        for _it in range(max_iter):
            new_c = _update(X, labels, k)
            for ci in range(k):
                if new_c[ci] is None:        # re-seed an emptied cluster at the worst-fit point
                    far = max(range(n), key=lambda i: _sqdist(X[i], centroids[labels[i]]))
                    new_c[ci] = list(X[far])
            centroids = new_c
            new_labels, inertia = _assign(X, centroids)
            trace.append(inertia)
            if new_labels == labels:         # converged: assignments stable
                labels = new_labels
                break
            labels = new_labels
        if best is None or inertia < best["inertia"]:
            best = {"labels": labels, "centroids": centroids, "inertia": inertia,
                    "inertia_trace": trace, "n_iter": len(trace) - 1,
                    "algo_version": ALGO_VERSION}
    return best


# ----------------------------------------------------------------------------- evaluation helpers
def adjusted_rand_index(a, b):
    """Chance-corrected agreement between two labelings of the same points (Hubert & Arabie 1985).
    1.0 = identical up to relabeling; ~0.0 = random; can go negative. Used for segment STABILITY."""
    if len(a) != len(b):
        raise ValueError("labelings must be the same length")
    n = len(a)
    if n == 0:
        raise ValueError("empty labeling")
    ca, cb = sorted(set(a)), sorted(set(b))
    ia = {v: i for i, v in enumerate(ca)}
    ib = {v: i for i, v in enumerate(cb)}
    table = [[0] * len(cb) for _ in range(len(ca))]
    for x, y in zip(a, b):
        table[ia[x]][ib[y]] += 1

    def comb2(x):
        return x * (x - 1) // 2

    sum_ij = sum(comb2(c) for row in table for c in row)
    ai = [sum(row) for row in table]
    bj = [sum(table[i][j] for i in range(len(ca))) for j in range(len(cb))]
    sum_a = sum(comb2(x) for x in ai)
    sum_b = sum(comb2(x) for x in bj)
    total = comb2(n)
    expected = (sum_a * sum_b) / total if total else 0.0
    max_idx = 0.5 * (sum_a + sum_b)
    denom = max_idx - expected
    if abs(denom) < 1e-12:
        return 1.0                            # both trivial (single cluster) -> defined as agreement
    return (sum_ij - expected) / denom


def reward_separation(labels, rewards):
    """eta^2 = SS_between / SS_total of a per-point reward across clusters: the fraction of reward
    variance EXPLAINED by the segmentation. 0 = segments carry no reward signal (random split); ->1 =
    each segment has a sharply distinct reward level. This is the "段间 reward 差异显著" metric."""
    if len(labels) != len(rewards):
        raise ValueError("labels and rewards length mismatch")
    n = len(rewards)
    if n == 0:
        raise ValueError("empty input")
    grand = sum(rewards) / n
    ss_tot = sum((r - grand) ** 2 for r in rewards)
    if ss_tot <= 1e-12:
        return 0.0                            # no reward variance at all -> nothing to explain
    groups = {}
    for lb, r in zip(labels, rewards):
        groups.setdefault(lb, []).append(r)
    ss_between = 0.0
    for vals in groups.values():
        m = sum(vals) / len(vals)
        ss_between += len(vals) * (m - grand) ** 2
    return ss_between / ss_tot


def cluster_purity(pred, truth):
    """Fraction of points whose predicted cluster's majority TRUE label matches their true label —
    a permutation-free way to score recovery of planted clusters."""
    if len(pred) != len(truth):
        raise ValueError("length mismatch")
    n = len(pred)
    if n == 0:
        raise ValueError("empty input")
    by_cluster = {}
    for p, t in zip(pred, truth):
        by_cluster.setdefault(p, {}).setdefault(t, 0)
        by_cluster[p][t] += 1
    correct = sum(max(counts.values()) for counts in by_cluster.values())
    return correct / n
