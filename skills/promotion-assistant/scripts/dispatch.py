#!/usr/bin/env python3
"""L3 dispatch — the ONE outbound exit. Fail-closed dry-run is the default, not an option.

Every real send/post/DM in the whole system goes through dispatch(). It asserts BOTH:
  1. product.json.send_mode == "live", AND
  2. environment token PROMO_LIVE_AUTHORIZED_<CHANNEL> matches the per-channel authorize token.
If either is missing -> the action is SIMULATED: it still runs the full pipeline
(compliance gate -> throttle -> [would call provider] -> writes an event_type='simulated' row +
a dry-run.jsonl record with the would-send content and estimated recipients), but performs ZERO
network egress. This lets the metrics stream + bandit train with no real outreach.

Pipeline order (all dry-run too):  compliance.check  ->  throttle.allow  ->  provider(live?)  ->
  events.append. A compliance/throttle rejection short-circuits and is logged (not a crash).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import compliance, events, providers


def _authorized(channel: str, send_mode: str, *, env=None) -> tuple:
    env = env if env is not None else os.environ
    if send_mode != "live":
        return (False, "send_mode=%s (not live)" % send_mode)
    tok_env = "PROMO_LIVE_AUTHORIZED_%s" % channel.upper().replace("-", "_")
    if not env.get(tok_env):
        return (False, "missing %s authorize token" % tok_env)
    return (True, "authorized")


def dispatch(decision: dict, *, cfg, throttle, env=None) -> dict:
    """decision keys: channel, platform, account, action, arm_id, audience_segment,
    propensity_p, policy_version, payload(dict for compliance), recipient(s)/est_recipients.

    Returns a result dict and appends the canonical event to metrics/events.jsonl."""
    channel = decision["channel"]
    platform = decision.get("platform", channel)
    account = decision.get("account", "default")
    action = decision.get("action", "post")
    payload = dict(decision.get("payload", {}))
    payload.setdefault("channel", channel)

    metrics_dir = cfg.metrics_dir()
    events_path = metrics_dir / "events.jsonl"
    dryrun_path = metrics_dir / "dry-run.jsonl"

    # ---- compliance gate (fail-closed) ----
    policy = dict(cfg.policy(channel))
    policy.setdefault("banned_claims", cfg.banned_claims)
    policy.setdefault("physical_address", (cfg.product.get("compliance", {}) or {}).get("physical_address"))
    suppression = compliance.load_suppression(metrics_dir / "suppression.csv")
    consent = compliance.load_consent_ledger(cfg.compliance_dir() / "consent-ledger.jsonl")
    ok, reasons = compliance.check(payload, policy=policy, suppression=suppression, consent=consent)
    if not ok:
        ev = events.make_event(channel, "blocked", platform=platform, account=account,
                               arm_id=decision.get("arm_id"),
                               audience_segment=decision.get("audience_segment"),
                               decision_id=decision.get("decision_id"),
                               propensity_p=decision.get("propensity_p"),
                               policy_version=decision.get("policy_version"),
                               utm=payload.get("utm"), reason="compliance: " + "; ".join(reasons))
        events.append(events_path, ev)
        return {"status": "rejected", "stage": "compliance", "reasons": reasons}

    # ---- throttle / warmup gate ----
    ch = cfg.channel(channel) or {}
    stage = ch.get("warmup_state", "normal")
    allow, why, wait = throttle.allow(account, platform, action, policy, account_stage=stage)
    if not allow:
        ev = events.make_event(channel, "ratelimited", platform=platform, account=account,
                               arm_id=decision.get("arm_id"),
                               decision_id=decision.get("decision_id"),
                               propensity_p=decision.get("propensity_p"),
                               policy_version=decision.get("policy_version"),
                               reason=why, wait_seconds=wait)
        events.append(events_path, ev)
        return {"status": "throttled", "reason": why, "wait_seconds": wait}

    # ---- authorization (fail-closed) ----
    is_live, auth_why = _authorized(channel, cfg.send_mode, env=env)
    prov = providers.get(platform)

    if is_live and prov.LIVE_TRANSPORT:
        result = prov.publish(payload, live=True) if action.startswith("post") or action == "publish" \
            else prov.dm(payload, live=True)
        etype = "sent" if result.get("status") == "sent" else "blocked"
        ev = events.make_event(channel, etype, platform=platform, account=account,
                               arm_id=decision.get("arm_id"),
                               audience_segment=decision.get("audience_segment"),
                               decision_id=decision.get("decision_id"),
                               propensity_p=decision.get("propensity_p"),
                               policy_version=decision.get("policy_version"),
                               utm=payload.get("utm"), live=True, provider_result=result)
        events.append(events_path, ev)
        return {"status": result.get("status"), "live": True, "provider": result}

    # ---- SIMULATED (dry-run) — full pipeline, zero egress ----
    sim = {
        "channel": channel, "platform": platform, "account": account, "action": action,
        "arm_id": decision.get("arm_id"), "audience_segment": decision.get("audience_segment"),
        "would_send": {"subject": payload.get("subject"), "body_preview": (payload.get("body") or "")[:200],
                       "cta": payload.get("cta")},
        "est_recipients": decision.get("est_recipients", payload.get("recipient")),
        "reason_not_live": auth_why if not is_live else ("deferred-gap: " + prov.deferred_reason),
        "utm": payload.get("utm", {}),
    }
    dryrun_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dryrun_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(sim, ensure_ascii=False) + "\n")
    ev = events.make_event(channel, "simulated", platform=platform, account=account,
                           arm_id=decision.get("arm_id"),
                           audience_segment=decision.get("audience_segment"),
                           decision_id=decision.get("decision_id"),
                           propensity_p=decision.get("propensity_p"),
                           policy_version=decision.get("policy_version"),
                           utm=payload.get("utm"))
    events.append(events_path, ev)
    return {"status": "simulated", "live": False, "reason": sim["reason_not_live"]}
