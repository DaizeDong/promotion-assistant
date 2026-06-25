#!/usr/bin/env python3
"""L3 compliance gate — fail-closed, pre-send (Side-A).

Compliance is engineering, not goodwill: CAN-SPAM / GDPR / suppression are encoded as a
gate that REFUSES the dispatch when any requirement is missing. There is no "warn and
send" path. A missing physical address, a missing unsubscribe, a suppressed recipient,
or an EU recipient without a lawful basis -> REJECT.

check() returns (ok: bool, reasons: list[str]). dispatch.py calls it before the outbound
exit; the acceptance gate (E5) feeds it deliberately-broken payloads and asserts 100%
rejection.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

# Countries under GDPR/PECR-style consent regimes (subset; extend in config/policy.json).
EU_EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "IS", "LI", "NO", "GB",
}


def load_suppression(path: Path) -> set:
    """Suppression list (unsubscribes + hard bounces + complaints). Checked every send."""
    sup = set()
    if path.is_file():
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if row:
                    sup.add(row[0].strip().lower())
    return sup


def load_consent_ledger(path: Path) -> dict:
    """email(lower) -> consent record. EU recipients need a lawful basis here."""
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            who = (rec.get("email") or "").strip().lower()
            if who:
                out[who] = rec
    return out


def check(payload: dict, *, policy: dict, suppression: set, consent: dict) -> tuple:
    """Validate a single outbound payload. Returns (ok, reasons).

    payload keys used:
      channel, transport ("smtp" triggers email-specific checks),
      recipient (email or handle), recipient_country (ISO2, optional),
      from_addr, reply_to, physical_address, unsubscribe, subject, body.
    """
    reasons = []
    transport = payload.get("transport", "")
    recip = (payload.get("recipient") or "").strip().lower()

    # --- suppression (all channels with an addressable recipient) ---
    if recip and recip in suppression:
        reasons.append("recipient on suppression list")

    if transport == "smtp":
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
            rec = consent.get(recip)
            if not rec or not rec.get("lawful_basis"):
                reasons.append("GDPR: EU recipient without lawful basis in consent ledger")

    # --- banned product claims (any channel) ---
    body = (payload.get("body") or "") + " " + (payload.get("subject") or "")
    for claim in policy.get("banned_claims", []):
        if claim and claim.lower() in body.lower():
            reasons.append("banned claim present: %r" % claim)

    return (len(reasons) == 0, reasons)


def record_unsub(path: Path, recipient: str) -> None:
    """Append a recipient to suppression immediately (idempotent-ish; dedupe on read)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([recipient.strip().lower()])
