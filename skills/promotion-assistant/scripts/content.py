#!/usr/bin/env python3
"""Durable SEO content generator: honest "connect <product> to <frontend>" setup guides + a proxy-
guide card. The 2026-07 expansion research found this is the best long-tail, zero-ToS-risk funnel --
your OWN content ranks for 'free API key for JanitorAI' / 'OpenAI-compatible proxy for SillyTavern'
intent and reaches the non-technical ICP at the moment of need.

This module only RENDERS text (a human publishes it, like ManualPrepProvider) and stamps every link
with register?aff=<code>. It never claims 'unlimited free' etc. -- generated copy is passed through
compliance.check() with the built-in over-claim floor, so a guide that over-claims fails to render.

  build_guide(cfg, frontend, aff_code=None) -> {"title","markdown","aff_url","frontend"}
  build_all(cfg, aff_code=None)              -> a guide per known frontend
  build_proxy_card(cfg, aff_code=None)       -> the SFW proxy-guide character-card blurb
"""
from __future__ import annotations

try:
    from . import compliance as _compliance  # package import (via scripts.content)
except ImportError:
    import compliance as _compliance         # flat import (tests add scripts/ to sys.path)

# Each frontend: how a user points it at an OpenAI-compatible gateway. Facts kept generic + honest;
# the skill renders the wrapper, the human verifies specifics before publishing.
FRONTENDS = {
    "janitorai": {
        "name": "JanitorAI",
        "where": "Settings > API > Proxy (Reverse Proxy)",
        "fields": ["Proxy URL: the gateway's OpenAI-compatible base URL (ending in /v1)",
                   "API Key: your gateway key",
                   "Model: pick one the gateway exposes (a free model to start)"],
        "note": "JanitorAI is built around pasting a proxy URL + key, so this is a one-time setup.",
    },
    "sillytavern": {
        "name": "SillyTavern",
        "where": "API Connections > Chat Completion > Custom (OpenAI-compatible)",
        "fields": ["Custom Endpoint (Base URL): the gateway's /v1 URL",
                   "API Key: your gateway key",
                   "Then click Connect and select a model from the dropdown"],
        "note": "It's a drop-in base-URL swap -- anything OpenAI-compatible works with no other change.",
    },
    "risu": {
        "name": "RisuAI",
        "where": "Settings > Model / Provider > OpenAI-compatible (custom URL)",
        "fields": ["Custom URL: the gateway's OpenAI-compatible base URL",
                   "API Key: your gateway key",
                   "Model: enter or select an available model id"],
        "note": "RisuAI deliberately supports custom base URLs, so any compatible gateway plugs in.",
    },
    "agnai": {
        "name": "Agnai",
        "where": "Settings > AI Settings > add an OpenAI-compatible service",
        "fields": ["Base URL: the gateway's /v1 URL",
                   "API Key: your gateway key",
                   "Model: choose an available model"],
        "note": "Agnai supports custom OpenAI-compatible providers for self-hosted / third-party gateways.",
    },
}


def _aff_url(cfg, aff_code):
    code = aff_code or "seo"
    return cfg.aff_base + code


def _honest_props(cfg):
    """The product's value props, but only the honest/renderable ones (the over-claim floor rejects
    scam superlatives, so we surface the genuine differentiators)."""
    return [p for p in (cfg.product.get("value_props") or [])][:3]


def _guard(cfg, text):
    """Render only if the copy clears the compliance over-claim floor. Returns (ok, reasons)."""
    ok, reasons = _compliance.check({"body": text, "transport": "post"},
                                    policy={"banned_claims": cfg.banned_claims},
                                    suppression=set(), consent={})
    return ok, reasons


def build_guide(cfg, frontend: str, aff_code=None) -> dict:
    fe = FRONTENDS.get(frontend)
    if not fe:
        return {"status": "error", "reason": "unknown frontend %r; known: %s"
                % (frontend, ", ".join(FRONTENDS))}
    product = cfg.product.get("product") or cfg.product.get("name") or "the gateway"
    aff = _aff_url(cfg, aff_code)
    props = _honest_props(cfg)
    steps = "\n".join("%d. %s" % (i + 1, f) for i, f in enumerate(fe["fields"]))
    md = (
        "# How to connect %s to %s (OpenAI-compatible gateway)\n\n"
        "%s is an OpenAI-compatible AI gateway. Because %s speaks the OpenAI API, connecting it is a "
        "one-time base-URL + key change.\n\n"
        "## Why use a gateway here\n%s\n\n"
        "## Setup (in %s)\n"
        "Go to **%s** and fill in:\n\n%s\n\n"
        "> %s\n\n"
        "## Get a key\n"
        "Sign up and grab a key here: %s\n\n"
        "That's it -- pick a model and start. If a model is busy, switch to another from the list.\n"
    ) % (product, fe["name"], product, fe["name"],
         "\n".join("- %s" % p for p in props) or "- Cheaper and more stable than going direct.",
         fe["name"], fe["where"], steps, fe["note"], aff)
    ok, reasons = _guard(cfg, md)
    if not ok:
        return {"status": "blocked", "reason": "over-claim guard: %s" % reasons, "frontend": frontend}
    return {"status": "ok", "frontend": frontend, "title": "Connect %s to %s" % (product, fe["name"]),
            "markdown": md, "aff_url": aff}


def build_all(cfg, aff_code=None) -> list:
    return [build_guide(cfg, fe, aff_code=aff_code) for fe in FRONTENDS]


def build_proxy_card(cfg, aff_code=None) -> dict:
    """A SFW proxy-guide 'character card' blurb (a durable SEO surface on Chub/JanitorAI). It is a
    genuine how-to, never an ad, and carries the aff link."""
    product = cfg.product.get("product") or cfg.product.get("name") or "the gateway"
    aff = _aff_url(cfg, aff_code)
    props = _honest_props(cfg)
    blurb = (
        "%s -- OpenAI-compatible proxy setup helper.\n\n"
        "A quick guide card: how to point JanitorAI / SillyTavern / RisuAI / Agnai at an "
        "OpenAI-compatible gateway (paste the base URL + key, pick a model).\n\n"
        "%s\n\n"
        "Get a key: %s\n"
    ) % (product, "\n".join("- %s" % p for p in props) or "- Cheaper, more stable, free models to start.", aff)
    ok, reasons = _guard(cfg, blurb)
    if not ok:
        return {"status": "blocked", "reason": "over-claim guard: %s" % reasons}
    return {"status": "ok", "title": "%s proxy setup helper" % product, "blurb": blurb, "aff_url": aff}
