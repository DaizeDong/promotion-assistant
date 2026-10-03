#!/usr/bin/env python3
"""L1 bridge to the schedule-reminder base (its frozen CLI contract — never touch its .db/SQL).

We invoke the explicit argv below and require JSON on stdout (no --json flag is passed).
The installed helper contract must be checked during setup; availability alone is not proof.
We validate the acknowledgement and treat it as the durable record
of scheduled posts / email waves / DMs. Each promo item carries:
  --source promotion-assistant
  --idempotency-key promotion:<sha256 of product/campaign/arm/channel/account/action/date>   (replays never duplicate)
  --ext '{"x_promotion_campaign_id":..,"x_promotion_arm_id":..,"x_promotion_channel":..,"x_promotion_utm":..}'
  --due-at <ISO>   (drives the human-paced cadence)
Cross-channel dependencies use block/--blocker-id. Installed compatibility remains a setup check.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# schedule-reminder base CLI. Path is env-configurable so this is portable across machines;
# the default is a generic per-tool location, never a hardcoded personal install path.
REMINDER = Path(os.path.expanduser(
    os.environ.get("PROMO_REMINDER_PY", "~/.local/schedule-reminder/reminder.py")))


class ScheduleBridge:
    def __init__(self, reminder_path: Path | None = None, db_path: str | None = None):
        selected = reminder_path if reminder_path is not None else os.environ.get('PROMO_REMINDER_PY', REMINDER)
        self.reminder = Path(selected).expanduser()
        self.db_path = db_path

    def available(self) -> bool:
        return self.reminder.is_file()

    def _run(self, args):
        if not self.available():
            return {"ok": False, "error_code": "ERR_NO_BASE", "message": "schedule-reminder not installed"}
        cmd = [sys.executable, str(self.reminder)] + args
        env = None
        if self.db_path:
            env = dict(os.environ, SCHEDULE_DB_PATH=self.db_path)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return {'ok': False, 'message': 'schedule bridge unavailable: '+type(exc).__name__}
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            try:
                result = json.loads(out)
                if not isinstance(result, dict) or result.get('ok') is not True or result.get('error') or result.get('error_code'):
                    return {'ok': False, 'message': 'schedule bridge returned an error or invalid receipt'}
                if args[0] == 'ensure' and (not isinstance(result.get('item'), dict)
                                        or not result['item'].get('id')):
                    return {'ok': False, 'message': 'schedule ensure receipt has no item.id'}
                return result
            except (ValueError, TypeError):
                return {"ok": False, "message": "schedule bridge returned malformed JSON"}
        err = (r.stderr or "").strip()
        if err:
            try:
                failure = json.loads(err)
            except ValueError:
                failure = None
            if isinstance(failure, dict) and failure.get('ok') is False and failure.get('error_code'):
                return failure
        return {"ok": False, "message": err or "schedule bridge failed or returned no output"}

    def init(self):
        return self._run(["init"])

    def schedule_item(self, *, title, due_at, idempotency_key, ext: dict, description=""):
        fields = [
            "--title", title, "--kind", "task", "--due-at", due_at,
            "--source", "promotion-assistant",
            "--idempotency-key", idempotency_key,
            "--description", description,
            "--ext", json.dumps(ext, ensure_ascii=False),
        ]
        preflight = self._run(['creation-preflight', *fields])
        if not preflight.get('ok'):
            return preflight
        if (preflight.get('complete') is not True
                or preflight.get('decision') not in ('create', 'reuse', 'review')
                or not isinstance(preflight.get('matches'), list)):
            return {'ok': False, 'error_code': 'ERR_CREATION_REVIEW',
                    'message': 'Review schedule candidates before creating this obligation.',
                    'preflight': preflight}
        # ensure permits an exact replay even after completion, but never creates an
        # ambiguous obligation without explicit review options (which we do not pass).
        return self._run(['ensure', *fields])

    def list_active(self):
        return self._run(["list", "--source", "promotion-assistant", "--active", "--limit", "200"])

    def progress(self, item_id, stage):
        return self._run(["transition", "--id", str(item_id), "--to", "doing",
                          "--reason", "promo:%s" % stage])
