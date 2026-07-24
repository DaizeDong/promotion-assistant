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
from . import providers as _providers
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


def run_once(cfg, campaign: str, *, env=None, clock=None, rng=None, conversion_window_s=None, channel=None):
    """One planning slot per arm: bandit-select -> dispatch (gated) -> daily ETL learn.

    channel: if given, restrict the bandit's arm pool to that channel's arms. This mirrors
    prep_once(channel=) and matches the per-channel live-authorization model -- e.g. going live
    on discord-own alone shouldn't let the global bandit pick a reddit arm. Omit for the default
    cross-channel bandit run."""
    metrics_dir = cfg.metrics_dir()
    events_path = metrics_dir / "events.jsonl"
    band = _bandit.Bandit(metrics_dir / "bandit-state.json", rng=rng)
    thr = _throttle.Throttle(metrics_dir / "throttle-state.json", clock=clock, rng=rng)

    arms = cfg.copy(campaign)
    if channel:  # scope to one channel's arms (per-channel go-live control)
        scoped = [a for a in arms if a.get("channel") == channel]
        if not scoped:
            return {"status": "empty", "reason": "no arms for channel %r" % channel}
        arms = scoped
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


def prep_once(cfg, campaign: str, *, channel=None, rng=None):
    """Manual-prep path: bandit-select an arm and emit the FINISHED copy + aff link + a compliant
    posting checklist for a HUMAN to post. No egress ever. Records a 'prepared' event so the bandit
    draw (arm/propensity/policy_version) is visible to OPE; the human's real post is logged later via
    record_post(), which writes the 'sent' event that closes the loop. Use for ToS-hostile surfaces
    (megathread, organic answers, Chub card, PH/HN) where an API post would be spam/ban."""
    metrics_dir = cfg.metrics_dir()
    events_path = metrics_dir / "events.jsonl"
    band = _bandit.Bandit(metrics_dir / "bandit-state.json", rng=rng)
    arms = cfg.copy(campaign)
    if channel:  # prep for a specific channel: restrict the arm pool to that channel's arms
        arms = [a for a in arms if a.get("channel") == channel] or arms
    arm_ids = [a.get("id") for a in arms if a.get("id")]
    if not arm_ids:
        return {"status": "empty", "reason": "no arms for channel %r" % channel}
    pick = band.select(arm_ids)
    arm = next(a for a in arms if a.get("id") == pick["arm_id"])
    ch = arm.get("channel", "unknown")
    aff = cfg.aff_base + (arm.get("utm", {}).get("content") or arm.get("id", ""))
    payload = {"subject": arm.get("hook"), "body": arm.get("body", ""), "cta": aff,
               "utm": arm.get("utm", {})}
    prov = _providers.get((cfg.channel(ch) or {}).get("platform", ch))
    if not hasattr(prov, "prep"):
        return {"status": "not-manual", "reason": "channel %r is not a manual-prep surface "
                "(use `run` for automated/dry-run channels)" % ch}
    prepared = prov.prep(payload)
    # record the draw so OPE sees the arm was played (no egress; value carried when human posts)
    ev = _events.make_event(ch, "prepared", platform=(cfg.channel(ch) or {}).get("platform", ch),
                            account=(cfg.channel(ch) or {}).get("account_handle", "default"),
                            arm_id=pick["arm_id"], audience_segment=arm.get("segment"),
                            decision_id="%s:%s" % (campaign, pick["arm_id"]),
                            propensity_p=pick["propensity_p"], policy_version=pick["policy_version"],
                            utm=arm.get("utm", {}), value=0.0)
    _events.append(events_path, ev)
    return {"status": "prepared", "channel": ch, "arm": pick["arm_id"], "prepared": prepared,
            "decision_id": ev["decision_id"]}


def record_participation(cfg, url: str, *, thread=None):
    """Close the participation loop after the HUMAN posted a genuine contribution. Writes a 'sent'
    event on the 'reddit-participation' channel tying the human's real permalink to the most recent
    'drafted' event (or standalone if none), actuator='human'. A later register?aff conversion on
    the aff link the human chose to include attributes back through this URL. The human is always
    the sole actuator -- this only records what they already did by hand."""
    metrics_dir = cfg.metrics_dir()
    events_path = metrics_dir / "events.jsonl"
    evs = _events.read(events_path)
    channel = "reddit-participation"
    drafts = [e for e in evs if e.get("channel") == channel and e.get("event_type") == "drafted"]
    last = max(drafts, key=lambda e: e.get("ts", 0)) if drafts else None
    ev = _events.make_event(
        channel, "sent", platform="reddit",
        account=(cfg.channel(channel) or {}).get("account_handle", "self"),
        arm_id=(last or {}).get("arm_id"),
        decision_id=(last or {}).get("decision_id"),
        utm=(last or {}).get("utm", {}),
        live=True, post_url=url, actuator="human", thread=thread)
    _events.append(events_path, ev)
    return {"status": "recorded", "channel": channel, "url": url, "event_id": ev["event_id"],
            "linked_draft": (last or {}).get("event_id")}


def record_post(cfg, channel: str, url: str, *, arm_id=None, campaign=None):
    """Close the loop after a human posted a prepped item: write a real 'sent' event tying the post
    URL to the arm, so a later register?aff conversion attributes back and the bandit updates. If
    arm_id is omitted, use the most recent 'prepared' event for this channel."""
    metrics_dir = cfg.metrics_dir()
    events_path = metrics_dir / "events.jsonl"
    evs = _events.read(events_path)
    if not arm_id:  # find the latest 'prepared' for this channel
        preps = [e for e in evs if e.get("channel") == channel and e.get("event_type") == "prepared"]
        if not preps:
            return {"status": "error", "reason": "no prior 'prepared' event for channel %r; pass "
                    "--arm-id explicitly" % channel}
        last = max(preps, key=lambda e: e.get("ts", 0))
        arm_id = last.get("arm_id")
        decision_id = last.get("decision_id")
        platform = last.get("platform"); segment = last.get("audience_segment")
        propensity = last.get("propensity_p"); policy = last.get("policy_version"); utm = last.get("utm")
    else:
        decision_id = "%s:%s" % (campaign or "manual", arm_id)
        platform = (cfg.channel(channel) or {}).get("platform", channel); segment = None
        propensity = None; policy = None; utm = {}
    ev = _events.make_event(channel, "sent", platform=platform,
                            account=(cfg.channel(channel) or {}).get("account_handle", "default"),
                            arm_id=arm_id, audience_segment=segment, decision_id=decision_id,
                            propensity_p=propensity, policy_version=policy, utm=utm,
                            live=True, post_url=url, actuator="human")
    _events.append(events_path, ev)
    return {"status": "recorded", "channel": channel, "arm_id": arm_id, "url": url,
            "event_id": ev["event_id"]}
