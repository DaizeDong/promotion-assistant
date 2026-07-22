#!/usr/bin/env python3
"""promotion-assistant CLI — the operator's mental model.

  promotion-assistant init       --config DIR        scaffold/point at a product config repo
  promotion-assistant channels   list                show registered channels + transport state
  promotion-assistant apply                          bridge secrets -> active config (delegates to
                                                       the config repo's own scripts/apply.py)
  promotion-assistant plan       --campaign C        build content calendar -> schedule-reminder
  promotion-assistant run        --campaign C [--once]   gated dispatch (DRY-RUN by default)
  promotion-assistant authorize  --channel X         print the exact per-channel live unlock steps
  promotion-assistant report     [--funnel|--bandit] funnel + arm convergence
  promotion-assistant doctor                         health / compliance / dry-run self-check

Everything is DRY-RUN unless product.json.send_mode==live AND PROMO_LIVE_AUTHORIZED_<CHANNEL> is set
(enforced in dispatch.py, not here).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# allow running as a plain script: make the skill dir importable as package root `scripts`
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts import config as _config        # noqa: E402
from scripts import events as _events         # noqa: E402
from scripts import metrics as _metrics       # noqa: E402
from scripts import orchestrate as _orch      # noqa: E402
from scripts import providers as _providers   # noqa: E402
from scripts.schedule_bridge import ScheduleBridge  # noqa: E402


def _load(args):
    return _config.load(getattr(args, "config", None))


def cmd_init(args):
    try:
        cfg = _load(args)
        print("config OK :", cfg.root)
        print("product   :", cfg.product.get("name"), "| send_mode:", cfg.send_mode)
    except _config.ConfigError as e:
        print("no config yet ->", e)
        print("create one from the template (see runbooks/new-machine.md) and set PROMO_CONFIG_DIR.")
        return 2
    return 0


def cmd_channels(args):
    cfg = _load(args)
    reg = _providers.build_registry()
    print("%-18s %-12s %-10s %s" % ("slug", "platform", "live?", "note"))
    for c in cfg.channels():
        plat = c.get("platform", c.get("slug"))
        prov = reg.get(plat, _providers.get(plat))
        live = "yes" if prov.LIVE_TRANSPORT else "DEFERRED"
        print("%-18s %-12s %-10s %s" % (c.get("slug"), plat, live,
              "" if prov.LIVE_TRANSPORT else prov.deferred_reason))
    return 0


def cmd_apply(args):
    cfg = _load(args)
    applier = cfg.root / "scripts" / "apply.py"
    if not applier.is_file():
        print("config repo has no scripts/apply.py (fork it from companion config kit). Skipping.")
        return 1
    print("delegating to", applier, "(never echoes secrets)")
    r = subprocess.run(["python", str(applier)] + (["--dry-run"] if args.dry_run else []),
                       cwd=str(cfg.root))
    return r.returncode


def cmd_plan(args):
    cfg = _load(args)
    res = _orch.plan(cfg, args.campaign, bridge=ScheduleBridge(), days=args.days)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args):
    cfg = _load(args)
    cw = int(args.conversion_window_days) * 86400 if args.conversion_window_days else None
    n = 1 if args.once else int(args.cycles)
    for _ in range(n):
        res = _orch.run_once(cfg, args.campaign, env=os.environ, conversion_window_s=cw)
        print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_authorize(args):
    ch = args.channel.upper().replace("-", "_")
    print("To go LIVE on channel %r (irreversible outreach — only after you control the account):" % args.channel)
    print("  1) set product.json send_mode = \"live\"")
    print("  2) export PROMO_LIVE_AUTHORIZED_%s=<any-non-empty-token>" % ch)
    print("  3) ensure the channel's secrets are applied (promotion-assistant apply)")
    print("Until BOTH are present, dispatch() simulates and writes metrics/dry-run.jsonl (zero egress).")
    return 0


def cmd_report(args):
    cfg = _load(args)
    evs = _events.read(cfg.metrics_dir() / "events.jsonl")
    if args.bandit:
        from scripts import bandit as _b
        b = _b.Bandit(cfg.metrics_dir() / "bandit-state.json")
        rows = sorted(b.arms.values(), key=lambda a: -(a["alpha"] / (a["alpha"] + a["beta"])))
        print("%-16s %8s %8s %8s" % ("arm", "alpha", "beta", "mean"))
        for a in rows:
            print("%-16s %8.2f %8.2f %8.3f" % (a["arm_id"], a["alpha"], a["beta"],
                  a["alpha"] / (a["alpha"] + a["beta"])))
    else:
        f = _metrics.funnel(evs, dims=("channel",))
        print("%-16s %6s %6s %6s %6s %6s %6s  %7s" %
              ("channel", "sent", "deliv", "view", "engage", "click", "conv", "cr_conv"))
        for key, b in f.items():
            print("%-16s %6d %6d %6d %6d %6d %6d  %7.3f" %
                  (key[0], b["L1_sent"], b["L2_delivered"], b["L3_view"], b["L4_engage"],
                   b["L5_click"], b["L6_conversion"], b["cr_conv"]))
    return 0


def cmd_doctor(args):
    cfg = _load(args)
    print("config root  :", cfg.root)
    print("send_mode    :", cfg.send_mode, "(default dry_run = safe)")
    print("schedule base:", "OK" if ScheduleBridge().available() else "MISSING")
    notifier = Path(os.path.expanduser(os.environ.get("PROMO_NOTIFIER_PY", "~/.local/notifier.py")))
    send_gmail = Path(os.path.expanduser(os.environ.get("PROMO_SEND_GMAIL", "~/.local/send-gmail.ps1")))
    print("relay        :", "OK" if notifier.is_file() else "MISSING")
    print("send-gmail   :", "OK" if send_gmail.is_file() else "MISSING")
    dry = cfg.metrics_dir() / "dry-run.jsonl"
    print("dry-run log  :", dry, "(exists)" if dry.is_file() else "(none yet)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="promotion-assistant")
    p.add_argument("--config", help="path to product config repo (else $PROMO_CONFIG_DIR)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sc = sub.add_parser("channels"); sc.add_argument("what", nargs="?", default="list"); sc.set_defaults(fn=cmd_channels)
    sa = sub.add_parser("apply"); sa.add_argument("--dry-run", action="store_true"); sa.set_defaults(fn=cmd_apply)
    sp = sub.add_parser("plan"); sp.add_argument("--campaign", required=True); sp.add_argument("--days", type=int, default=7); sp.set_defaults(fn=cmd_plan)
    sr = sub.add_parser("run"); sr.add_argument("--campaign", required=True); sr.add_argument("--once", action="store_true"); sr.add_argument("--cycles", default=1); sr.add_argument("--conversion-window-days", default=0); sr.set_defaults(fn=cmd_run)
    su = sub.add_parser("authorize"); su.add_argument("--channel", required=True); su.set_defaults(fn=cmd_authorize)
    srep = sub.add_parser("report"); srep.add_argument("--funnel", action="store_true"); srep.add_argument("--bandit", action="store_true"); srep.set_defaults(fn=cmd_report)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except _config.ConfigError as e:
        sys.stderr.write("promotion-assistant: no usable config (%s)\n" % e)
        sys.stderr.write("  -> run `promotion-assistant init --config <dir>`, or set $PROMO_CONFIG_DIR "
                         "to a product config repo (bootstrap: scripts/init_config.py; see "
                         "runbooks/new-machine.md).\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
