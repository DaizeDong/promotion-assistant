#!/usr/bin/env python3
"""L3 deliverability-driven auto-throttle — the ROADMAP "Planned" capability:

    "Mailbox-pool warmup + inbox-placement probe -> deliverability-driven auto-throttle"

The base throttle (`throttle.py`) reacts to *transport* signals (429 / cooldown / day-cap /
warmup level). It is BLIND to whether messages actually land in the inbox. A campaign can stay
well under every rate limit yet quietly rot in spam folders — at which point the correct action
is to *cut send volume* and let reputation recover, not to keep blasting.

This module closes that gap deterministically (pure stdlib, no network):

  1. `placement_rate(probe)`         seed-account probe outcomes -> measured inbox-placement rate.
  2. `placement_multiplier(rate)`    inbox rate -> a send-rate multiplier in [0,1], with a HARD
                                     pause (0.0) below a floor and full throughput (1.0) when
                                     healthy; monotone non-decreasing in between.
  3. `warmup_ramp(age_days, ...)`    per-mailbox volume ceiling that ramps with mailbox age (a
                                     fresh mailbox may not blast at the steady-state cap).
  4. `recommend_cap(...)`            combine the two constraints with the configured base cap:
                                     min(steady, warmup_ceiling) * placement_multiplier.

Everything is deterministic and config-driven (no hardcoded vendor numbers); the acceptance
test (E22) asserts the deliverability signal is load-bearing vs a placement-blind control.
"""
from __future__ import annotations

from typing import Iterable

_PLACEMENTS = ("inbox", "spam", "missing")


def placement_rate(probe) -> float:
    """Inbox-placement rate from a seed-account probe.

    `probe` is either a list of outcome strings (each in inbox/spam/missing) OR a dict of
    counts {"inbox": n, "spam": n, "missing": n}. Returns inbox / total in [0, 1].
    """
    if isinstance(probe, dict):
        counts = {k: float(probe.get(k, 0)) for k in _PLACEMENTS}
    else:
        seq = list(probe)
        counts = {k: 0.0 for k in _PLACEMENTS}
        for o in seq:
            if o not in counts:
                raise ValueError("unknown placement outcome %r (allowed: %s)" % (o, _PLACEMENTS))
            counts[o] += 1.0
    total = sum(counts.values())
    if total <= 0:
        raise ValueError("empty deliverability probe (no seed-account observations)")
    for k, v in counts.items():
        if v < 0:
            raise ValueError("negative count for %r" % k)
    return counts["inbox"] / total


def placement_multiplier(inbox_rate: float, *, healthy: float = 0.90,
                         floor: float = 0.50) -> float:
    """Map an inbox-placement rate to a send-rate multiplier in [0, 1].

      rate >= healthy  -> 1.0   (full throughput)
      rate <= floor    -> 0.0   (HARD PAUSE: reputation is degrading, stop sending)
      between          -> linear ramp (monotone non-decreasing)

    `floor`/`healthy` are config knobs, never hardcoded vendor numbers.
    """
    if not (0.0 <= inbox_rate <= 1.0):
        raise ValueError("inbox_rate must be in [0,1], got %r" % inbox_rate)
    if not (0.0 <= floor < healthy <= 1.0):
        raise ValueError("require 0<=floor<healthy<=1, got floor=%r healthy=%r" % (floor, healthy))
    if inbox_rate >= healthy:
        return 1.0
    if inbox_rate <= floor:
        return 0.0
    return (inbox_rate - floor) / (healthy - floor)


def warmup_ramp(age_days: float, *, start: float = 20.0, daily_growth: float = 1.5,
                steady: float = 500.0) -> float:
    """Per-mailbox daily volume ceiling that ramps with mailbox age.

    Day 0 a fresh mailbox may send `start`; each elapsed day multiplies the ceiling by
    `daily_growth`, capped at the `steady`-state ceiling. Monotone non-decreasing in age.
    A fresh mailbox therefore CANNOT immediately blast at the steady cap — that is the whole
    point of pool warmup (and what a "no warmup" control gets wrong).
    """
    if age_days < 0:
        raise ValueError("age_days must be >= 0, got %r" % age_days)
    if start <= 0 or steady <= 0 or daily_growth < 1.0:
        raise ValueError("require start>0, steady>0, daily_growth>=1")
    ceil = start * (daily_growth ** age_days)
    return min(float(steady), float(ceil))


def recommend_cap(base_cap: float, *, inbox_rate: float, mailbox_age_days: float,
                  healthy: float = 0.90, floor: float = 0.50,
                  warmup_start: float = 20.0, warmup_growth: float = 1.5,
                  warmup_steady: float = 500.0) -> float:
    """Deliverability-driven send ceiling for ONE mailbox this cycle.

        cap = min(base_cap, warmup_ceiling(age)) * placement_multiplier(inbox_rate)

    Both constraints can bind: a fresh mailbox is warmup-limited; degraded placement scales the
    whole thing down (to zero below the floor). This is the auto-throttle the base throttle
    cannot do on its own because it never observes inbox placement.
    """
    if base_cap < 0:
        raise ValueError("base_cap must be >= 0")
    warm = warmup_ramp(mailbox_age_days, start=warmup_start, daily_growth=warmup_growth,
                       steady=warmup_steady)
    mult = placement_multiplier(inbox_rate, healthy=healthy, floor=floor)
    return min(float(base_cap), warm) * mult


def blind_cap(base_cap: float, *, mailbox_age_days: float = 0.0, **_ignored) -> float:
    """Placement-BLIND control: the old behavior — full base cap regardless of inbox placement
    or mailbox age. Used by the acceptance test to prove the deliverability signal is
    load-bearing (the aware controller must throttle where this one does not)."""
    if base_cap < 0:
        raise ValueError("base_cap must be >= 0")
    return float(base_cap)


class DeliverabilityController:
    """Convenience wrapper holding the config knobs for a mailbox pool."""

    def __init__(self, *, base_cap: float, healthy: float = 0.90, floor: float = 0.50,
                 warmup_start: float = 20.0, warmup_growth: float = 1.5,
                 warmup_steady: float = 500.0):
        self.base_cap = float(base_cap)
        self.healthy = float(healthy)
        self.floor = float(floor)
        self.warmup_start = float(warmup_start)
        self.warmup_growth = float(warmup_growth)
        self.warmup_steady = float(warmup_steady)

    def cap_for(self, *, probe, mailbox_age_days: float) -> dict:
        rate = placement_rate(probe)
        cap = recommend_cap(self.base_cap, inbox_rate=rate, mailbox_age_days=mailbox_age_days,
                            healthy=self.healthy, floor=self.floor, warmup_start=self.warmup_start,
                            warmup_growth=self.warmup_growth, warmup_steady=self.warmup_steady)
        return {"inbox_rate": rate, "recommended_cap": cap,
                "paused": cap <= 0.0,
                "warmup_ceiling": warmup_ramp(mailbox_age_days, start=self.warmup_start,
                                              daily_growth=self.warmup_growth,
                                              steady=self.warmup_steady),
                "placement_multiplier": placement_multiplier(rate, healthy=self.healthy,
                                                             floor=self.floor)}
