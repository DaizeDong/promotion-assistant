#!/usr/bin/env python3
"""Programmatic acceptance gate E1-E12 (self-evolve regression signals, all machine-judged).

Run:  python skills/promotion-assistant/scripts/selftest.py
Exit 0 iff every core signal passes. Each check is deterministic (seeded). Tests that need the
schedule-reminder base degrade to an EXPLICIT gap (never a silent skip) if the base is absent.
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts import bandit as B          # noqa: E402
from scripts import compliance as C      # noqa: E402
from scripts import config as CFG        # noqa: E402
from scripts import dispatch as D        # noqa: E402
from scripts import events as EV         # noqa: E402
from scripts import fingerprint as FP    # noqa: E402
from scripts import metrics as M         # noqa: E402
from scripts import orchestrate as ORCH  # noqa: E402
from scripts import throttle as TH       # noqa: E402
from scripts.schedule_bridge import ScheduleBridge  # noqa: E402

R = []  # (id, name, ok, detail)


def rec(i, name, ok, detail=""):
    R.append((i, name, bool(ok), detail))


def _mk_config(tmp, send_mode="dry_run"):
    root = Path(tmp)
    (root / "channels" / "reddit-rp").mkdir(parents=True, exist_ok=True)
    (root / "copy").mkdir(parents=True, exist_ok=True)
    (root / "product.json").write_text(json.dumps({
        "name": "TestProd", "send_mode": send_mode,
        "aff_base": "https://x.test/register?aff=",
        "banned_claims": ["100% uncensored"],
        "compliance": {"physical_address": "1 Test St", "unsubscribe_url": "https://x.test/u"},
        "from_addr": "promo@x.test",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "registry.json").write_text(json.dumps({"channels": [
        {"slug": "reddit-rp", "platform": "reddit", "transport": "post",
         "account_handle": "acct1", "warmup_state": "normal"}
    ]}, ensure_ascii=False), encoding="utf-8")
    (root / "channels" / "reddit-rp" / "policy.json").write_text(json.dumps({
        "day_cap": 50, "min_gap_sec": 0
    }), encoding="utf-8")
    (root / "copy" / "camp.json").write_text(json.dumps([
        {"id": "armA", "channel": "reddit-rp", "segment": "rp", "hook": "free proxy that stays up",
         "body": "tried it for two months", "utm": {"source": "reddit", "content": "armA"}},
        {"id": "armB", "channel": "reddit-rp", "segment": "rp", "hook": "cheap openai gateway",
         "body": "saves money", "utm": {"source": "reddit", "content": "armB"}},
    ], ensure_ascii=False), encoding="utf-8")
    return CFG.Config(root)


# ---- E1 metrics correctness ----
def e1():
    evs = []
    truth = {"sent": 4, "delivered": 3, "click": 2, "conversion": 1}
    for _ in range(4):
        evs.append(EV.make_event("c", "sent", arm_id="a", propensity_p=0.5, policy_version="v"))
    for _ in range(3):
        evs.append(EV.make_event("c", "delivered"))
    for _ in range(2):
        evs.append(EV.make_event("c", "click"))
    evs.append(EV.make_event("c", "conversion"))
    f = M.funnel(evs, dims=("channel",))[("c",)]
    ok = (f["L1_sent"] == 4 and f["L2_delivered"] == 3 and f["L5_click"] == 2
          and f["L6_conversion"] == 1 and abs(f["cr_conv"] - 0.25) < 1e-9)
    rec("E1", "metrics funnel counts/rates exact", ok,
        "sent=%d click=%d conv=%d cr=%.3f" % (f["L1_sent"], f["L5_click"], f["L6_conversion"], f["cr_conv"]))


# ---- E2 bandit convergence ----
def e2():
    rng = random.Random(7)
    probs = {"a0": 0.3, "a1": 0.3, "a2": 0.7, "a3": 0.3}  # a2 best
    b = B.Bandit(None, gamma=1.0, rng=rng)
    sim = random.Random(11)
    picks = []
    for _ in range(500):
        d = b.select(list(probs), samples_for_propensity=40)
        arm = d["arm_id"]
        r = 1.0 if sim.random() < probs[arm] else 0.0
        b.update(arm, r)
        picks.append(arm)
    last = picks[-100:]
    frac_best = last.count("a2") / 100.0
    rec("E2", "bandit converges to true-best arm (>0.9)", frac_best > 0.9, "best-share=%.2f" % frac_best)


# ---- E3 non-stationary adaptation ----
def _run_drift(gamma):
    """Return b-share in the 120-round window RIGHT AFTER the optimum flips (recovery SPEED)."""
    rng = random.Random(3)
    sim = random.Random(5)
    b = B.Bandit(None, gamma=gamma, rng=rng)
    picks = []
    for t in range(800):
        if t < 400:
            probs = {"a": 0.85, "b": 0.15}
        else:
            probs = {"a": 0.15, "b": 0.85}   # optimum flips to b at t=400
        d = b.select(["a", "b"], samples_for_propensity=30)
        arm = d["arm_id"]
        r = 1.0 if sim.random() < probs[arm] else 0.0
        b.update(arm, r)
        picks.append(arm)
    return picks[400:520].count("b") / 120.0   # how fast it re-finds b after drift


def e3():
    disc = _run_drift(0.9)     # discounted TS re-finds b quickly
    stat = _run_drift(1.0)     # stationary TS stays anchored to stale optimum
    rec("E3", "discounted TS recovers from drift faster than stationary",
        disc > 0.5 and disc > stat, "post-drift b-share: discounted=%.2f stationary=%.2f" % (disc, stat))


# ---- E4 throttle never exceeds + AIMD ----
def e4():
    with tempfile.TemporaryDirectory() as t:
        thr = TH.Throttle(Path(t) / "s.json", clock=lambda: 1000.0, rng=random.Random(1))
        pol = {"day_cap": 5, "min_gap_sec": 0, "backoff": {"factor": 0.5, "cooldown_h": 24}}
        oks = sum(1 for _ in range(12) if thr.allow("acct", "reddit", "post", pol)[0])
        cap_before = thr.state["acct|reddit|post"]["cap"]
        thr.on_throttle_signal("acct", "reddit", "post", pol)
        cap_after = thr.state["acct|reddit|post"]["cap"]
        in_cd = thr.allow("acct", "reddit", "post", pol)
        ok = (oks == 5 and abs(cap_after - cap_before * 0.5) < 1e-9 and in_cd[0] is False)
        rec("E4", "token-bucket cap honored + 429 halves cap + cooldown",
            ok, "allowed=%d cap %.1f->%.1f cooldown=%s" % (oks, cap_before, cap_after, not in_cd[0]))


# ---- E5 compliance fail-closed ----
def e5():
    pol = {"banned_claims": ["100% uncensored"], "physical_address": "1 Test St"}
    base = {"transport": "smtp", "from_addr": "a@x.test", "subject": "Hello",
            "unsubscribe": "https://x.test/u", "recipient": "u@x.test", "recipient_country": "US",
            "physical_address": "1 Test St"}
    good = C.check(dict(base), policy=pol, suppression=set(), consent={})[0]
    no_unsub = C.check({**base, "unsubscribe": ""}, policy=pol, suppression=set(), consent={})[0]
    no_addr = C.check({**base, "physical_address": "", **{"_": 0}}, policy={"banned_claims": []},
                      suppression=set(), consent={})[0]
    eu = C.check({**base, "recipient_country": "DE"}, policy=pol, suppression=set(), consent={})[0]
    supp = C.check(dict(base), policy=pol, suppression={"u@x.test"}, consent={})[0]
    banned = C.check({**base, "body": "we are 100% uncensored"}, policy=pol, suppression=set(), consent={})[0]
    ok = good and not no_unsub and not no_addr and not eu and not supp and not banned
    rec("E5", "compliance gate fail-closed (all 5 violations rejected, valid passes)", ok,
        "good=%s unsub=%s addr=%s eu=%s supp=%s banned=%s" % (good, no_unsub, no_addr, eu, supp, banned))


# ---- E6 attribution ----
def e6():
    evs = [
        EV.make_event("reddit", "sent", arm_id="armA", subject_key="u1", utm={"content": "armA"},
                      propensity_p=0.5, policy_version="v"),
        EV.make_event("reddit", "click", arm_id="armA", subject_key="u1"),
        EV.make_event("reddit", "conversion", subject_key="u1"),
        EV.make_event("mastodon", "sent", arm_id="armB", subject_key="u2", utm={"content": "armB"},
                      propensity_p=0.5, policy_version="v"),
        EV.make_event("mastodon", "conversion", subject_key="u2"),
    ]
    res = {r["conversion_event"]: r for r in M.attribute(evs)}
    a = M.attribute(evs)
    by_subj = {x["attributed_channel"]: x for x in a}
    ok = (len(a) == 2 and by_subj.get("reddit", {}).get("attributed_arm") == "armA"
          and by_subj.get("mastodon", {}).get("attributed_arm") == "armB")
    rec("E6", "last-non-direct attribution maps conversions to right (channel,arm)", ok,
        json.dumps([(x["attributed_channel"], x["attributed_arm"]) for x in a]))


# ---- E7 dry-run engine + E8 propensity + E10 schema (shared run) ----
def e7_e8_e10():
    with tempfile.TemporaryDirectory() as t:
        cfg = _mk_config(t, send_mode="dry_run")
        env = {}  # no PROMO_LIVE_AUTHORIZED_* -> must simulate
        res = ORCH.run_once(cfg, "camp", env=env, rng=random.Random(2))
        evs = EV.read(cfg.metrics_dir() / "events.jsonl")
        dry = cfg.metrics_dir() / "dry-run.jsonl"
        types = [e["event_type"] for e in evs]
        no_live = all(not e.get("live") for e in evs)
        sim_ok = "simulated" in types and "sent" not in types and dry.is_file()
        rec("E7", "dry-run: full pipeline, only simulated events, zero live egress",
            sim_ok and no_live and res["dispatch"]["status"] == "simulated",
            "types=%s dryrun=%s" % (types, dry.is_file()))
        # E8 propensity completeness on decision events
        dec = [e for e in evs if e.get("arm_id") and e["event_type"] in ("sent", "simulated")]
        e8_ok = bool(dec) and all(e.get("propensity_p") is not None and e.get("policy_version") for e in dec)
        rec("E8", "every decision event carries propensity_p + policy_version", e8_ok,
            "decision_events=%d" % len(dec))
        # E10 schema gate
        viol = sum(len(EV.validate_event(e)) for e in evs)
        bad = EV.validate_event({"channel": None, "event_type": "sent"})  # should be flagged
        rec("E10", "all events pass JSON schema; malformed is caught", viol == 0 and len(bad) > 0,
            "violations=%d malformed_flags=%d" % (viol, len(bad)))


# ---- E9 anti-fingerprint ----
def e9():
    tmpl = ("{Hey|Hi|Yo|Sup}, {tried|been running|switched to|found} {this|a|some} "
            "{free|cheap|budget|low-cost} {proxy|gateway|relay|endpoint} for "
            "{roleplay|chatbots|creative writing|companions} — "
            "{rock solid|zero downtime|super stable|never drops} {so far|lately|this month}"
            "{.|!|, honestly|, ngl}")
    vs = FP.variants(tmpl, 5, seed=4)
    mx = FP.max_pairwise_similarity(vs)
    hashes = len({FP.content_hash(v) for v in vs})
    rec("E9", "multi-account variants stay distinct (pairwise sim <0.7, unique hashes)",
        mx < 0.7 and hashes == len(vs), "max_sim=%.2f unique=%d/%d" % (mx, hashes, len(vs)))


# ---- E11 delayed-conversion censoring ----
def e11():
    now = 100000.0
    inside = [EV.make_event("c", "sent", arm_id="z", ts=now - 100, propensity_p=0.5, policy_version="v")]
    r1, s1 = M.reward_for_arm(inside, "z", conversion_window_s=1000, now=now)
    outside = [EV.make_event("c", "sent", arm_id="z", ts=now - 5000, propensity_p=0.5, policy_version="v")]
    r2, s2 = M.reward_for_arm(outside, "z", conversion_window_s=1000, now=now)
    ok = (s1 == "censored" and r1 is None and s2 == "ok" and r2 is not None)
    rec("E11", "delayed conversion inside window = censored (not negative)", ok,
        "inside=%s outside=%s" % (s1, s2))


# ---- E12 idempotency via schedule-reminder base ----
def e12():
    br = ScheduleBridge()
    if not br.available():
        rec("E12", "idempotent schedule writes (replay = no dup)", None,
            "GAP: schedule-reminder base not installed")
        return
    with tempfile.TemporaryDirectory() as t:
        db = str(Path(t) / "r.db")
        b = ScheduleBridge(db_path=db)
        b.init()
        key = "promotion:test:armA:20260625"
        r1 = b.schedule_item(title="t", due_at="2026-07-01T10:00:00Z", idempotency_key=key,
                             ext={"x_promotion_arm_id": "armA"})
        r2 = b.schedule_item(title="t", due_at="2026-07-01T10:00:00Z", idempotency_key=key,
                             ext={"x_promotion_arm_id": "armA"})
        lst = b.list_active()
        items = lst.get("items", lst.get("results", []))
        n = len(items) if isinstance(items, list) else None
        id1 = (r1.get("item") or r1).get("id") if isinstance(r1, dict) else None
        id2 = (r2.get("item") or r2).get("id") if isinstance(r2, dict) else None
        ok = (n == 1) or (id1 is not None and id1 == id2)
        rec("E12", "idempotent schedule writes (replay = no dup)", ok,
            "items=%s id1=%s id2=%s" % (n, id1, id2))


def main():
    e1(); e2(); e3(); e4(); e5(); e6(); e7_e8_e10(); e9(); e11(); e12()
    print("promotion-assistant acceptance gate (E1-E12)")
    print("-" * 70)
    fails = 0
    gaps = 0
    for i, name, ok, detail in R:
        if ok is None:
            tag = "GAP "
            gaps += 1
        elif ok:
            tag = "PASS"
        else:
            tag = "FAIL"
            fails += 1
        print("  [%s] %-4s %s" % (tag, i, name))
        if detail and (ok is not True):
            print("           -> %s" % detail)
    print("-" * 70)
    print("%d checks | %d pass | %d fail | %d gap" %
          (len(R), sum(1 for _, _, o, _ in R if o is True), fails, gaps))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
