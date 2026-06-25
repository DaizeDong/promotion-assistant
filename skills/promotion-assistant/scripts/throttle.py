#!/usr/bin/env python3
"""L3 throttle controller — token-bucket + AIMD + warmup state machine + human jitter.

Per (account x platform x action). Capacity is the platform's *observed* safe value times a
margin (50-70%), never a hardcoded vendor number. On a 429/warning the cap halves and a
cooldown begins (multiplicative decrease); after stable days it grows additively (x1.2).
A warmup state machine forbids level-skipping for fresh accounts.

Anti-pattern guarded: "random delay == safe" is FALSE — jitter only changes timing, not
pattern. So this layer also exposes session-density / navigation-variance hooks that the
provider layer must honor (here we model density + lognormal inter-action gaps).

State persists in metrics/throttle-state.json. Pure-Python, deterministic under an injected
clock + RNG seed so the acceptance gate (E4) can assert "0 over-limit, backoff correct".
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

WARMUP_STAGES = ["browse", "like", "follow_comment", "nonpromo_post", "normal"]
# actions each warmup stage is allowed to perform (no skipping)
STAGE_ACTIONS = {
    "browse": set(),
    "like": {"like"},
    "follow_comment": {"like", "follow", "comment"},
    "nonpromo_post": {"like", "follow", "comment", "post_nonpromo"},
    "normal": {"like", "follow", "comment", "post_nonpromo", "post", "dm"},
}


class Throttle:
    def __init__(self, state_path: Path, *, clock=None, rng=None):
        self.path = state_path
        self.clock = clock or (lambda: __import__("time").time())
        self.rng = rng or random.Random()
        self.state = {}
        if state_path.is_file():
            try:
                self.state = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                self.state = {}

    # ---- persistence ----
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _key(self, account, platform, action):
        return "%s|%s|%s" % (account, platform, action)

    def _bucket(self, account, platform, action, policy):
        k = self._key(account, platform, action)
        b = self.state.get(k)
        if not b:
            cap = float(policy.get("day_cap", 10))
            b = {"cap": cap, "base_cap": cap, "tokens": cap, "last_refill": self.clock(),
                 "cooldown_until": 0.0, "stable_since": self.clock(), "last_action": 0.0}
            self.state[k] = b
        return b

    # ---- warmup ----
    def warmup_allows(self, account_stage: str, action: str) -> bool:
        stage = account_stage if account_stage in STAGE_ACTIONS else "browse"
        return action in STAGE_ACTIONS[stage]

    # ---- core decision ----
    def allow(self, account, platform, action, policy, *, account_stage="normal") -> tuple:
        """Return (ok, reason, wait_seconds). Consumes a token if ok."""
        if action == "publish":      # normalize the dispatch verb to the throttle vocabulary
            action = "post"
        if not self.warmup_allows(account_stage, action):
            return (False, "warmup: stage %r forbids %r" % (account_stage, action), 0.0)

        b = self._bucket(account, platform, action, policy)
        now = self.clock()

        if now < b["cooldown_until"]:
            return (False, "in cooldown", b["cooldown_until"] - now)

        # refill daily bucket
        day = 86400.0
        elapsed = now - b["last_refill"]
        if elapsed >= day:
            b["tokens"] = b["cap"]
            b["last_refill"] = now

        # human pacing: enforce min gap with lognormal jitter between actions
        min_gap = float(policy.get("min_gap_sec", 0))
        if min_gap and b["last_action"]:
            need = min_gap * self._jitter()
            since = now - b["last_action"]
            if since < need:
                return (False, "min-gap pacing", need - since)

        if b["tokens"] < 1.0:
            return (False, "daily cap reached", day - elapsed)

        b["tokens"] -= 1.0
        b["last_action"] = now
        return (True, "ok", 0.0)

    def _jitter(self) -> float:
        """Lognormal multiplier ~ centered near 1.0 (never fixed/uniform)."""
        return math.exp(self.rng.gauss(0.0, 0.35))

    # ---- AIMD feedback ----
    def on_throttle_signal(self, account, platform, action, policy):
        """429 / warning / forced re-auth -> multiplicative decrease + cooldown."""
        b = self._bucket(account, platform, action, policy)
        backoff = policy.get("backoff", {})
        factor = float(backoff.get("factor", 0.5))
        cooldown_h = float(backoff.get("cooldown_h", 24))
        b["cap"] = max(1.0, b["cap"] * factor)
        b["tokens"] = min(b["tokens"], b["cap"])
        b["cooldown_until"] = self.clock() + cooldown_h * 3600.0
        b["stable_since"] = self.clock()

    def on_stable_period(self, account, platform, action, policy):
        """Additive/geometric increase after a stable window, capped at base_cap ceiling."""
        b = self._bucket(account, platform, action, policy)
        ramp = policy.get("rampup", {})
        stable_days = float(ramp.get("stable_days", 7))
        factor = float(ramp.get("factor", 1.2))
        if self.clock() - b["stable_since"] >= stable_days * 86400.0:
            ceil = b["base_cap"] * float(policy.get("max_growth_mult", 3.0))
            b["cap"] = min(ceil, b["cap"] * factor)
            b["stable_since"] = self.clock()
