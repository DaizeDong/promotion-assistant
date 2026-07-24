#!/usr/bin/env python3
"""Regression guard for the participation copilot: opportunity scoring, red-flag veto, draft
prompt discipline (warming=no link, graduated=disclosed), give-before-ask ledger, readiness gate,
courtesy pacing, and read-only query construction. Every test is pure (no network)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "skills", "promotion-assistant", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import participation as P   # noqa: E402
import reddit_read as RR    # noqa: E402


# ---- opportunity scoring ------------------------------------------------------------------------
def test_red_flag_hard_veto():
    r = P.score_opportunity({"title": "Unpopular opinion: this all sucks", "body": "rant"})
    assert r["label"] == "skip" and r["red_flag"] is True


def test_expertise_thread_scores_immediate():
    r = P.score_opportunity(
        {"title": "SillyTavern won't connect to my OpenAI-compatible proxy, getting 500",
         "body": "base url + api key set, still fails, what should I use?",
         "num_comments": 1, "score": 8, "created_utc": 1000, "intent": "troubleshooting"},
        now_ts=1000 + 3600)
    assert r["label"] == "immediate"
    assert r["scores"]["expertise_fit"] >= 0.66


def test_offtopic_thread_not_immediate():
    r = P.score_opportunity({"title": "Favorite anime this season?", "body": "chat",
                             "num_comments": 40})
    # low expertise fit must never be immediate (don't steer the person outside their knowledge)
    assert r["label"] != "immediate"
    assert r["scores"].get("expertise_fit", 0) < 0.34


def test_immediate_requires_expertise_even_if_hot():
    # a hot, fresh, unanswered thread that ISN'T in the person's wheelhouse must not be immediate
    r = P.score_opportunity({"title": "Best gaming mouse?", "body": "recommendations?",
                             "num_comments": 0, "score": 50, "created_utc": 1000,
                             "intent": "recommendation"}, now_ts=1000)
    assert r["label"] != "immediate"


def test_ranking_orders_immediate_first():
    posts = [
        {"title": "anime chat", "body": ""},
        {"title": "SillyTavern proxy 500 error, which openai-compatible gateway?",
         "body": "base url api key", "num_comments": 0, "intent": "troubleshooting"},
    ]
    ranked = P.rank_opportunities(posts)
    assert "proxy" in ranked[0]["title"].lower()


# ---- draft prompt discipline --------------------------------------------------------------------
def test_draft_warming_has_no_link_no_product():
    prompt = P.build_draft_prompt({"title": "help", "body": "proxy 500", "intent": "troubleshooting"},
                                  graduated=False, product="TokenReply", aff_url="https://x/aff")
    assert "no product mention" in prompt.lower() or "no link" in prompt.lower()
    assert "https://x/aff" not in prompt  # warming: link never injected


def test_draft_graduated_requires_disclosure_and_link():
    prompt = P.build_draft_prompt({"title": "help", "body": "proxy 500", "intent": "troubleshooting"},
                                  graduated=True, product="TokenReply", aff_url="https://x/aff")
    assert "Full disclosure" in prompt
    assert "https://x/aff" in prompt
    assert "90" in prompt  # 90/10 discipline


# ---- ledger + readiness -------------------------------------------------------------------------
def test_ledger_9to1_strict():
    assert P.ledger_balance([{"type": "give"}] * 9 + [{"type": "ask"}])["holds_9to1"] is True
    assert P.ledger_balance([{"type": "give"}] * 8 + [{"type": "ask"}])["holds_9to1"] is False
    assert P.ledger_balance([{"type": "give"}] * 3)["holds_9to1"] is True  # no asks -> inf


def test_readiness_new_account_not_ready():
    rd = P.readiness({"age_days": 3, "karma": 10, "sub_gives": 0, "mod_strikes": 1},
                     [{"type": "give"}] * 2 + [{"type": "ask"}])
    assert rd["ready"] is False
    assert rd["next"]  # gives a concrete next step


def test_readiness_seasoned_account_ready():
    rd = P.readiness({"age_days": 30, "karma": 80, "sub_gives": 5, "mod_strikes": 0},
                     [{"type": "give"}] * 9 + [{"type": "ask"}])
    assert rd["ready"] is True
    assert rd["met"] == rd["total"]


def test_readiness_is_proposed_with_evidence():
    # even when ready, criteria carry their evidence (never a bare self-declaration)
    rd = P.readiness({"age_days": 30, "karma": 80, "sub_gives": 5, "mod_strikes": 0},
                     [{"type": "give"}] * 9 + [{"type": "ask"}])
    assert all("detail" in c for c in rd["criteria"])


# ---- courtesy pacing ----------------------------------------------------------------------------
def test_pacing_per_sub_cap():
    r = P.pacing_ok([{"sub": "a"}, {"sub": "a"}], sub="a", max_per_sub_day=2)
    assert r["ok"] is False


def test_pacing_paused_sub_blocked():
    r = P.pacing_ok([], sub="a", paused_subs={"a"})
    assert r["ok"] is False and "paused" in r["reason"]


def test_pacing_within_limits_ok():
    r = P.pacing_ok([{"sub": "a"}], sub="b", max_per_day=5, max_per_sub_day=2)
    assert r["ok"] is True


# ---- read-only query construction + parsing -----------------------------------------------------
def test_build_search_queries_scoped_and_capped():
    qs = RR.build_search_queries(["500 errors", "rate limits"], "openai-compatible gateway",
                                 competitors=["OpenRouter"], subreddit="SillyTavernAI")
    assert all("site:reddit.com" in q for q in qs)
    assert all("subreddit:SillyTavernAI" in q for q in qs)
    assert len(qs) <= 40


def test_parse_listing_normalizes_schema():
    body = {"data": {"children": [{"data": {
        "id": "abc", "name": "t3_abc", "title": "proxy 500", "selftext": "help",
        "subreddit": "SillyTavernAI", "num_comments": 2, "score": 5, "created_utc": 1000,
        "permalink": "/r/x/abc"}}]}}
    posts = RR.parse_listing(body)
    assert len(posts) == 1
    assert posts[0]["fullname"] == "t3_abc"
    assert posts[0]["permalink"] == "https://www.reddit.com/r/x/abc"


def test_missing_creds_degrades_to_empty():
    from pathlib import Path
    assert RR.load_reddit_creds(Path("/nonexistent/reddit.env")) == {}
