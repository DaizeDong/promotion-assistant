#!/usr/bin/env python3
"""Alert channel — promotion anomalies -> Discord relay (Big Brother bot, Claude->phone, one-way).

Periodic 'due' reminders ride schedule-reminder's own tick/relay. THIS module is for promotion
EXCEPTIONS that must page the operator now: ban/shadowban detected, deliverability drop, unsub
spike, a dry-run that caught a would-be real send, or a warmup milestone reached. We shell out to
the existing relay (do NOT reimplement notification, do NOT mix with the Haptic scheduler bot).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RELAY = Path.home() / ".claude" / "discord_relay" / "send.py"


def _egress_cmd():
    """Pluggable Agent Center egress: prefer schedule-reminder's unified relay (#promotion stream)
    when the base is installed; fall back to the Big Brother relay (send.py) so this works
    standalone. Caller appends the message as the final arg."""
    rp = os.environ.get("SCHEDULE_RELAY_PY") or str(
        Path.home() / ".claude/skills/schedule-reminder/scripts/relay.py")
    if os.path.isfile(rp):
        return [sys.executable, rp, "send", "--stream", "promotion", "--text"]
    if RELAY.is_file():
        return [sys.executable, str(RELAY)]
    return None


def alert(message: str, *, dry_run=False) -> dict:
    cmd = _egress_cmd()
    if not cmd:
        return {"status": "no-relay", "message": message}
    if dry_run:
        return {"status": "dry-run", "message": message}
    try:
        r = subprocess.run(cmd + [message], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return {"status": "sent" if r.returncode == 0 else "error", "rc": r.returncode}
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": str(e)[:200]}
