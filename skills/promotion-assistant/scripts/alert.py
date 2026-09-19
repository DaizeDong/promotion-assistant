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

# Local notifier (one-way push to the operator). Env-configurable for portability; the default is
# a generic per-tool path, never a hardcoded personal install location.
RELAY = Path(os.path.expanduser(
    os.environ.get("PROMO_NOTIFIER_PY", "~/.local/notifier.py")))


def _egress_cmd():
    """Pluggable Agent Center egress: prefer schedule-reminder's unified relay (#promotion stream)
    when the base is installed; fall back to the Big Brother relay (send.py) so this works
    standalone. Caller appends the message as the final arg."""
    rp = os.environ.get("SCHEDULE_RELAY_PY") or os.path.expanduser(
        "~/.local/schedule-reminder/relay.py")
    if os.path.isfile(rp):
        return [sys.executable, rp, "send", "--stream", "promotion", "--text"]
    if RELAY.is_file():
        return [sys.executable, str(RELAY)]
    return None


def _notification_client():
    import importlib.util
    from pathlib import Path
    path = Path(os.environ.get('SCHEDULE_NOTIFICATION_CLIENT') or
                Path.home() / '.claude/skills/schedule-reminder/scripts/notification_client.py')
    if not path.is_file():
        raise RuntimeError('shared notification client missing; bind SCHEDULE_NOTIFICATION_CLIENT')
    spec = importlib.util.spec_from_file_location('_owner_notification_client', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alert(message: str, *, dry_run=False, run_id=None, condition='anomaly',
          retry_failed=False) -> dict:
    if dry_run or os.environ.get('AGENT_CENTER_RELAY_DRYRUN'):
        return {'status': 'dry-run', 'message': message}
    cmd = _egress_cmd()
    if not cmd:
        return {'status': 'no-relay', 'message': message}
    try:
        client = _notification_client()
        receipt = client.submit('promotion-assistant', run_id, 'alert', condition, 'promotion',
            message, language='preserve', retry_failed=retry_failed,
            **client.transport_options(cmd, 'promotion'))
        return {'status': 'sent' if receipt['state'] == 'sent' else 'error',
                'rc': 0 if receipt['state'] == 'sent' else 1, 'receipt': receipt}
    except Exception as exc:
        return {'status': 'error', 'reason': type(exc).__name__}
