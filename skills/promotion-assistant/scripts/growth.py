#!/usr/bin/env python3
"""Discord growth module: the owned-server acquisition loop the 2026-07 research called the single
highest-leverage compliant surface. It fits the already-live discord-own transport: stand up a
TokenReply-OWNED server, list it on the Discord directories the RP crowd browses, and let the bandit
run live in your own channels.

This module RENDERS listing assets + the /key onboarding-bot spec (a human submits the listing; the
server's OWN bot runs /bump). It never touches other servers, never bump-for-votes, never rings.

  listing(cfg)      -> name/tags/description + directory URLs + the compliant bump note
  keybot_spec(cfg)  -> a spec for the free-model /key onboarding bot (what to build, compliantly)
"""
from __future__ import annotations

try:
    from . import compliance as _compliance  # package import (via scripts.content)
except ImportError:
    import compliance as _compliance         # flat import (tests add scripts/ to sys.path)

DIRECTORIES = [
    "https://disboard.org/  (tags: openai, chatbot, api)",
    "https://top.gg/servers  (submit your server)",
    "https://discadia.com/  (submit your server)",
]


def _honest_props(cfg):
    return [p for p in (cfg.product.get("value_props") or [])][:3]


def listing(cfg) -> dict:
    product = cfg.product.get("product") or cfg.product.get("name") or "the gateway"
    props = _honest_props(cfg)
    desc = ("%s community server -- an OpenAI-compatible AI gateway for RP frontends (JanitorAI, "
            "SillyTavern, RisuAI, Agnai). %s Grab a free model to start; ask for help with setup in "
            "the channels." % (product, " ".join("%s." % p.rstrip(".") for p in props)))
    ok, reasons = _compliance.check({"body": desc, "transport": "post"},
                                    policy={"banned_claims": cfg.banned_claims},
                                    suppression=set(), consent={})
    if not ok:
        desc = "%s community server -- an OpenAI-compatible AI gateway for RP frontends. Free models " \
               "to start; setup help in the channels." % product  # fall back to a plain, guard-safe desc
    return {
        "name": "%s" % product,
        "tags": ["openai", "chatbot", "api", "roleplay", "ai"],
        "description": desc,
        "directories": DIRECTORIES,
        "bump_note": ("Bump ONLY your OWN server via its own bot's /bump command (DISBOARD allows a "
                      "self-bump every 2h). NEVER join bump-for-vote / reciprocal-bump rings -- that "
                      "is against directory ToS and gets the listing removed."),
    }


def keybot_spec(cfg) -> str:
    product = cfg.product.get("product") or cfg.product.get("name") or "the gateway"
    aff = cfg.aff_base + "discord"
    return (
        "=" * 66 + "\n"
        "/key onboarding bot spec (build this in YOUR server)\n" + "=" * 66 + "\n\n"
        "Goal: a compliant, first-party onboarding loop that mirrors how competitors acquire the RP\n"
        "crowd -- a bot in a #free-models channel that hands out free-tier access, so joining the\n"
        "server has an immediate payoff and the bandit can attribute join -> register?aff conversions.\n\n"
        "Channels:\n"
        "  #announcements  -- the discord-own transport posts copy arms here (already live)\n"
        "  #free-models    -- the /key bot lives here; users run a command to get started\n"
        "  #setup-help     -- humans + pinned setup guides (see `content` command output)\n\n"
        "Bot command (/key):\n"
        "  - On /key, DM or reply with: the OpenAI-compatible base URL + how to get a free-tier key at\n"
        "    %s , and a one-line 'paste this into JanitorAI/SillyTavern' pointer.\n"
        "  - Rate-limit per user; log the interaction so join -> key -> register?aff can be attributed.\n\n"
        "Compliance:\n"
        "  - OWN server + OWN bot only. Never DM users of OTHER servers, never scrape members.\n"
        "  - The free tier's actual grant is a PRODUCT decision (you set what /key gives).\n"
        "  - No over-claim in the bot copy (the compliance floor forbids 'unlimited free' etc.).\n"
    ) % aff
