#!/usr/bin/env python3
"""Delayed-reward prediction (Demeter-style) — ARCHITECTURE.md roadmap R5 -> signal E16.

WHY THIS EXISTS
---------------
metrics.py already CENSORS delayed conversions (an impression still inside its
`conversion_window` with no conversion yet is not counted as a negative). That keeps slow
channels from being under-rewarded, but it is purely *defensive*: while we wait out the
window the bandit gets no early estimate of how good a still-open impression will be.

This module is the *predictive* half required by ARCHITECTURE §7.1 stage-4 ("delayed
conversion ... reward_partial + reward_final"): fit a calibrated model that maps an
impression's EARLY/partial-window signals (opened? clicked? engaged?) to the probability it
will EVENTUALLY convert, so the bandit can act on a calibrated `reward_partial` before the
conversion window closes — exactly the Demeter delayed-reward idea.

The contract that makes it un-gameable (E16): the model's predicted reward, compared against
the *backfilled* true reward once the window closes, must be CALIBRATED (low ECE) and must
DISCRIMINATE (Brier < the predict-the-base-rate baseline, AUC > 0.5). A constant base-rate
predictor is trivially calibrated-in-aggregate but cannot discriminate; a model that overfits
discriminates but is miscalibrated. Demanding both at once is the real bar.

CENSORING-AWARE TRAINING (the architecture-load-bearing piece): a sample that has not
converted yet but is STILL INSIDE its conversion window has an UNKNOWN label — it must NOT be
trained as a negative (that is the very §7.1 stage-4 / metrics.py rule). `fit_delayed` drops
those rows when `censor_aware=True`. Training them as negatives (the bug) biases the model to
under-predict conversion; the test proves the censor-aware fit tracks the true base rate while
the naive one is biased low.

Pure stdlib, deterministic under an injected RNG. No real sends, no network.
"""
from __future__ import annotations

import math
import random
from typing import Iterable

# --------------------------------------------------------------------------- numeric helpers

_CLIP = 30.0  # logit clamp to keep exp() finite


def _sigmoid(z: float) -> float:
    if z >= _CLIP:
        return 1.0
    if z <= -_CLIP:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _logit(p: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, p))
    return math.log(p / (1.0 - p))


# --------------------------------------------------------------------------- censoring resolution

def resolve_label(sample: dict, *, now: float, conversion_window_s: float):
    """Return True/False/None for one sample's eventual-conversion label AS KNOWN AT `now`.

    sample keys: send_ts (float), converted (bool), convert_ts (float|None).
      * converted by now                                  -> True  (observed positive)
      * not converted AND window already elapsed          -> False (observed negative)
      * not converted AND still inside conversion window   -> None  (CENSORED, unknown)
    """
    send_ts = sample["send_ts"]
    converted = bool(sample.get("converted"))
    cts = sample.get("convert_ts")
    if converted and cts is not None and cts <= now:
        return True
    if (now - send_ts) < conversion_window_s:
        return None  # delayed-conversion: outcome not yet revealed -> do NOT train as negative
    return False


# --------------------------------------------------------------------------- logistic model

class LogisticReward:
    """Tiny L2-regularized logistic regression (batch gradient descent). Deterministic."""

    def __init__(self, dim: int, *, l2: float = 1e-3):
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim
        self.l2 = l2
        self.w = [0.0] * dim
        self.b = 0.0
        self.loss_trace: list[float] = []

    def _z(self, x):
        return self.b + sum(wi * xi for wi, xi in zip(self.w, x))

    def predict_proba(self, x) -> float:
        if len(x) != self.dim:
            raise ValueError("feature dim mismatch")
        return _sigmoid(self._z(x))

    def fit(self, X, y, *, lr: float = 0.3, epochs: int = 400):
        if not X:
            raise ValueError("no training rows")
        if len(X) != len(y):
            raise ValueError("X / y length mismatch")
        n = len(X)
        for x in X:
            if len(x) != self.dim:
                raise ValueError("feature dim mismatch")
        for _ in range(epochs):
            gw = [0.0] * self.dim
            gb = 0.0
            loss = 0.0
            for x, yi in zip(X, y):
                p = _sigmoid(self._z(x))
                err = p - yi
                for j in range(self.dim):
                    gw[j] += err * x[j]
                gb += err
                # binary cross-entropy
                pp = min(1.0 - 1e-12, max(1e-12, p))
                loss += -(yi * math.log(pp) + (1 - yi) * math.log(1 - pp))
            for j in range(self.dim):
                gw[j] = gw[j] / n + self.l2 * self.w[j]
                self.w[j] -= lr * gw[j]
            self.b -= lr * (gb / n)
            self.loss_trace.append(loss / n)
        return self


def fit_delayed(samples: Iterable[dict], *, now: float, conversion_window_s: float,
                censor_aware: bool = True, l2: float = 1e-3, lr: float = 0.3,
                epochs: int = 400) -> LogisticReward:
    """Fit a LogisticReward on partial-window features -> eventual conversion.

    Each sample: {"features": [..], "send_ts", "converted", "convert_ts"}.
    censor_aware=True drops rows whose label is still censored at `now` (the correct §7.1
    behaviour). censor_aware=False trains censored rows as NEGATIVES (the bug under test).
    """
    samples = list(samples)
    if not samples:
        raise ValueError("no samples")
    dim = len(samples[0]["features"])
    X, y = [], []
    for s in samples:
        lab = resolve_label(s, now=now, conversion_window_s=conversion_window_s)
        if lab is None:
            if censor_aware:
                continue                      # unknown outcome -> excluded from training
            lab = False                       # BUG path: treat still-open as a negative
        X.append(list(s["features"]))
        y.append(1.0 if lab else 0.0)
    if not X:
        raise ValueError("no resolvable training rows")
    return LogisticReward(dim, l2=l2).fit(X, y, lr=lr, epochs=epochs)


def predict_reward(model: LogisticReward, features, conversion_value: float = 1.0) -> float:
    """reward_partial = P(eventual conversion) * conversion_value (Demeter early estimate)."""
    if conversion_value < 0:
        raise ValueError("conversion_value must be >= 0")
    return model.predict_proba(features) * conversion_value


# --------------------------------------------------------------------------- calibration metrics

def expected_calibration_error(probs, outcomes, *, bins: int = 10) -> float:
    """ECE: sum over equal-width bins of (bin_weight * |mean_pred - mean_outcome|)."""
    if len(probs) != len(outcomes):
        raise ValueError("probs / outcomes length mismatch")
    if not probs:
        raise ValueError("empty input")
    if bins <= 0:
        raise ValueError("bins must be positive")
    n = len(probs)
    acc = [[] for _ in range(bins)]
    for p, o in zip(probs, outcomes):
        idx = min(bins - 1, int(p * bins))
        acc[idx].append((p, o))
    ece = 0.0
    for cell in acc:
        if not cell:
            continue
        mp = sum(p for p, _ in cell) / len(cell)
        mo = sum(o for _, o in cell) / len(cell)
        ece += (len(cell) / n) * abs(mp - mo)
    return ece


def brier_score(probs, outcomes) -> float:
    if len(probs) != len(outcomes):
        raise ValueError("probs / outcomes length mismatch")
    if not probs:
        raise ValueError("empty input")
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def auc(probs, outcomes) -> float:
    """Mann-Whitney AUC (rank-based). Returns 0.5 if a class is absent."""
    pos = [p for p, o in zip(probs, outcomes) if o >= 0.5]
    neg = [p for p, o in zip(probs, outcomes) if o < 0.5]
    if not pos or not neg:
        return 0.5
    wins = 0.0
    for pp in pos:
        for pn in neg:
            if pp > pn:
                wins += 1.0
            elif pp == pn:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def calibration_slope(probs, outcomes, *, epochs: int = 500, lr: float = 0.3) -> float:
    """Slope of a 1-D logistic recalibration outcome ~ sigmoid(a + slope*logit(p)).

    slope ~ 1 => well calibrated; slope < 1 => over-confident; slope > 1 => under-confident.
    """
    X = [[_logit(p)] for p in probs]
    y = [float(o) for o in outcomes]
    m = LogisticReward(1, l2=0.0).fit(X, y, lr=lr, epochs=epochs)
    return m.w[0]


__all__ = [
    "resolve_label", "LogisticReward", "fit_delayed", "predict_reward",
    "expected_calibration_error", "brier_score", "auc", "calibration_slope",
]
