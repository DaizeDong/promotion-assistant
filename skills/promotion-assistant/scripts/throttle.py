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

import copy
import hashlib
import json
import math
import random
from pathlib import Path
from . import private_storage

WARMUP_STAGES = ["browse", "like", "follow_comment", "nonpromo_post", "normal"]
# actions each warmup stage is allowed to perform (no skipping)
STAGE_ACTIONS = {
    "browse": set(),
    "like": {"like"},
    "follow_comment": {"like", "follow", "comment"},
    "nonpromo_post": {"like", "follow", "comment", "post_nonpromo"},
    "normal": {"like", "follow", "comment", "post_nonpromo", "post", "dm"},
}


def _state_document(payload):
    if payload is None:
        return {'schema_version': 1, 'buckets': {}, 'reservations': {}, 'cooldowns': {}}
    try:
        value = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError('malformed throttle state; preserve it for explicit recovery') from exc
    if not isinstance(value, dict):
        raise ValueError('throttle state must be an object')
    if 'schema_version' not in value:
        value = {'schema_version': 1, 'buckets': value, 'reservations': {}, 'cooldowns': {}}
    if type(value.get('schema_version')) is not int or value['schema_version'] != 1 or not all(
            isinstance(value.get(key), dict) for key in ('buckets', 'reservations', 'cooldowns')):
        raise ValueError('unsupported throttle state schema')
    fields = ('cap', 'base_cap', 'tokens', 'last_refill', 'cooldown_until', 'stable_since', 'last_action')
    for key, bucket in value['buckets'].items():
        if not isinstance(key, str) or not isinstance(bucket, dict):
            raise ValueError('invalid throttle bucket')
        if any(type(bucket.get(field)) not in (int, float) or not math.isfinite(bucket[field])
               or bucket[field] < 0 for field in fields):
            raise ValueError('invalid throttle bucket values')
        if bucket['tokens'] > bucket['cap']:
            raise ValueError('throttle tokens exceed durable capacity')
        if ('period_used' in bucket and (type(bucket['period_used']) not in (int, float)
                or not math.isfinite(bucket['period_used']) or bucket['period_used'] < 0)):
            raise ValueError('invalid throttle period usage')
        if 'usage_known' in bucket and type(bucket['usage_known']) is not bool:
            raise ValueError('invalid throttle usage provenance')
    for key, reservation in value['reservations'].items():
        if (not isinstance(key, str) or not key or not isinstance(reservation, dict)
                or not isinstance(reservation.get('binding'), str)
                or len(reservation['binding']) != 64
                or type(reservation.get('period')) not in (int, float)
                or not math.isfinite(reservation['period']) or reservation['period'] < 0):
            raise ValueError('invalid throttle reservation')
    if any(not isinstance(key, str) or type(until) not in (int, float)
           or not math.isfinite(until) or until < 0 for key, until in value['cooldowns'].items()):
        raise ValueError('invalid throttle cooldown')
    return value


class Throttle:
    def __init__(self, state_path: Path, *, clock=None, rng=None):
        self.path = state_path
        self.clock = clock or (lambda: __import__("time").time())
        self.rng = rng or random.Random()
        payload = private_storage.read_text(state_path, missing=None) if state_path.is_file() else None
        self.state = _state_document(payload)['buckets']
        self._loaded_state = copy.deepcopy(self.state)

    def save(self):
        """Persist an in-memory model only if no other writer changed its loaded state."""
        def merge(previous):
            document = _state_document(previous)
            if document['buckets'] != self._loaded_state:
                raise ValueError('throttle state changed; use durable reserve instead of a stale save')
            document['buckets'] = self.state
            return json.dumps(document, indent=2, sort_keys=True)+'\n', None
        private_storage.update_text(self.path, merge)
        self._loaded_state = copy.deepcopy(self.state)

    def _key(self, account, platform, action):
        return json.dumps([account, platform, action], separators=(',', ':'))

    def _bucket(self, account, platform, action, policy):
        """Reconcile the current policy ceiling without resetting usage or AIMD capacity.

        Lower limits take effect immediately. Raising a limit does not mint tokens
        during the current period; refill remains bounded by both policy and AIMD.
        """
        cap = float(policy.get("day_cap", 10))
        if not math.isfinite(cap) or cap < 0:
            raise ValueError('day_cap must be finite and nonnegative')
        key = self._key(account, platform, action)
        # Read a valid legacy bucket once, preserving its consumed capacity.
        legacy = "%s|%s|%s" % (account, platform, action)
        if key not in self.state and legacy in self.state:
            self.state[key] = self.state.pop(legacy)
        bucket = self.state.get(key)
        if bucket is None:
            bucket = {"cap": cap, "base_cap": cap, "tokens": cap, "last_refill": self.clock(),
                      "cooldown_until": 0.0, "stable_since": self.clock(), "last_action": 0.0,
                      "period_used": 0.0, "usage_known": True}
            self.state[key] = bucket
        else:
            if 'period_used' not in bucket:
                # Clipped legacy AIMD tokens cannot prove how much was consumed.
                # Keep the period and learned capacity; resume only at normal refill.
                bucket['period_used'] = 0.0
                bucket['usage_known'] = False
                bucket['tokens'] = 0.0
            bucket.setdefault('usage_known', True)
            if bucket['base_cap'] == 0 and bucket['cap'] == 0 and cap > 0:
                bucket['cap'] = cap
            bucket['base_cap'] = cap
            ceiling = min(bucket['cap'], cap)
            bucket['tokens'] = min(bucket['tokens'], max(0.0, ceiling-bucket['period_used']))
        return bucket

    def warmup_allows(self, account_stage: str, action: str) -> bool:
        stage = account_stage if account_stage in STAGE_ACTIONS else "browse"
        return action in STAGE_ACTIONS[stage]

    def allow(self, account, platform, action, policy, *, account_stage="normal") -> tuple:
        """In-memory model API; outbound dispatch uses durable reserve()."""
        return self._allow(account, platform, action, policy, account_stage=account_stage)

    def _allow(self, account, platform, action, policy, *, account_stage="normal", reuse=False):
        action = 'post' if action == 'publish' else action
        if not self.warmup_allows(account_stage, action):
            return False, "warmup: stage %r forbids %r" % (account_stage, action), 0.0
        bucket = self._bucket(account, platform, action, policy)
        now = self.clock()
        if now < bucket["cooldown_until"]:
            return False, "in cooldown", bucket["cooldown_until"]-now
        elapsed = now-bucket["last_refill"]
        if elapsed < 0:
            return False, "clock precedes current throttle period", -elapsed
        if elapsed >= 86400.0:
            bucket["tokens"] = min(bucket["cap"], bucket["base_cap"])
            bucket["period_used"] = 0.0
            bucket["usage_known"] = True
            bucket["last_refill"] = now
            reuse = False
            elapsed = 0.0
        if not bucket['usage_known']:
            return False, 'legacy quota usage is unknown until refill', 86400.0-elapsed
        ceiling = min(bucket['cap'], bucket['base_cap'])
        if ceiling < 1.0 or (reuse and bucket['period_used'] > ceiling):
            return False, 'daily cap reached under current policy', 86400.0-elapsed
        gap = float(policy.get("min_gap_sec", 0))
        if not math.isfinite(gap) or gap < 0:
            raise ValueError('min_gap_sec must be finite and nonnegative')
        if gap and bucket["last_action"]:
            need = gap*self._jitter()
            since = now-bucket["last_action"]
            if since < need:
                return False, "min-gap pacing", need-since
        if not reuse and bucket["tokens"] < 1.0:
            return False, "daily cap reached", 86400.0-elapsed
        if not reuse:
            bucket["tokens"] -= 1.0
            bucket["period_used"] += 1.0
        bucket["last_action"] = now
        return True, "reserved" if reuse else "ok", 0.0

    def reserve(self, account, platform, action, policy, *, reservation_id, payload,
                account_stage="normal"):
        """Commit account admission before any effect; retries retain their exact intent."""
        if not isinstance(reservation_id, str) or not reservation_id or not isinstance(payload, dict):
            raise ValueError('durable admission requires an action identity and frozen payload')
        binding = hashlib.sha256(json.dumps(
            [account, platform, action, payload], sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode()).hexdigest()
        normalized = 'post' if action == 'publish' else action
        account_key = json.dumps([account, platform], separators=(',', ':'))

        def admit(previous):
            document = _state_document(previous)
            self.state = document['buckets']
            reservation = document['reservations'].get(reservation_id)
            if reservation is not None and reservation['binding'] != binding:
                raise ValueError('throttle action identity collides with different frozen intent')
            now = self.clock()
            cooldown = document['cooldowns'].get(account_key, 0.0)
            if cooldown > now:
                return previous, (False, 'in account cooldown', cooldown-now)
            bucket = self._bucket(account, platform, normalized, policy)
            reuse = (reservation is not None and reservation['period'] == bucket['last_refill']
                     and 0 <= now-bucket['last_refill'] < 86400.0)
            result = self._allow(account, platform, normalized, policy,
                                 account_stage=account_stage, reuse=reuse)
            if result[0]:
                document['reservations'][reservation_id] = {
                    'binding': binding, 'period': bucket['last_refill']}
            document['buckets'] = self.state
            encoded = json.dumps(document, indent=2, sort_keys=True)+'\n'
            return encoded, result

        result = private_storage.update_text(self.path, admit)
        self._loaded_state = copy.deepcopy(self.state)
        return result

    def _jitter(self) -> float:
        return math.exp(self.rng.gauss(0.0, 0.35))

    def on_throttle_signal(self, account, platform, action, policy):
        """In-memory AIMD model; record_throttle_signal() persists provider feedback."""
        action = 'post' if action == 'publish' else action
        bucket = self._bucket(account, platform, action, policy)
        backoff = policy.get("backoff", {})
        factor = float(backoff.get("factor", 0.5))
        hours = float(backoff.get("cooldown_h", 24))
        if not math.isfinite(factor) or not 0 < factor <= 1 or not math.isfinite(hours) or hours <= 0:
            raise ValueError('invalid throttle backoff policy')
        bucket["cap"] = max(1.0, bucket["cap"]*factor)
        bucket["tokens"] = min(bucket["tokens"], bucket["cap"])
        bucket["cooldown_until"] = self.clock()+hours*3600.0
        bucket["stable_since"] = self.clock()

    def record_throttle_signal(self, account, platform, action, policy):
        """A 429 durably cools the account before another item can be admitted."""
        normalized = 'post' if action == 'publish' else action
        account_key = json.dumps([account, platform], separators=(',', ':'))
        def update(previous):
            document = _state_document(previous)
            self.state = document['buckets']
            self.on_throttle_signal(account, platform, normalized, policy)
            until = self._bucket(account, platform, normalized, policy)['cooldown_until']
            document['cooldowns'][account_key] = max(document['cooldowns'].get(account_key, 0), until)
            document['buckets'] = self.state
            return json.dumps(document, indent=2, sort_keys=True)+'\n', until
        result = private_storage.update_text(self.path, update)
        self._loaded_state = copy.deepcopy(self.state)
        return result

    def on_stable_period(self, account, platform, action, policy):
        bucket = self._bucket(account, platform, action, policy)
        ramp = policy.get("rampup", {})
        stable_days = float(ramp.get("stable_days", 7))
        factor = float(ramp.get("factor", 1.2))
        if self.clock()-bucket["stable_since"] >= stable_days*86400.0:
            ceiling = bucket["base_cap"]*float(policy.get("max_growth_mult", 3.0))
            bucket["cap"] = min(ceiling, bucket["cap"]*factor)
            bucket["stable_since"] = self.clock()
