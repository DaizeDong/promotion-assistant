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
