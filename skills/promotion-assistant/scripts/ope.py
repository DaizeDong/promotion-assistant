#!/usr/bin/env python3
"""R10 / E21 — off-policy evaluation (OPE) for the bandit (ARCHITECTURE.md sec 7.4).

The logs are collected by the *old* (behavior) policy, so the raw on-log reward average estimates
V(pi_behavior), NOT the value of a candidate target policy you want to ship. Reading the log
average as if it were the target policy's value is the classic selection-bias trap that sec 7.4
warns about. To evaluate / pre-flight a new policy on historical data without going live you must
de-bias with the logged propensity p_a (which `bandit.select` already records per decision).

This module implements three estimators over logged decisions
``{arm_id, reward in [0,1], propensity_p>0}`` plus a target policy ``{arm_id: prob}``:

  * IPS   — inverse propensity scoring: unbiased but high variance.
  * SNIPS — self-normalized IPS: tiny bias, materially lower variance.
  * DR    — doubly robust: a direct reward model q_hat + an IPS correction. *Consistent if EITHER*
            the propensities OR the reward model is right, and lower variance than IPS when q_hat
            is decent. `clipped_ips` trades a little bias for bounded variance under extreme weights.

Pure stdlib, deterministic. Red before this file existed; green after. Mutation-killable: break the
1/p weighting and the de-bias / variance assertions in tests/test_ope_e21.py go red.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence


def _validate_policy(policy: Dict[str, float]) -> Dict[str, float]:
    if not policy:
        raise ValueError("target policy must be a non-empty {arm_id: prob} map")
    s = 0.0
    for a, p in policy.items():
        if p < 0:
            raise ValueError(f"target policy prob for {a!r} is negative: {p}")
        s += p
    if s <= 0:
        raise ValueError("target policy probabilities sum to <= 0")
    # normalize defensively so callers may pass unnormalized weights
    return {a: p / s for a, p in policy.items()}


def _record_fields(rec: dict):
    """Extract (arm_id, reward, behavior_propensity) with hard guards (sec 7.4 completeness)."""
    arm = rec.get("arm_id")
    if arm is None:
        raise ValueError("logged decision missing arm_id")
    if "reward" not in rec or rec["reward"] is None:
        raise ValueError(f"logged decision for arm {arm!r} missing reward")
    p = rec.get("propensity_p")
    if p is None:
        # exactly the failure sec 7.4 calls out: no propensity -> off-policy eval is impossible
        raise ValueError(f"logged decision for arm {arm!r} missing propensity_p (OPE impossible)")
    p = float(p)
    if not (p > 0.0):
        raise ValueError(f"propensity_p must be > 0 for OPE (got {p} for arm {arm!r})")
    r = float(rec["reward"])
    return arm, r, p


def importance_weights(records: Sequence[dict], target_policy: Dict[str, float],
                       *, clip: Optional[float] = None) -> List[float]:
    """w_i = pi_target(a_i) / pi_behavior(a_i), optionally capped at ``clip``."""
    pe = _validate_policy(target_policy)
    out = []
    for rec in records:
        arm, _r, p = _record_fields(rec)
        w = pe.get(arm, 0.0) / p
        if clip is not None and w > clip:
            w = clip
        out.append(w)
    return out


def naive_value(records: Sequence[dict]) -> float:
    """The *wrong* estimator: plain on-log reward mean (estimates V(behavior), not V(target))."""
    rs = [_record_fields(r)[1] for r in records]
    return sum(rs) / len(rs) if rs else 0.0


def ips(records: Sequence[dict], target_policy: Dict[str, float],
        *, clip: Optional[float] = None) -> float:
    """Inverse-propensity-scoring value estimate of the target policy. Unbiased when clip is None."""
    if not records:
        return 0.0
    w = importance_weights(records, target_policy, clip=clip)
    rs = [_record_fields(r)[1] for r in records]
    return sum(wi * ri for wi, ri in zip(w, rs)) / len(records)


def clipped_ips(records: Sequence[dict], target_policy: Dict[str, float], clip: float) -> float:
    """IPS with weights capped at ``clip`` — bounded variance under extreme propensity at small bias."""
    return ips(records, target_policy, clip=clip)


def snips(records: Sequence[dict], target_policy: Dict[str, float],
          *, clip: Optional[float] = None) -> float:
    """Self-normalized IPS: sum(w r)/sum(w). Slightly biased, materially lower variance than IPS."""
    if not records:
        return 0.0
    w = importance_weights(records, target_policy, clip=clip)
    rs = [_record_fields(r)[1] for r in records]
    sw = sum(w)
    if sw <= 0:
        return 0.0
    return sum(wi * ri for wi, ri in zip(w, rs)) / sw


def fit_q_hat(records: Sequence[dict]) -> Dict[str, float]:
    """Direct-method reward model: empirical mean logged reward per arm (the simplest q_hat)."""
    agg: Dict[str, List[float]] = {}
    for rec in records:
        arm, r, _p = _record_fields(rec)
        agg.setdefault(arm, []).append(r)
    return {a: (sum(v) / len(v) if v else 0.0) for a, v in agg.items()}


def dr(records: Sequence[dict], target_policy: Dict[str, float],
       q_hat, *, clip: Optional[float] = None) -> float:
    """Doubly-robust estimate.

    V_DR = mean_i [ DM_i + w_i (r_i - q_hat(a_i)) ],  DM_i = sum_a pi_target(a) q_hat(a).

    Consistent if EITHER the propensities OR q_hat are correct. ``q_hat`` may be a dict
    {arm: predicted_reward} or a callable arm -> predicted_reward.
    """
    if not records:
        return 0.0
    pe = _validate_policy(target_policy)
    q = (q_hat.get if isinstance(q_hat, dict) else q_hat)  # type: Callable

    def qv(a):
        try:
            val = q(a)
        except Exception:
            val = None
        return float(val) if val is not None else 0.0

    dm = sum(pe[a] * qv(a) for a in pe)  # direct-method baseline (same for every record here)
    w = importance_weights(records, target_policy, clip=clip)
    total = 0.0
    for wi, rec in zip(w, records):
        arm, r, _p = _record_fields(rec)
        total += dm + wi * (r - qv(arm))
    return total / len(records)


def on_policy_value(true_means: Dict[str, float], target_policy: Dict[str, float]) -> float:
    """Ground-truth value of the target policy given true per-arm reward means (for tests/oracle)."""
    pe = _validate_policy(target_policy)
    return sum(pe.get(a, 0.0) * true_means.get(a, 0.0) for a in pe)
