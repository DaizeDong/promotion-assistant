#!/usr/bin/env python3
"""L3 compliance gate — fail-closed, pre-send (Side-A).

Compliance is engineering, not goodwill: CAN-SPAM / GDPR / suppression are encoded as a
gate that REFUSES the dispatch when any requirement is missing. There is no "warn and
send" path. A missing physical address, a missing unsubscribe, a suppressed recipient,
or an EU recipient without a lawful basis -> REJECT.

check() returns (ok: bool, reasons: list[str]). dispatch.py calls it before the outbound
exit; the acceptance gate (E5) feeds it deliberately-broken payloads and asserts 100%
rejection.

EVASION HARDENING (v0.1.2): the matchers used to be trivially bypassable —
  * banned-claim / body text via zero-width chars (U+200B..) and homoglyphs (Cyrillic/Greek
    lookalikes) -> now text is NFKC-normalized, zero-width/format chars stripped, and common
    confusables folded to ASCII before substring matching.
  * suppression via a `+tag` alias or case/dot noise -> the recipient AND the stored list are
    normalized the same way (local-part `+tag` dropped, NFKC, casefold) before comparison.
  * CAN-SPAM skipped by mislabeling an email as transport="post" -> email checks now fire when
    the payload LOOKS like email (recipient is an email address, or channel/transport says so),
    not only when transport=="smtp".
Normalization is applied ONLY for matching; the original payload is never mutated.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

# Countries under GDPR/PECR-style consent regimes (subset; extend in config/policy.json).
EU_EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "IS", "LI", "NO", "GB",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Common Cyrillic/Greek/misc lowercase homoglyphs -> ASCII. NFKC does NOT fold these
# (they are distinct letters), so an explicit confusable map is required.
_CONFUSABLES = {
    # Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "у": "y", "х": "x", "ѕ": "s", "і": "i", "ј": "j",
    "һ": "h", "ԁ": "d", "к": "k", "в": "b", "м": "m",
    "н": "h", "т": "t",
    # Greek
    "ο": "o", "α": "a", "ε": "e", "ρ": "p", "ν": "v",
    "ι": "i", "κ": "k", "χ": "x", "υ": "u", "γ": "y",
    "τ": "t", "μ": "u",
}
# Unicode "format" chars (category Cf) + soft hyphen are stripped outright.
_STRIP_EXTRA = {"­"}

# Built-in over-claim floor (see check(): merged with the product's banned_claims, never removable).
# Scam-adjacent superlatives that competitors over-use; using them taints the brand. Matched as
# NORMALIZED substrings, so "un­limited free" (zero-width) and homoglyph variants are caught too.
DEFAULT_OVERCLAIM = [
    "unlimited free", "free forever", "no limits", "no rate limit", "no rate limits",
    "never rate limited", "unlimited tokens", "unlimited requests", "100% free",
    "completely free", "no cost ever", "always free", "infinite tokens",
]


def _normalize_text(s: str) -> str:
    """Fold text to a canonical ASCII-ish form for robust substring matching.

    NFKC -> strip zero-width/format chars + soft hyphen -> fold known confusables -> casefold
    -> collapse whitespace. Used only for matching; never mutates the payload.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    out = []
    for ch in s:
        if ch in _STRIP_EXTRA or unicodedata.category(ch) == "Cf":
            continue  # zero-width space/joiner/BOM/soft hyphen etc.
        out.append(_CONFUSABLES.get(ch, ch))
    s = "".join(out).casefold()
    return re.sub(r"\s+", " ", s).strip()


def normalize_recipient(recip: str) -> str:
    """Canonical form of a recipient for suppression matching.

    Lowercase + NFKC + strip format chars; for email addresses drop the local-part `+tag`
    alias (a@example.com and a+promo@example.com are the same mailbox for suppression purposes).
    """
    r = _normalize_text(recip).replace(" ", "")
    if "@" in r:
        local, _, domain = r.partition("@")
        local = local.split("+", 1)[0]  # drop +tag alias
        r = local + "@" + domain
    return r


def _looks_like_email(recip: str) -> bool:
    return bool(_EMAIL_RE.match((recip or "").strip()))


def _is_email(payload: dict) -> bool:
    """Email-specific checks fire when the payload is email-like — by transport, channel, OR the
    recipient actually being an email address — so a mislabeled transport can't skip CAN-SPAM."""
    transport = (payload.get("transport") or "").strip().lower()
    channel = (payload.get("channel") or "").strip().lower()
    if transport in ("smtp", "email", "mail", "ses", "sendgrid"):
        return True
    if channel in ("email", "mail", "smtp", "newsletter"):
        return True
    return _looks_like_email(payload.get("recipient") or "")


def load_suppression(path: Path) -> set:
    """Suppression list (unsubscribes + hard bounces + complaints). Checked every send.
    Entries are stored normalized (alias/case/unicode-folded) so evasive variants still hit."""
    sup = set()
    if path.is_file():
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if row and row[0].strip():
                    sup.add(normalize_recipient(row[0]))
    return sup


def load_consent_ledger(path: Path) -> dict:
    """email(normalized) -> consent record. EU recipients need a lawful basis here."""
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            who = normalize_recipient(rec.get("email") or "")
            if who:
                out[who] = rec
    return out


def check(payload: dict, *, policy: dict, suppression: set, consent: dict) -> tuple:
    """Validate a single outbound payload. Returns (ok, reasons).

    payload keys used:
      channel, transport, recipient (email or handle), recipient_country (ISO2, optional),
      from_addr, reply_to, physical_address, unsubscribe, subject, body.
    """
    reasons = []
    recip_norm = normalize_recipient(payload.get("recipient") or "")

    # --- suppression (all channels with an addressable recipient) ---
    if recip_norm and recip_norm in suppression:
        reasons.append("recipient on suppression list")

    if _is_email(payload):
        # --- CAN-SPAM ---
        if not payload.get("from_addr"):
            reasons.append("CAN-SPAM: missing real From")
        if not payload.get("physical_address") and not policy.get("physical_address"):
            reasons.append("CAN-SPAM: missing physical postal address")
        if not payload.get("unsubscribe"):
            reasons.append("CAN-SPAM: missing functional unsubscribe")
        subj = (payload.get("subject") or "").strip()
        if not subj:
            reasons.append("CAN-SPAM: empty/missing subject")
        # crude deception guard: subject must not be a bare RE:/FWD: with no context
        if subj[:3].upper() in ("RE:", "FW:") and len(subj) <= 4:
            reasons.append("CAN-SPAM: deceptive subject")

        # --- GDPR / consent for EU recipients ---
        country = (payload.get("recipient_country") or "").upper()
        if country in EU_EEA:
            rec = consent.get(recip_norm)
            if not rec or not rec.get("lawful_basis"):
                reasons.append("GDPR: EU recipient without lawful basis in consent ledger")

    # --- banned product claims (any channel), matched on normalized text so zero-width /
    #     homoglyph obfuscation cannot slip a banned claim past the gate ---
    #     The product's own banned_claims PLUS a built-in over-claim floor: the 2026-07 expansion
    #     research found that out-claiming competitors ("unlimited free", "no limits") inherits their
    #     scam-adjacent reputation and gets the brand flamed across the RP scene. These phrases are
    #     forbidden by DEFAULT for every product; a product can add more via banned_claims but cannot
    #     remove these -- honest differentiation (stability / breadth / real price), never over-claim.
    body_norm = _normalize_text((payload.get("body") or "") + " " + (payload.get("subject") or ""))
    for claim in list(policy.get("banned_claims", [])) + DEFAULT_OVERCLAIM:
        cn = _normalize_text(claim)
        if cn and cn in body_norm:
            reasons.append("banned claim present: %r" % claim)

    return (len(reasons) == 0, reasons)


def record_unsub(path: Path, recipient: str) -> None:
    """Append a recipient to suppression immediately (stored normalized; dedupe on read)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([normalize_recipient(recipient)])
