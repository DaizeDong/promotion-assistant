#!/usr/bin/env python3
"""L5 causal layer — always-valid sequential A/B test (R8 / E19).

The bandit (bandit.py) optimizes *decisions* (find the best arm fast). But when a human asks
"is copy A *actually* better than copy B?" and wants to watch the result roll in, a fixed-sample
A/B test read with continuous peeking inflates the Type-I (false-positive) error from the nominal
alpha to 20-30% (you stop the moment p<0.05 by chance). ARCHITECTURE.md sec 7.3 mandates a separate
**always-valid** test for reportable causal conclusions, so peeking is safe by construction.

This module implements a two-sided **betting e-process** for the equality of two Bernoulli reward
streams (E[reward_A] == E[reward_B]). It is anytime-valid: by Ville's inequality, the probability
that the e-value EVER crosses 1/alpha under the null is <= alpha, no matter how often you peek.

Construction (pure stdlib, no numpy):
  - For each paired observation d_t = a_t - b_t in {-1, 0, +1}, run two one-sided e-processes,
    each at level alpha/2 (Bonferroni union -> two-sided level alpha):
      wealth_pos bets E[d] > 0 (copy A better): wealth *= (1 + lam * d_t), lam in [0, lam_max]
      wealth_neg bets E[d] < 0 (copy B better): wealth *= (1 + lam * (-d_t)), lam in [0, lam_max]
  - lam_t is chosen *predictably* (before seeing d_t) by ONS, projected to [0, lam_max], with
    lam_max < 1 so 1 + lam*d stays > 0 for d in [-1, 1] (wealth never goes non-positive).
  - Under H0 each factor is a supermartingale (E[1 + lam*d | past] = 1 + lam*E[d] <= 1), so the
    running max wealth is a valid e-process and reject-threshold 1/(alpha/2) = 2/alpha controls the
    one-sided error at alpha/2 at ANY stopping time.

Decision: reject H0 the first time max(wealth_pos, wealth_neg) >= 2/alpha; the crossing process
gives the direction ("A" or "B"). Stopping is sticky (once rejected, stays rejected).
"""
from __future__ import annotations

from dataclasses import dataclass, field

_LAM_EPS = 1e-6


def _ons_step(lam: float, A: float, b: float, payoff: float, lam_max: float):
    """One predictable ONS update for a one-sided betting martingale.

    payoff is the realized (1-D) bet payoff for this step using the *current* (predictable) lam.
    Returns (new_lam, new_A, new_b) projected to [0, lam_max]. lam stays >= 0 (one-sided).
    """
    factor = 1.0 + lam * payoff  # > 0 by lam in [0, lam_max], payoff in [-1, 1], lam_max < 1
    g = payoff / factor
    A = A + g * g
    b = b + g
    new_lam = b / (A + 1.0)
    if new_lam < 0.0:
        new_lam = 0.0
    elif new_lam > lam_max:
        new_lam = lam_max
    return new_lam, A, b


@dataclass
class SequentialABTest:
    """Always-valid two-sided sequential test of E[reward_A] == E[reward_B].

    Feed paired Bernoulli (or [0,1]-bounded) rewards via update(); read .reject / .direction /
    .e_value at any time. Safe to peek every step.
    """

    alpha: float = 0.05
    n: int = 0
    _lam_max: float = field(default=1.0 - 1e-3, init=False)
    # positive-direction (A>B) e-process state
    _w_pos: float = field(default=1.0, init=False)
    _lam_pos: float = field(default=0.0, init=False)
    _A_pos: float = field(default=0.0, init=False)
    _b_pos: float = field(default=0.0, init=False)
    # negative-direction (B>A) e-process state
    _w_neg: float = field(default=1.0, init=False)
    _lam_neg: float = field(default=0.0, init=False)
    _A_neg: float = field(default=0.0, init=False)
    _b_neg: float = field(default=0.0, init=False)
    # running maxima (e-process = running max of the supermartingale wealth)
    _emax_pos: float = field(default=1.0, init=False)
    _emax_neg: float = field(default=1.0, init=False)
    reject: bool = field(default=False, init=False)
    direction: str | None = field(default=None, init=False)

    def __post_init__(self):
        if not (0.0 < self.alpha < 1.0):
            raise ValueError("alpha must be in (0, 1)")

    @property
    def threshold(self) -> float:
        """One-sided reject threshold = 1 / (alpha/2) = 2/alpha (two-sided level alpha)."""
        return 2.0 / self.alpha

    @property
    def e_value(self) -> float:
        """Two-sided e-value = max of the two one-sided running maxima."""
        return max(self._emax_pos, self._emax_neg)

    @property
    def p_value(self) -> float:
        """Anytime-valid p-value = min(1, 1/e_value). Monotone non-increasing as evidence grows."""
        e = self.e_value
        return 1.0 if e <= 0.0 else min(1.0, 1.0 / e)

    def update(self, a_reward: float, b_reward: float) -> dict:
        """Observe one paired (reward_A, reward_B) and advance both e-processes.

        Returns a snapshot dict {n, e_value, p_value, reject, direction, threshold}.
        Bets use the PREDICTABLE lam fixed before this observation (validity requirement);
        lam is then updated for the next step.
        """
        d = float(a_reward) - float(b_reward)
        if d < -1.0 or d > 1.0:
            raise ValueError("rewards must be in [0, 1] so the paired diff stays in [-1, 1]")
        self.n += 1

        # positive process bets payoff = +d ; negative process bets payoff = -d
        self._w_pos *= (1.0 + self._lam_pos * d)
        self._w_neg *= (1.0 + self._lam_neg * (-d))
        if self._w_pos > self._emax_pos:
            self._emax_pos = self._w_pos
        if self._w_neg > self._emax_neg:
            self._emax_neg = self._w_neg

        # predictable ONS update for the NEXT step
        self._lam_pos, self._A_pos, self._b_pos = _ons_step(
            self._lam_pos, self._A_pos, self._b_pos, d, self._lam_max)
        self._lam_neg, self._A_neg, self._b_neg = _ons_step(
            self._lam_neg, self._A_neg, self._b_neg, -d, self._lam_max)

        # sticky two-sided reject (first crossing wins the direction)
        if not self.reject:
            thr = self.threshold
            if self._emax_pos >= thr and self._emax_pos >= self._emax_neg:
                self.reject = True
                self.direction = "A"
            elif self._emax_neg >= thr:
                self.reject = True
                self.direction = "B"
        return self.snapshot()

    def snapshot(self) -> dict:
        return {
            "n": self.n,
            "e_value": self.e_value,
            "p_value": self.p_value,
            "reject": self.reject,
            "direction": self.direction,
            "threshold": self.threshold,
        }


def run_sequential_ab(pairs, alpha: float = 0.05) -> dict:
    """Convenience: run a full paired stream, peeking every step, return the final snapshot.

    `pairs` is an iterable of (a_reward, b_reward). Stops early-reporting via the sticky reject
    flag but still consumes the stream (the e-process running max is what matters for validity).
    """
    t = SequentialABTest(alpha=alpha)
    for a, b in pairs:
        t.update(a, b)
    return t.snapshot()
