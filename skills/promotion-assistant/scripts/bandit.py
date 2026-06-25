#!/usr/bin/env python3
"""L5 decision layer — Beta Thompson Sampling with optional discounting (non-stationary).

Stage 1 (MVP): Beta-Bernoulli TS — each arm keeps Beta(alpha, beta); sample each, pick argmax;
success -> alpha+=1, failure -> beta+=1. Stage 2 (REQUIRED for promotion): discounted TS —
each round first decays alpha/beta by gamma (~0.95-0.99) so the policy never locks onto a stale
historical optimum (content fatigue / platform changes / seasonality).

Every decision records propensity_p (the sampled-selection probability estimate) + policy_version
so off-policy estimators (IPS/DR) can de-bias later. Reward is supplied by metrics.py (a
multi-objective scalarization with STRONG NEGATIVE terms for ban/spam/unsub), so the bandit
learns to avoid compliance red-lines instead of optimizing pure engagement (anti-Goodhart).

Pure stdlib (random.gauss-free Beta via two Gammas). Deterministic under an injected RNG so the
acceptance gate (E2/E3) can measure regret + drift recovery.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

POLICY_VERSION = "ts-discounted-1"


def _gamma_sample(rng, k, theta=1.0):
    # Marsaglia-Tsang for k>=1; boost for k<1.
    if k < 1:
        u = rng.random()
        return _gamma_sample(rng, k + 1, theta) * (u ** (1.0 / k))
    d = k - 1.0 / 3.0
    c = 1.0 / (9.0 * d) ** 0.5
    while True:
        x = rng.gauss(0, 1)
        v = (1 + c * x) ** 3
        if v <= 0:
            continue
        u = rng.random()
        if u < 1 - 0.0331 * (x ** 4):
            return d * v * theta
        if __import__("math").log(u) < 0.5 * x * x + d * (1 - v + __import__("math").log(v)):
            return d * v * theta


def _beta_sample(rng, a, b):
    x = _gamma_sample(rng, max(a, 1e-6))
    y = _gamma_sample(rng, max(b, 1e-6))
    return x / (x + y) if (x + y) > 0 else 0.5


class Bandit:
    def __init__(self, state_path: Path, *, gamma=0.97, rng=None, prior=(1.0, 1.0)):
        self.path = state_path
        self.gamma = gamma            # discount for non-stationarity (set 1.0 to disable)
        self.rng = rng or random.Random()
        self.prior = prior
        self.arms = {}
        if state_path and state_path.is_file():
            try:
                self.arms = json.loads(state_path.read_text(encoding="utf-8")).get("arms", {})
            except Exception:
                self.arms = {}

    def _arm(self, arm_id):
        a = self.arms.get(arm_id)
        if not a:
            a = {"arm_id": arm_id, "alpha": self.prior[0], "beta": self.prior[1], "n_pulls": 0}
            self.arms[arm_id] = a
        return a

    def _discount(self):
        if self.gamma >= 1.0:
            return
        for a in self.arms.values():
            a["alpha"] = self.prior[0] + (a["alpha"] - self.prior[0]) * self.gamma
            a["beta"] = self.prior[1] + (a["beta"] - self.prior[1]) * self.gamma

    def select(self, arm_ids, *, samples_for_propensity=200) -> dict:
        """Discount, then Thompson-sample. Returns {arm_id, propensity_p, policy_version}."""
        self._discount()
        for aid in arm_ids:
            self._arm(aid)
        draws = {aid: _beta_sample(self.rng, self.arms[aid]["alpha"], self.arms[aid]["beta"])
                 for aid in arm_ids}
        chosen = max(draws, key=draws.get)
        # Monte-Carlo estimate of P(arm chosen) under current posterior -> propensity for OPE.
        wins = 0
        mc = random.Random(self.rng.random())
        for _ in range(samples_for_propensity):
            best, bestv = None, -1.0
            for aid in arm_ids:
                v = _beta_sample(mc, self.arms[aid]["alpha"], self.arms[aid]["beta"])
                if v > bestv:
                    bestv, best = v, aid
            if best == chosen:
                wins += 1
        prop = max(1e-4, wins / float(samples_for_propensity))
        return {"arm_id": chosen, "propensity_p": prop, "policy_version": POLICY_VERSION}

    def update(self, arm_id, reward):
        """reward in [0,1] (continuous Bernoulli-style). Strong-negative rewards push beta."""
        a = self._arm(arm_id)
        r = max(0.0, min(1.0, float(reward)))
        a["alpha"] += r
        a["beta"] += (1.0 - r)
        a["n_pulls"] += 1

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"policy_version": POLICY_VERSION, "arms": self.arms},
                                        indent=2, ensure_ascii=False), encoding="utf-8")

    def best_arm(self):
        if not self.arms:
            return None
        return max(self.arms.values(), key=lambda a: a["alpha"] / (a["alpha"] + a["beta"]))["arm_id"]
