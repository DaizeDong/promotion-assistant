#!/usr/bin/env python3
"""Alert channel — promotion anomalies -> Discord relay (Big Brother bot, Claude->phone, one-way).

Periodic 'due' reminders ride schedule-reminder's own tick/relay. THIS module is for promotion
EXCEPTIONS that must page the operator now: ban/shadowban detected, deliverability drop, unsub
spike, a dry-run that caught a would-be real send, or a warmup milestone reached. We shell out to
the existing relay (do NOT reimplement notification, do NOT mix with the Haptic scheduler bot).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

RELAY = Path.home() / ".local" / "notifier.py"


def alert(message: str, *, dry_run=False) -> dict:
    if not RELAY.is_file():
        return {"status": "no-relay", "message": message}
    if dry_run:
        return {"status": "dry-run", "message": message}
    try:
        r = subprocess.run(["python", str(RELAY), message], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return {"status": "sent" if r.returncode == 0 else "error", "rc": r.returncode}
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": str(e)[:200]}
