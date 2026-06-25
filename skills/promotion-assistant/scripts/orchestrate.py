#!/usr/bin/env python3
"""L1 orchestration — plan (content calendar -> schedule-reminder) and run (gated dispatch + learn).

plan(): turn the copy library (= bandit arms) x audiences into dated items, register each with the
schedule-reminder base (idempotent key, x_promotion_* ext). Human-paced via policy gaps + jitter.

run(): for each due slot, the bandit selects an arm (records propensity + policy_version), build a
decision, push it through dispatch() (compliance -> throttle -> dry-run/live exit). After a cycle,
run the daily ETL: events -> reward (censoring delayed conversions) -> bandit.update -> save. Zero
real egress unless send_mode==live AND the channel is authorized (dispatch enforces this).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from . import bandit as _bandit
from . import dispatch as _dispatch
from . import events as _events
from . import metrics as _metrics
from . import throttle as _throttle
from .schedule_bridge import ScheduleBridge


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z"


def plan(cfg, campaign: str, *, start=None, bridge: ScheduleBridge | None = None, days=7):
    """Generate a content calendar for a campaign and register items with schedule-reminder."""
    bridge = bridge or ScheduleBridge()
    arms = cfg.copy(campaign)
    if not arms:
        return {"status": "empty", "reason": "no copy for campaign %r" % campaign}
    start = start or _dt.datetime.utcnow()
    product = cfg.product.get("name", "product").lower()
    scheduled, errors = [], []
    for i, arm in enumerate(arms):
        slug = arm.get("channel", "unknown")
        policy = cfg.policy(slug)
        gap_h = max(1, int(policy.get("min_gap_sec", 1800)) // 3600 or 1)
        due = start + _dt.timedelta(hours=i * max(gap_h, 24 // max(1, len(arms))))
        date_key = due.strftime("%Y%m%d")
        idem = "promotion:%s:%s:%s" % (product, arm.get("id", "arm%d" % i), date_key)
        ext = {
            "x_promotion_campaign_id": campaign,
            "x_promotion_arm_id": arm.get("id"),
            "x_promotion_channel": slug,
            "x_promotion_utm": arm.get("utm", {}),
        }
        if bridge.available():
            res = bridge.schedule_item(title="promo:%s:%s" % (slug, arm.get("id")),
                                       due_at=_iso(due), idempotency_key=idem, ext=ext,
                                       description=(arm.get("hook") or "")[:200])
            (scheduled if res.get("ok") else errors).append(res)
        else:
            scheduled.append({"ok": True, "local_only": True, "idempotency_key": idem})
    return {"status": "ok", "scheduled": len(scheduled), "errors": errors,
            "base_available": bridge.available()}


def run_once(cfg, campaign: str, *, env=None, clock=None, rng=None, conversion_window_s=None):
    """One planning slot per arm: bandit-select -> dispatch (gated) -> daily ETL learn."""
    metrics_dir = cfg.metrics_dir()
    events_path = metrics_dir / "events.jsonl"
    band = _bandit.Bandit(metrics_dir / "bandit-state.json", rng=rng)
    thr = _throttle.Throttle(metrics_dir / "throttle-state.json", clock=clock, rng=rng)

    arms = cfg.copy(campaign)
    arm_ids = [a.get("id") for a in arms if a.get("id")]
    if not arm_ids:
        return {"status": "empty", "reason": "no arms"}

    # decide
    pick = band.select(arm_ids)
    arm = next(a for a in arms if a.get("id") == pick["arm_id"])
    channel = arm.get("channel", "unknown")
    aff = cfg.aff_base + (arm.get("utm", {}).get("content") or arm.get("id", ""))
    payload = {
        "channel": channel, "transport": (cfg.channel(channel) or {}).get("transport", "post"),
        "subject": arm.get("hook"), "body": arm.get("body", ""), "cta": aff,
        "utm": arm.get("utm", {}),
        # email-only compliance fields pulled from product/policy when present
        "from_addr": cfg.product.get("from_addr"),
        "physical_address": (cfg.product.get("compliance", {}) or {}).get("physical_address"),
        "unsubscribe": (cfg.product.get("compliance", {}) or {}).get("unsubscribe_url"),
    }
    decision = {
        "channel": channel, "platform": (cfg.channel(channel) or {}).get("platform", channel),
        "account": (cfg.channel(channel) or {}).get("account_handle", "default"),
        "action": "post", "arm_id": pick["arm_id"],
        "audience_segment": arm.get("segment"),
        "propensity_p": pick["propensity_p"], "policy_version": pick["policy_version"],
        "decision_id": "%s:%s" % (campaign, pick["arm_id"]),
        "payload": payload, "est_recipients": arm.get("segment", "audience"),
    }
    res = _dispatch.dispatch(decision, cfg=cfg, throttle=thr, env=env)
    thr.save()

    # learn (daily ETL view over the full log)
    evs = _events.read(events_path)
    now = clock() if clock else None
    r, status = _metrics.reward_for_arm(evs, pick["arm_id"],
                                        conversion_window_s=conversion_window_s, now=now)
    if r is not None:
        band.update(pick["arm_id"], r)
        band.save()
    return {"status": "ok", "dispatch": res, "arm": pick["arm_id"],
            "reward": r, "reward_status": status}
