#!/usr/bin/env python3
"""Participation copilot -- a COMPLIANT, human-in-the-loop community-participation module.

Governing invariant (do not weaken):
  A human is always the publisher and endorser. This module AUGMENTS a real person's genuine
  participation -- it discovers threads their real expertise fits, drafts a genuine answer they
  edit, and tracks their give-before-ask balance -- but it NEVER fakes participation and NEVER
  evades a platform's safety systems. It has NO code path that posts or votes: every "publish"
  returns a draft for the human to send by hand (mirroring ManualPrepProvider's structural
  no-egress: there is nothing to gate because nothing sends).

Synthesized from a survey of six participation/warmup/discovery skills. It borrows their
*structure* (opportunity scoring, reply frameworks, give-before-ask ledger, prepared->record
attribution) and discards their *intent* where that intent was detection-evasion or autonomous
undisclosed posting. In particular it deliberately DROPS the anti-detection warmup curve /
fingerprinting / proxy machinery that exists elsewhere only to survive behavioral classifiers;
the only pacing here is *courtesy* pacing (don't spam, don't over-post), never classifier evasion.

Pure functions only (scoring, red-flag exclusion, ledger, readiness, draft prompt construction).
Network reads live in reddit_read.py; the CLI wires them together. Nothing here sends.
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------------------------------------
# Discovery: opportunity scoring  (synthesis of opportunity-research 8-field extraction + 5-dim
# scoring + 4-label ladder, and growth-skill's red-flag exclusion + "when in doubt, skip").
# ------------------------------------------------------------------------------------------------

# Red-flag phrases: a thread matching any of these is HARD-vetoed (label=skip) no matter its score.
# Borrowed from growth-skill: bait/troll, polarized debate, promo-banned, would-look-opportunistic.
RED_FLAGS = [
    "no self promo", "no self-promo", "no promotion", "no advertising", "no ads",
    "drama", "rant", "unpopular opinion", "circlejerk", "vent", "shitpost",
    "politics", "political", "nsfw drama", "callout", "call-out", "witch hunt",
]

# Intent types (from opportunity-research); recommendation/troubleshooting/comparison carry the
# highest genuine-help value because the person is actively looking for an answer.
INTENT_WEIGHTS = {
    "recommendation": 1.0,
    "troubleshooting": 1.0,
    "comparison": 0.9,
    "workflow": 0.7,
    "discussion": 0.4,
    "other": 0.3,
}

# The person's declared, verifiable areas of real expertise. A thread only scores high on
# expertise_fit if it actually touches one of these -- this is what prevents the tool from steering
# the person toward answering things they don't genuinely know (the growth-skill failure mode).
DEFAULT_EXPERTISE = [
    "openai-compatible", "openai compatible", "proxy", "reverse proxy", "base url",
    "api key", "sillytavern", "risuai", "agnai", "janitorai", "gateway",
    "rate limit", "500", "model", "endpoint", "aggregat",
]


def has_red_flag(text: str) -> bool:
    t = (text or "").lower()
    return any(rf in t for rf in RED_FLAGS)


def _kw_hits(text: str, keywords) -> int:
    t = (text or "").lower()
    return sum(1 for k in keywords if k.lower() in t)


def score_opportunity(post: dict, *, expertise=None, now_ts=None) -> dict:
    """Score one thread on five dimensions and assign a 4-label readiness ladder.

    post: {title, body, subreddit, num_comments, score, created_utc, intent(optional)}
    Returns {scores{}, total, label, reasons[], red_flag}. Pure; no network, no clock() unless
    now_ts passed (created_utc freshness needs a reference time -- caller supplies it, never
    Date.now, to stay deterministic/testable).
    """
    expertise = expertise or DEFAULT_EXPERTISE
    title = post.get("title", "") or ""
    body = post.get("body", "") or ""
    text = title + "\n" + body
    reasons = []

    # HARD veto: red flag anywhere -> skip regardless of score.
    if has_red_flag(text):
        return {"scores": {}, "total": 0.0, "label": "skip", "red_flag": True,
                "reasons": ["red-flag phrase present -> skip (when in doubt, skip)"]}

    # (1) expertise_fit -- does this touch what the person genuinely knows?
    hits = _kw_hits(text, expertise)
    expertise_fit = min(1.0, hits / 3.0)  # 3+ expertise keyword hits saturates
    if expertise_fit >= 0.66:
        reasons.append("strong expertise fit (%d keyword hits)" % hits)

    # (2) need_intensity -- is the person actively seeking an answer? intent + question signals.
    intent = (post.get("intent") or _infer_intent(text)).lower()
    need = INTENT_WEIGHTS.get(intent, 0.3)
    if "?" in text:
        need = min(1.0, need + 0.1)
    reasons.append("intent=%s" % intent)

    # (3) freshness -- newer is better (answer gets seen before the thread is buried).
    freshness = 0.5
    cu = post.get("created_utc")
    if cu is not None and now_ts is not None:
        age_h = max(0.0, (now_ts - float(cu)) / 3600.0)
        # 1.0 at 0h, ~0.5 at 24h, ~0.2 at ~3d, floor 0.05
        freshness = max(0.05, 1.0 / (1.0 + age_h / 24.0))

    # (4) unanswered -- few comments => higher marginal value of a good answer.
    nc = post.get("num_comments")
    if nc is None:
        unanswered = 0.5
    else:
        unanswered = max(0.1, 1.0 / (1.0 + float(nc) / 5.0))  # 5 comments ~ 0.5

    # (5) community_fit -- is this a live thread worth engaging (score as a liveliness proxy).
    sc = post.get("score")
    community_fit = 0.5 if sc is None else min(1.0, 0.3 + float(max(0, sc)) / 20.0)

    scores = {
        "expertise_fit": round(expertise_fit, 3),
        "need_intensity": round(need, 3),
        "freshness": round(freshness, 3),
        "unanswered": round(unanswered, 3),
        "community_fit": round(community_fit, 3),
    }
    # Weighted total: expertise_fit is load-bearing (a compliant copilot must not push the person
    # to answer outside their real knowledge), so it dominates.
    total = round(
        0.40 * expertise_fit + 0.20 * need + 0.15 * freshness
        + 0.15 * unanswered + 0.10 * community_fit, 3)

    label = _label_for(total, expertise_fit)
    reasons.append("total=%.3f -> %s" % (total, label))
    return {"scores": scores, "total": total, "label": label, "red_flag": False, "reasons": reasons}


def _label_for(total: float, expertise_fit: float) -> str:
    # Immediate requires BOTH a high total AND genuine expertise fit -- never steer the person to
    # answer something they don't actually know just because the thread is hot.
    if total >= 0.62 and expertise_fit >= 0.5:
        return "immediate"
    if total >= 0.45:
        return "monitor"
    if expertise_fit < 0.34:
        return "skip"  # not your wheelhouse -> don't force it
    return "build"  # relevant but weak; maybe write real content first


def _infer_intent(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("recommend", "suggestion", "what should i use", "which", "best ")):
        return "recommendation"
    if any(w in t for w in ("error", "not working", "fails", "500", "can't connect", "broken", "help")):
        return "troubleshooting"
    if any(w in t for w in (" vs ", "versus", "compare", "difference between")):
        return "comparison"
    if any(w in t for w in ("how do i", "how to", "setup", "configure")):
        return "workflow"
    return "discussion"


def rank_opportunities(posts, *, expertise=None, now_ts=None) -> list:
    """Score + sort a list of posts; return them best-first with their scoring attached."""
    scored = []
    for p in posts:
        s = score_opportunity(p, expertise=expertise, now_ts=now_ts)
        scored.append({**p, "_score": s})
    order = {"immediate": 0, "build": 1, "monitor": 2, "skip": 3}
    scored.sort(key=lambda x: (order.get(x["_score"]["label"], 9), -x["_score"]["total"]))
    return scored


# ------------------------------------------------------------------------------------------------
# Draft assistance: build a prompt for llmcall that produces a GENUINE, helpful answer grounded in
# the person's real expertise. Draft-only; the human edits and posts. (synthesis of growth reply
# frameworks + marketing 3-5 paragraph structure + disclosure template.)
# ------------------------------------------------------------------------------------------------

# Four typed reply frameworks (from growth-skill) -- STRUCTURES to be rewritten each time, never
# pasted. Chosen by the thread's intent.
REPLY_FRAMEWORKS = {
    "recommendation": "They're asking for a recommendation. Give 2-3 honest evaluation criteria "
                      "first, then a concrete suggestion, then a clarifying question.",
    "troubleshooting": "They have a problem. Diagnose the likely cause from the details given, give "
                       "the concrete fix steps, and note what to check if it still fails.",
    "comparison": "They're comparing options. Lay out the real trade-offs neutrally, say which fits "
                  "which situation, avoid declaring a single winner.",
    "workflow": "They want to know how to do something. Give the ordered steps, the exact values, "
                "and one gotcha.",
    "discussion": "Add a substantive, specific point from real experience; ask a genuine question.",
}


def build_draft_prompt(post: dict, *, graduated: bool, product: str, aff_url: str,
                       expertise_note: str = "") -> str:
    """Construct the llmcall prompt. If NOT graduated: pure help, zero product mention, zero link.
    If graduated: 90/10, answer-first, product mentioned last with an explicit disclosure line."""
    intent = (post.get("intent") or _infer_intent(post.get("title", "") + " " + post.get("body", ""))).lower()
    framework = REPLY_FRAMEWORKS.get(intent, REPLY_FRAMEWORKS["discussion"])
    title = post.get("title", "")
    body = post.get("body", "")

    base = (
        "Write a genuine, helpful Reddit reply to the thread below. This is a REAL person's reply "
        "in their own voice -- do NOT fabricate a 'I use product X' persona, do NOT overclaim, do "
        "NOT sound like marketing. 3-5 short paragraphs, specific and grounded in real knowledge.\n\n"
        "Reply framework for this thread: %s\n\n"
        "The author's genuine areas of expertise: %s\n\n"
        "THREAD TITLE: %s\nTHREAD BODY: %s\n\n"
    ) % (framework, expertise_note or ", ".join(DEFAULT_EXPERTISE[:8]), title, body)

    if not graduated:
        base += (
            "IMPORTANT: This account is still building standing in the community. Provide PURE help "
            "-- absolutely no product mention, no link, no CTA. Just genuinely answer the question. "
            "The goal is a real contribution, nothing else."
        )
    else:
        base += (
            "You MAY mention %s if -- and only if -- it genuinely fits the person's question, and "
            "only briefly at the END (90%% help / 10%% mention). If you mention it, you MUST include "
            "an explicit disclosure line: 'Full disclosure: I work on it.' Use soft phrasing "
            "('if it helps, ...'), never a hard CTA. If it doesn't genuinely fit, don't mention it "
            "at all. If you do link, the link is: %s"
        ) % (product, aff_url)
    return base


# ------------------------------------------------------------------------------------------------
# Readiness: give-before-ask ledger + account-standing + graduation state machine.
# (synthesis of warmup-planner verifiable graduation criteria + marketing 90/10 + manualprep 9:1.)
# ------------------------------------------------------------------------------------------------

def ledger_balance(entries) -> dict:
    """entries: list of {type: 'give'|'ask', ...}. Returns give/ask counts + ratio + whether the
    9:1 give-before-ask discipline is currently held."""
    gives = sum(1 for e in entries if e.get("type") == "give")
    asks = sum(1 for e in entries if e.get("type") == "ask")
    ratio = (gives / asks) if asks else float("inf")
    return {"gives": gives, "asks": asks, "ratio": ratio,
            "holds_9to1": ratio >= 9.0, "next_ask_ok": ratio >= 9.0}


def readiness(account: dict, ledger_entries, *, min_age_days=14, min_karma=50,
              min_sub_gives=3) -> dict:
    """Assess whether the account is ready to make a promotional post (e.g. the megathread).

    account: {age_days, karma, sub_gives(in-community non-promo contributions accepted),
              mod_strikes}. All values three-valued-labeled by the caller (Measured/User/Estimated);
    here we just gate on them. Graduation is PROPOSED with evidence, never self-declared: we return
    the criteria and which are met, and the human confirms.
    """
    lb = ledger_balance(ledger_entries)
    age = account.get("age_days")
    karma = account.get("karma")
    sub_gives = account.get("sub_gives")
    strikes = account.get("mod_strikes", 0)

    criteria = [
        ("account_age", age is not None and age >= min_age_days,
         "account age >= %d days (have: %s)" % (min_age_days, age)),
        ("karma", karma is not None and karma >= min_karma,
         "karma >= %d (have: %s)" % (min_karma, karma)),
        ("in_community_gives", sub_gives is not None and sub_gives >= min_sub_gives,
         "in-community accepted non-promo contributions >= %d (have: %s)" % (min_sub_gives, sub_gives)),
        ("ledger_9to1", lb["holds_9to1"],
         "give:ask ratio holds 9:1 (have: %s gives / %s asks)" % (lb["gives"], lb["asks"])),
        ("no_strikes", strikes == 0,
         "zero mod removals/strikes (have: %s)" % strikes),
    ]
    met = [c for c in criteria if c[1]]
    unmet = [c for c in criteria if not c[1]]
    ready = len(unmet) == 0
    return {
        "ready": ready,
        "ledger": lb,
        "criteria": [{"key": k, "met": ok, "detail": d} for k, ok, d in criteria],
        "met": len(met), "total": len(criteria),
        "verdict": ("READY -- proposed with evidence; you confirm and post by hand"
                    if ready else "NOT READY -- keep participating genuinely"),
        "next": [d for _, ok, d in criteria if not ok][:1],
    }


# ------------------------------------------------------------------------------------------------
# Courtesy pacing (NOT anti-detection): simple per-day / per-sub caps + circuit breaker.
# ------------------------------------------------------------------------------------------------

def pacing_ok(recent_actions, *, sub=None, max_per_day=5, max_per_sub_day=2,
              paused_subs=None) -> dict:
    """recent_actions: list of {sub, ts} within the last 24h (caller filters the window).
    paused_subs: set of subs under a post-removal 7-day pause. Returns whether another genuine
    contribution now would stay within courteous limits. This is etiquette, not classifier evasion.
    """
    paused_subs = paused_subs or set()
    if sub and sub in paused_subs:
        return {"ok": False, "reason": "sub %r is paused (a prior post was removed) -- wait it out" % sub}
    day_count = len(recent_actions)
    if day_count >= max_per_day:
        return {"ok": False, "reason": "already %d contributions today (courtesy cap %d)"
                % (day_count, max_per_day)}
    if sub:
        sub_count = sum(1 for a in recent_actions if a.get("sub") == sub)
        if sub_count >= max_per_sub_day:
            return {"ok": False, "reason": "already %d in r/%s today (per-sub cap %d)"
                    % (sub_count, sub, max_per_sub_day)}
    return {"ok": True, "reason": "within courteous limits"}
