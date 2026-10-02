#!/usr/bin/env python3
"""L4 event schema + append-only event store (event sourcing).

Every outbound action and every receipt becomes one JSONL line. The raw log is the
source of truth; funnel counts, attribution and reward are *views* computed from it
(metrics.py), so weights stay hot-swappable and reward is re-computable.

HARD: propensity_p + policy_version MUST be present on any event produced by a bandit
decision (off-policy de-biasing needs them). validate_event() enforces the schema; the
acceptance gate (E8/E10) checks completeness.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from . import private_storage

EVENT_TYPES = {
    # positive funnel
    "sent", "delivered", "open", "view", "like", "comment", "share", "reply",
    "click", "conversion",
    # negative / risk (first-class, fed as strong negative reward)
    "bounce", "unsub", "complaint", "blocked", "ratelimited", "shadowban",
    # build-time
    "simulated",
    # manual-prep channels: 'prepared' = the skill emitted arm copy for a human to post (records the
    # bandit draw so OPE sees it); the human's actual post is later logged as a normal 'sent' via
    # `record-post`, closing the loop for human-actuated (ToS-hostile) surfaces.
    "prepared",
    # participation copilot (human-in-the-loop community participation): 'drafted' = the copilot
    # produced a genuine-help draft for a human to edit and post; the human's actual contribution is
    # later logged via `participate record`, closing the attribution loop with their real permalink.
    "drafted",
    # Delivery outcomes without a confirmed remote receipt never enter the sent funnel.
    "uncertain", "failed", "deferred", "manual-prep",
}

REQUIRED = ("event_id", "ts", "channel", "event_type")


def now_ts() -> float:
    return time.time()


def make_event(channel, event_type, *, platform=None, account=None, arm_id=None,
               audience_segment=None, decision_id=None, value=1.0, propensity_p=None,
               policy_version=None, utm=None, ts=None, **extra) -> dict:
    if event_type not in EVENT_TYPES:
        raise ValueError("unknown event_type %r" % event_type)
    ev = {
        "event_id": uuid.uuid4().hex,
        "ts": float(ts if ts is not None else now_ts()),
        "channel": channel,
        "platform": platform,
        "account": account,
        "arm_id": arm_id,
        "audience_segment": audience_segment,
        "decision_id": decision_id,
        "event_type": event_type,
        "value": value,
        "propensity_p": propensity_p,
        "policy_version": policy_version,
        "utm": utm or {},
    }
    ev.update(extra)
    return ev


def validate_event(ev: dict) -> list:
    """Return a list of schema violations (empty = valid)."""
    errs = []
    for k in REQUIRED:
        if ev.get(k) in (None, ""):
            errs.append("missing required field: %s" % k)
    if ev.get("event_type") not in EVENT_TYPES:
        errs.append("bad event_type: %r" % ev.get("event_type"))
    if not isinstance(ev.get("utm", {}), dict):
        errs.append("utm must be an object")
    # Human choices have no sampling probability; prepared bandit choices retain theirs.
    if ev.get("arm_id") and ev.get("event_type") in ("sent", "simulated"):
        human = ev.get("decision_origin") == "human" and ev.get("actuator") == "human"
        if human:
            if ev.get("propensity_p") is not None or ev.get("policy_version") is not None:
                errs.append("human choice must not claim a stochastic propensity")
        elif ev.get("propensity_p") is None or ev.get("policy_version") is None:
            errs.append("decision event missing propensity_p/policy_version")
    return errs


def _rows(payload):
    rows = []
    for line in (payload or '').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError('event store contains a non-object row')
        rows.append(row)
    return rows


def append(path: Path, ev: dict) -> None:
    append_once(path, ev)


def append_once(path: Path, ev: dict, *, key=None):
    """Atomically append, or return a matching prior manual-record identity."""
    errs = validate_event(ev)
    if errs:
        raise ValueError("event schema violation: %s" % "; ".join(errs))
    if key is not None and (not isinstance(key, str) or not key):
        raise ValueError('event idempotency key must be a nonempty string')
    event = dict(ev)
    if key is not None:
        event['record_key'] = key

    def merge(previous):
        rows = _rows(previous)
        if key is not None:
            matches = [row for row in rows if row.get('record_key') == key]
            if len(matches) > 1:
                raise ValueError('event store contains duplicate record identities')
            if matches:
                fields = ('channel', 'platform', 'account', 'event_type', 'post_url', 'thread', 'linked_draft',
                          'participation_type', 'arm_id', 'decision_id', 'decision_origin',
                          'propensity_p', 'policy_version', 'actuator')
                if any(matches[0].get(field) != event.get(field) for field in fields):
                    raise ValueError('event identity is already linked to a different decision or publication')
                return previous, matches[0]
        prefix = previous or ''
        if prefix and not prefix.endswith('\n'):
            prefix += '\n'
        return prefix+json.dumps(event, ensure_ascii=False)+'\n', event

    return private_storage.update_text(path, merge)


def read(path: Path):
    return _rows(private_storage.read_text(path))
