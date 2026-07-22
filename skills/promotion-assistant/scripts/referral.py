#!/usr/bin/env python3
"""Referral module: turn the product's own register?aff=<code> system into a compliant word-of-mouth
loop. The 2026-07 research found competitors grow via 'refer a friend for free credits' loops; this
treats each ADVOCATE (a user who shares their code) as a first-class attributed source.

Compliant by construction: it only MINTS codes and RENDERS an invite a human shares -- no auto-DM,
no scraped contacts, no spam. Second-order attribution: a signup on advocate A's code is credited to
A (for a reward tier) AND to the channel A was recruited through (for the bandit), via the existing
6-layer funnel on register?aff.

  advocate_code(handle)              -> a stable, URL-safe ref code for an advocate
  invite_copy(cfg, handle, ...)      -> the message an advocate posts/shares (aff link = their code)
  attribute(events, code)            -> signups on this code, for reward crediting
"""
from __future__ import annotations

import hashlib
import re

try:
    from . import compliance as _compliance  # package import (via scripts.content)
except ImportError:
    import compliance as _compliance         # flat import (tests add scripts/ to sys.path)

_SAFE = re.compile(r"[^a-z0-9]+")


def advocate_code(handle: str) -> str:
    """A stable, URL-safe, non-reversible-ish ref code for an advocate handle. Deterministic so the
    same advocate always gets the same code (idempotent attribution), short so it reads clean in a
    register?aff=<code> link. Prefix 'r_' marks it a referral (vs a channel arm code)."""
    h = (handle or "").strip().lower()
    slug = _SAFE.sub("", h)[:12] or "anon"
    tag = hashlib.sha1(h.encode("utf-8")).hexdigest()[:6]
    return "r_%s_%s" % (slug, tag)


def invite_copy(cfg, handle: str, *, reward_hint: str = "") -> dict:
    """The message an advocate shares. Honest, no over-claim (passes the compliance floor). The link
    carries THEIR code so their referrals attribute back to them."""
    code = advocate_code(handle)
    aff = cfg.aff_base + code
    product = cfg.product.get("product") or cfg.product.get("name") or "this gateway"
    reward = (" " + reward_hint.strip()) if reward_hint else ""
    body = ("Using %s for my setup and it's been solid. If you want to try it, my link:%s\n%s"
            % (product, reward, aff))
    ok, reasons = _compliance.check({"body": body, "transport": "post"},
                                    policy={"banned_claims": cfg.banned_claims},
                                    suppression=set(), consent={})
    if not ok:
        return {"status": "blocked", "reason": "over-claim guard: %s" % reasons}
    return {"status": "ok", "advocate": handle, "code": code, "aff_url": aff, "copy": body}


def attribute(events, code: str) -> dict:
    """Second-order attribution: count conversions/signups tagged with this advocate code so a reward
    tier can credit the advocate. Reads the same events.jsonl the funnel uses (utm.content == code, or
    an explicit ref_code field). Pure read, no side effects."""
    hits = [e for e in events
            if (e.get("utm", {}) or {}).get("content") == code or e.get("ref_code") == code]
    conversions = [e for e in hits if e.get("event_type") == "conversion"]
    return {"code": code, "touches": len(hits), "conversions": len(conversions),
            "converted": len(conversions) > 0}
