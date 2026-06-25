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

EVENT_TYPES = {
    # positive funnel
    "sent", "delivered", "open", "view", "like", "comment", "share", "reply",
    "click", "conversion",
    # negative / risk (first-class — fed as strong negative reward)
    "bounce", "unsub", "complaint", "blocked", "ratelimited", "shadowban",
    # build-time
    "simulated",
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
    # propensity completeness for decision-bearing events
    if ev.get("arm_id") and ev.get("event_type") in ("sent", "simulated"):
        if ev.get("propensity_p") is None or ev.get("policy_version") is None:
            errs.append("decision event missing propensity_p/policy_version")
    return errs


def append(path: Path, ev: dict) -> None:
    errs = validate_event(ev)
    if errs:
        raise ValueError("event schema violation: %s" % "; ".join(errs))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def read(path: Path):
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
