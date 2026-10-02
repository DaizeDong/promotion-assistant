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
import hashlib
import json
import uuid

from . import bandit as _bandit
from . import dispatch as _dispatch
from . import events as _events
from . import metrics as _metrics
from . import providers as _providers
from . import throttle as _throttle
from . import participation as _participation
from .schedule_bridge import ScheduleBridge


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z"


def plan(cfg, campaign: str, *, start=None, bridge: ScheduleBridge | None = None, days=7):
    """Generate a content calendar for a campaign and register items with schedule-reminder."""
    if type(days) is not int or days <= 0:
        raise ValueError('days must be a positive scheduling horizon')
    bridge = bridge or ScheduleBridge()
    arms = cfg.copy(campaign)
    if not arms:
        return {"status": "empty", "reason": "no copy for campaign %r" % campaign}
    start = start or _dt.datetime.utcnow()
    product = cfg.product.get("name", "product").lower()
    scheduled, errors, outside_horizon = [], [], 0
    for i, arm in enumerate(arms):
        slug = arm.get("channel", "unknown")
        policy = cfg.policy(slug)
        gap_h = max(1, int(policy.get("min_gap_sec", 1800)) // 3600 or 1)
        due = start + _dt.timedelta(hours=i * max(gap_h, 24 // max(1, len(arms))))
        if due >= start + _dt.timedelta(days=days):
            outside_horizon += 1
            continue
        date_key = due.strftime("%Y%m%d")
        registration = cfg.channel(slug) or {}
        obligation = [product, campaign, arm.get('id', 'arm%d' % i), slug,
                      registration.get('account_handle', 'default'), arm.get('action', 'post'), date_key]
        idem = "promotion:"+hashlib.sha256(json.dumps(obligation, separators=(',', ':')).encode()).hexdigest()
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
            confirmed = (isinstance(res, dict) and res.get('ok') is True
                         and isinstance(res.get('item'), dict) and bool(res['item'].get('id')))
            (scheduled if confirmed else errors).append(res)
        else:
            errors.append({"ok": False, "reason": "schedule base unavailable", "idempotency_key": idem})
    status = ('deferred' if not bridge.available() else 'partial' if scheduled and errors else
              'failed' if errors else 'complete')
    return {"status": status, "scheduled": len(scheduled), "errors": errors,
            "base_available": bridge.available(), "outside_horizon": outside_horizon, "horizon_days": days}


def run_once(cfg, campaign: str, *, env=None, clock=None, rng=None, conversion_window_s=None,
             channel=None, run_id=None, resume=False):
    """Review and dispatch one selected arm with durable per-destination results."""
    from .runs import execute
    return execute(cfg, campaign, env=env, clock=clock, rng=rng,
                   conversion_window_s=conversion_window_s, channel=channel,
                   run_id=run_id, resume=resume)


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
        arms = [a for a in arms if a.get("channel") == channel]
    arm_ids = [a.get("id") for a in arms if a.get("id")]
    if not arm_ids:
        return {"status": "blocked", "reason": "no arms for channel %r" % channel}
    pick = band.select(arm_ids)
    arm = next(a for a in arms if a.get("id") == pick["arm_id"])
    ch = arm.get("channel", "unknown")
    aff = cfg.aff_base + (arm.get("utm", {}).get("content") or arm.get("id", ""))
    payload = {"subject": arm.get("hook"), "body": arm.get("body", ""), "cta": aff,
               "utm": arm.get("utm", {}), "transport": "post",
               "channel": ch, "platform": (cfg.channel(ch) or {}).get("platform", ch)}
    prov = _providers.get((cfg.channel(ch) or {}).get("platform", ch))
    if not hasattr(prov, "prep"):
        return {"status": "not-manual", "reason": "channel %r is not a manual-prep surface "
                "(use `run` for automated/dry-run channels)" % ch}
    if cfg.product.get('enabled') is False or (cfg.channel(ch) or {}).get('enabled') is False:
        return {'status': 'blocked', 'reason': 'selected channel or product is disabled'}
    prepared = prov.prep(payload)
    ok, reasons, eligibility, _ = _dispatch.review(
        {**payload, 'body': prepared['copy']}, cfg=cfg, channel=ch)
    if not ok:
        return {'status': 'blocked', 'reasons': reasons, 'eligibility': eligibility}
    # record the draw so OPE sees the arm was played (no egress; value carried when human posts)
    ev = _events.make_event(ch, "prepared", platform=(cfg.channel(ch) or {}).get("platform", ch),
                            account=(cfg.channel(ch) or {}).get("account_handle", "default"),
                            arm_id=pick["arm_id"], audience_segment=arm.get("segment"),
                            decision_id="prep-"+uuid.uuid4().hex,
                            propensity_p=pick["propensity_p"], policy_version=pick["policy_version"],
                            utm=arm.get("utm", {}), value=0.0)
    _events.append(events_path, ev)
    return {"status": "prepared", "channel": ch, "arm": pick["arm_id"], "prepared": prepared,
            "decision_id": ev["decision_id"]}


def record_participation(cfg, url: str, *, thread=None, draft_id=None, participation_type=None):
    """Record the human's final give/ask classification and explicit source draft/thread."""
    if participation_type not in {'give', 'ask'}:
        return {'status': 'error', 'reason': 'record requires an explicit final contribution type: give or ask'}
    if not thread:
        return {'status': 'error', 'reason': 'record requires the source thread URL'}
    try:
        url = _participation.canonical_permalink(url)
        thread = _participation.thread_identity(thread)
        if _participation.thread_identity(url) != thread:
            raise ValueError('publication permalink does not belong to the stated source thread')
        path = cfg.data_path('metrics', 'events.jsonl')
        rows = _events.read(path)
        draft = None
        if draft_id is not None:
            matches = [row for row in rows if row.get('event_id') == draft_id
                       and row.get('event_type') == 'drafted' and row.get('channel') == 'reddit-participation']
            if len(matches) != 1 or matches[0].get('thread') != thread:
                raise ValueError('draft identity must match exactly one draft for this source thread')
            draft = matches[0]
        ev = _events.make_event(
            'reddit-participation', 'sent', platform='reddit',
            account=(cfg.channel('reddit-participation') or {}).get('account_handle', 'self'),
            live=True, post_url=url, actuator='human', decision_origin='human',
            thread=thread, linked_draft=draft_id, participation_type=participation_type,
            graduated=(draft or {}).get('graduated'),
            draft_compliance=(draft or {}).get('compliance_ok'),
            utm=(draft or {}).get('utm', {}) if participation_type == 'ask' else {})
        stored = _events.append_once(path, ev, key='participation:'+url)
        return {'status': 'recorded', 'channel': 'reddit-participation', 'url': url,
                'event_id': stored['event_id'], 'linked_draft': stored.get('linked_draft'),
                'participation_type': stored['participation_type']}
    except ValueError as exc:
        return {'status': 'error', 'reason': str(exc)}


def record_post(cfg, channel: str, url: str, *, arm_id=None, campaign=None, decision_id=None):
    """Link a real prepared choice, or honestly record an explicit human arm choice."""
    try:
        url = _participation.canonical_permalink(url)
        path = cfg.data_path('metrics', 'events.jsonl')
        rows = _events.read(path)
        prepared = None
        if not arm_id or decision_id:
            preps = [row for row in rows if row.get('channel') == channel
                     and row.get('event_type') == 'prepared'
                     and (not arm_id or row.get('arm_id') == arm_id)
                     and (not decision_id or row.get('decision_id') == decision_id)]
            if not preps or (decision_id and len(preps) != 1):
                raise ValueError('no unambiguous matching prepared decision; provide an explicit human --arm-id')
            prepared = max(preps, key=lambda row: row.get('ts', 0))
            arm_id = prepared['arm_id']
        if not isinstance(arm_id, str) or not arm_id:
            raise ValueError('record requires an arm identity')
        registration = cfg.channel(channel) or {}
        origin = 'bandit' if prepared else 'human'
        identity = (prepared['decision_id'] if prepared else 'human-'+hashlib.sha256(
            json.dumps([campaign, channel, arm_id, url], separators=(',', ':')).encode()).hexdigest())
        ev = _events.make_event(
            channel, 'sent', platform=(prepared or {}).get('platform') or registration.get('platform', channel),
            account=registration.get('account_handle', 'default'), arm_id=arm_id,
            audience_segment=(prepared or {}).get('audience_segment'), decision_id=identity,
            propensity_p=(prepared or {}).get('propensity_p'), policy_version=(prepared or {}).get('policy_version'),
            utm=(prepared or {}).get('utm', {}), live=True, post_url=url, actuator='human',
            decision_origin=origin, linked_draft=(prepared or {}).get('event_id'))
        stored = _events.append_once(path, ev, key='manual-post:'+channel+':'+url)
        return {'status': 'recorded', 'channel': channel, 'arm_id': arm_id, 'url': url,
                'event_id': stored['event_id'], 'decision_origin': stored['decision_origin']}
    except ValueError as exc:
        return {'status': 'error', 'reason': str(exc)}
