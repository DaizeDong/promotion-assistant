#!/usr/bin/env python3
"""Regression guard for the 2026-07 expansion: over-claim floor, Mastodon/Bluesky providers,
ManualPrepProvider prep/record loop. Every provider is exercised in NON-live mode (no network);
the over-claim guard is pure text; the manual loop is checked structurally."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "skills", "promotion-assistant", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import compliance  # noqa: E402
import providers   # noqa: E402
import content     # noqa: E402


class _FakeCfg:
    """Minimal cfg stand-in for the pure content generator (no config repo needed)."""
    def __init__(self):
        self.product = {"product": "TestGW", "url": "https://tg.example",
                        "value_props": ["cheaper and more stable", "generous free models"]}
    aff_base = "https://tg.example/register?aff="
    banned_claims = []


# ---- over-claim floor (built-in, non-removable) --------------------------------------------------
def _check(body, banned=None):
    return compliance.check({"body": body, "transport": "post"},
                            policy={"banned_claims": banned or []}, suppression=set(), consent={})


def test_overclaim_floor_blocks_scam_superlatives():
    for bad in ("Get unlimited free tokens", "no limits, ever", "100% free forever", "never rate limited"):
        ok, reasons = _check(bad)
        assert not ok, "should block over-claim: %r" % bad
        assert any("banned claim" in r for r in reasons)


def test_overclaim_floor_allows_honest_copy():
    ok, _ = _check("Cheaper, more stable OpenAI-compatible gateway with generous free models")
    assert ok


def test_overclaim_floor_survives_zero_width_obfuscation():
    ok, _ = _check("un​limited free access")  # zero-width space inside 'unlimited'
    assert not ok  # normalized match still catches it


def test_overclaim_floor_is_not_removable_by_empty_banned_claims():
    # a product with an explicitly empty banned_claims list still gets the floor
    ok, _ = _check("unlimited free", banned=[])
    assert not ok


# ---- Mastodon / Bluesky providers: non-live is a clean no-op, missing creds is a clean error -----
def test_mastodon_non_live_is_not_live():
    r = providers.MastodonProvider().publish({"body": "x"}, live=False)
    assert r["status"] == "deferred-gap" and r["platform"] == "mastodon"


def test_mastodon_live_without_creds_errors_cleanly(monkeypatch):
    monkeypatch.delenv("PROMO_MASTODON_INSTANCE", raising=False)
    monkeypatch.delenv("PROMO_MASTODON_TOKEN", raising=False)
    r = providers.MastodonProvider().publish({"body": "x"}, live=True)
    assert r["status"] == "error" and "PROMO_MASTODON" in r["reason"]


def test_bluesky_non_live_is_not_live():
    r = providers.BlueskyProvider().publish({"body": "x"}, live=False)
    assert r["status"] == "deferred-gap" and r["platform"] == "bluesky"


def test_bluesky_live_without_creds_errors_cleanly(monkeypatch):
    monkeypatch.delenv("PROMO_BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("PROMO_BLUESKY_APP_PASSWORD", raising=False)
    r = providers.BlueskyProvider().publish({"body": "x"}, live=True)
    assert r["status"] == "error" and "PROMO_BLUESKY" in r["reason"]


def test_mastodon_bluesky_are_live_transport_in_registry():
    reg = providers.build_registry()
    assert reg["mastodon"].LIVE_TRANSPORT is True
    assert reg["bluesky"].LIVE_TRANSPORT is True
    assert reg["x"].LIVE_TRANSPORT is False  # X stays deferred


# ---- ManualPrepProvider: never egresses, prep emits copy + checklist ------------------------------
def test_manual_prep_never_has_live_transport():
    reg = providers.build_registry()
    for slug in ("reddit", "janitorai-card", "producthunt", "hackernews"):
        assert reg[slug].LIVE_TRANSPORT is False  # permanent -- a human is the actuator


def test_manual_prep_publish_never_sends():
    # even asked to go live, a manual-prep provider must not egress
    r = providers.build_registry()["reddit"].publish({"body": "x"}, live=True)
    assert r["status"] == "deferred-gap"  # no network path exists


def test_manual_prep_emits_copy_and_checklist():
    prov = providers.build_registry()["reddit"]
    out = prov.prep({"subject": "hook", "body": "text", "cta": "https://x/register?aff=a"})
    assert out["status"] == "prepared"
    assert "hook" in out["copy"] and "register?aff=a" in out["copy"]
    assert isinstance(out["checklist"], list) and out["checklist"]  # a real per-surface checklist
    assert "megathread" in out["surface"].lower()


# ---- SEO content generator: honest guides, aff-stamped, over-claim-guarded ----------------------
def test_content_guide_renders_with_aff_link():
    g = content.build_guide(_FakeCfg(), "sillytavern", aff_code="seo_st")
    assert g["status"] == "ok"
    assert "SillyTavern" in g["markdown"] and "register?aff=seo_st" in g["markdown"]
    assert "base-URL" in g["markdown"] or "Base URL" in g["markdown"]


def test_content_all_frontends():
    guides = content.build_all(_FakeCfg(), aff_code="x")
    fes = {g["frontend"] for g in guides if g.get("status") == "ok"}
    assert {"janitorai", "sillytavern", "risu", "agnai"} <= fes


def test_content_unknown_frontend_errors():
    g = content.build_guide(_FakeCfg(), "nosuchfrontend")
    assert g["status"] == "error"


def test_content_proxy_card_has_aff():
    c = content.build_proxy_card(_FakeCfg(), aff_code="card_a")
    assert c["status"] == "ok" and "register?aff=card_a" in c["blurb"]


def test_content_over_claim_is_refused():
    # a cfg whose value_props over-claim must be BLOCKED by the floor at render time
    cfg = _FakeCfg()
    cfg.product = {**cfg.product, "value_props": ["unlimited free tokens forever"]}
    g = content.build_guide(cfg, "janitorai")
    assert g["status"] == "blocked"


# ---- referral module: stable codes, aff-stamped invite, over-claim-guarded, attribution ----------
import referral  # noqa: E402


def test_referral_code_is_stable_and_urlsafe():
    c1 = referral.advocate_code("CoolUser")
    c2 = referral.advocate_code("cooluser")  # case-insensitive -> same code (idempotent)
    assert c1 == c2 and c1.startswith("r_")
    assert all(ch.isalnum() or ch == "_" for ch in c1)


def test_referral_invite_carries_advocate_code():
    r = referral.invite_copy(_FakeCfg(), "alice")
    assert r["status"] == "ok"
    assert r["code"] in r["aff_url"] and r["code"] in r["copy"]


def test_referral_invite_over_claim_refused():
    cfg = _FakeCfg()
    r = referral.invite_copy(cfg, "bob", reward_hint="unlimited free forever")
    assert r["status"] == "blocked"


def test_referral_attribution():
    code = referral.advocate_code("carol")
    evs = [{"event_type": "click", "utm": {"content": code}},
           {"event_type": "conversion", "utm": {"content": code}},
           {"event_type": "conversion", "utm": {"content": "other"}}]
    a = referral.attribute(evs, code)
    assert a["touches"] == 2 and a["conversions"] == 1 and a["converted"] is True


# ---- growth module: listing assets + keybot spec, guard-safe ------------------------------------
import growth  # noqa: E402


def test_growth_listing_has_tags_and_directories():
    L = growth.listing(_FakeCfg())
    assert "openai" in L["tags"] and L["directories"]
    assert "bump" in L["bump_note"].lower() and "ring" in L["bump_note"].lower()  # anti-ring guard present


def test_growth_keybot_spec_is_compliant_text():
    s = growth.keybot_spec(_FakeCfg())
    assert "/key" in s and "OWN server" in s and "register?aff=discord" in s
    assert "Never DM users of OTHER servers" in s
