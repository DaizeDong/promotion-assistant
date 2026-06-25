#!/usr/bin/env python3
"""L1 bridge to the schedule-reminder base (its frozen CLI contract — never touch its .db/SQL).

We only invoke `reminder.py <verb> --json`, parse stdout JSON, and treat it as the durable record
of scheduled posts / email waves / DMs. Each promo item carries:
  --source promotion-assistant --actor promotion-assistant
  --idempotency-key promotion:<product>:<arm>:<yyyymmdd>   (replays never duplicate)
  --ext '{"x_promotion_campaign_id":..,"x_promotion_arm_id":..,"x_promotion_channel":..,"x_promotion_utm":..}'
  --due-at <ISO>   (drives the human-paced cadence)
Cross-channel dependencies use block/--blocker-id. Contract api_version is additive-only -> safe.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REMINDER = Path.home() / ".local" / "schedule-reminder" / "reminder.py"


class ScheduleBridge:
    def __init__(self, reminder_path: Path | None = None, db_path: str | None = None):
        self.reminder = Path(reminder_path) if reminder_path else REMINDER
        self.db_path = db_path

    def available(self) -> bool:
        return self.reminder.is_file()

    def _run(self, args):
        if not self.available():
            return {"ok": False, "error_code": "ERR_NO_BASE", "message": "schedule-reminder not installed"}
        cmd = ["python", str(self.reminder)] + args
        env = None
        if self.db_path:
            import os
            env = dict(os.environ, SCHEDULE_DB_PATH=self.db_path)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env)
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            try:
                return json.loads(out.splitlines()[-1])
            except Exception:
                return {"ok": True, "raw": out}
        err = (r.stderr or "").strip()
        try:
            return json.loads(err.splitlines()[-1]) if err else {"ok": False, "message": "no output"}
        except Exception:
            return {"ok": False, "message": err or "unknown error"}

    def init(self):
        return self._run(["init"])

    def schedule_item(self, *, title, due_at, idempotency_key, ext: dict, description=""):
        return self._run([
            "add", "--title", title, "--kind", "task", "--due-at", due_at,
            "--source", "promotion-assistant",
            "--idempotency-key", idempotency_key,
            "--description", description,
            "--ext", json.dumps(ext, ensure_ascii=False),
        ])

    def list_active(self):
        return self._run(["list", "--source", "promotion-assistant", "--active", "--limit", "200"])

    def progress(self, item_id, stage):
        return self._run(["transition", "--id", str(item_id), "--to", "in_progress",
                          "--reason", "promo:%s" % stage])
