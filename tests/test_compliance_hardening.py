#!/usr/bin/env python3
"""Regression guard for compliance-matcher evasion (v0.1.2 hardening).

These encode the exact bypasses an adversarial review demonstrated against the old gate:
zero-width chars, Cyrillic/Greek homoglyphs, `+tag` suppression aliases, and CAN-SPAM
skipped by mislabeling an email's transport. Each must now be caught.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "skills", "promotion-assistant", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import compliance  # noqa: E402

POLICY = {"banned_claims": ["miracle"], "physical_address": "123 Main St, NJ"}


def _clean_email(**over):
    p = {
        "channel": "email", "transport": "smtp", "recipient": "ok@example.com",
        "from_addr": "me@example.com", "unsubscribe": "https://x/unsub",
        "subject": "Hello there", "body": "a normal message",
    }
    p.update(over)
    return p


def test_clean_email_passes():
    ok, reasons = compliance.check(_clean_email(), policy=POLICY, suppression=set(), consent={})
    assert ok, reasons


def test_banned_claim_via_zero_width_is_caught():
    # "mira<ZWSP>cle" must still match the banned word "miracle"
    ok, reasons = compliance.check(_clean_email(body="our mira​cle product"),
                                   policy=POLICY, suppression=set(), consent={})
    assert not ok and any("banned claim" in r for r in reasons)


def test_banned_claim_via_homoglyph_is_caught():
    # Cyrillic 'а' (U+0430) in place of Latin 'a'
    ok, reasons = compliance.check(_clean_email(body="a mirаcle cure"),
                                   policy=POLICY, suppression=set(), consent={})
    assert not ok and any("banned claim" in r for r in reasons)


def test_suppression_plus_tag_alias_is_caught():
    sup = {compliance.normalize_recipient("user@example.com")}
    ok, reasons = compliance.check(_clean_email(recipient="user+promo@example.com"),
                                   policy=POLICY, suppression=sup, consent={})
    assert not ok and any("suppression" in r for r in reasons)


def test_suppression_case_and_unicode_variant_is_caught():
    sup = {compliance.normalize_recipient("user@example.com")}
    ok, reasons = compliance.check(_clean_email(recipient="USER@Example.com"),
                                   policy=POLICY, suppression=sup, consent={})
    assert not ok and any("suppression" in r for r in reasons)


def test_email_mislabeled_transport_still_canspam_checked():
    # recipient is clearly an email but transport lies ("post") + missing unsubscribe -> must reject
    p = _clean_email(transport="post", channel="post", unsubscribe="")
    ok, reasons = compliance.check(p, policy=POLICY, suppression=set(), consent={})
    assert not ok and any("unsubscribe" in r for r in reasons)


def test_normalize_recipient_drops_plus_tag_and_folds_case():
    assert compliance.normalize_recipient("A.B+news@Example.COM") == "a.b@example.com"
