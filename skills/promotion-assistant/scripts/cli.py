#!/usr/bin/env python3
"""promotion-assistant CLI — the operator's mental model.

  promotion-assistant init       --config DIR        scaffold/point at a product config repo
  promotion-assistant channels   list                show registered channels + transport state
  promotion-assistant apply                          bridge secrets -> active config (delegates to
                                                       the config repo's own scripts/apply.py)
  promotion-assistant plan       --campaign C        build content calendar -> schedule-reminder
  promotion-assistant run        --campaign C [--once]   gated dispatch (DRY-RUN by default)
  promotion-assistant prep       --campaign C [--channel X]  manual-prep: emit human-postable copy +
                                                       aff link + compliance checklist (ToS-hostile
                                                       surfaces: megathread / Chub card / PH / HN)
  promotion-assistant record-post --channel X --url U     log a human's post as 'sent' (loop-close)
  promotion-assistant content     [guides|card] [--frontend F]  durable SEO setup guides + proxy card
  promotion-assistant refer       --handle H         mint an advocate ref code + invite copy
  promotion-assistant growth      [listing|keybot]   Discord-directory listing assets / /key bot spec
  promotion-assistant participate discover --sub S   compliant human-in-loop community copilot:
  promotion-assistant participate draft --url U        surface threads your expertise fits, draft a
  promotion-assistant participate status               genuine reply you edit+post BY HAND, track
  promotion-assistant participate record --url U       give-before-ask readiness, attribute your posts
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
        res = _orch.run_once(cfg, args.campaign, env=os.environ, conversion_window_s=cw,
                             channel=getattr(args, "channel", None))
        print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_prep(args):
    """Manual-prep: emit the finished, bandit-selected copy + aff link + a compliance checklist for a
    HUMAN to post on a ToS-hostile surface (megathread, Chub card, PH/HN). No egress."""
    cfg = _load(args)
    res = _orch.prep_once(cfg, args.campaign, channel=args.channel)
    if res.get("status") != "prepared":
        print(json.dumps(res, ensure_ascii=False))
        return 1
    p = res["prepared"]
    print("=" * 66)
    print("PREP for %s  (arm: %s)" % (p.get("surface"), res.get("arm")))
    print("=" * 66)
    print("\n--- COPY (paste this) ---\n")
    print(p.get("copy"))
    print("\n--- COMPLIANCE CHECKLIST (a human posts; automated egress here = spam/ban) ---")
    for line in p.get("checklist", []):
        print("  [ ] " + line)
    print("\n--- AFTER YOU POST ---")
    print("  " + p.get("reminder"))
    print("  (this records the human post as a 'sent' event so a later register?aff conversion")
    print("   attributes back to arm %s and the bandit learns)" % res.get("arm"))
    return 0


def cmd_record_post(args):
    """Close the loop after a human posted a prepped item: writes a real 'sent' event tying the post
    URL to the arm (attribution + bandit update on a later conversion)."""
    cfg = _load(args)
    res = _orch.record_post(cfg, args.channel, args.url, arm_id=args.arm_id, campaign=args.campaign)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("status") == "recorded" else 1


def cmd_participate(args):
    """Compliant, human-in-the-loop community-participation copilot. Augments a REAL person's
    genuine participation -- discovers threads their expertise fits, drafts a genuine answer they
    edit, tracks their give-before-ask readiness, and records their own posts for attribution.
    NEVER posts/votes (no egress path); the human is always the publisher and endorser."""
    cfg = _load(args)
    from scripts import participation as _p
    from scripts import reddit_read as _rr
    sub = args.what

    if sub == "discover":
        # Read-only. Prefer official OAuth (your account); else emit the site:reddit.com queries for
        # the operator to run through their search tooling (tavily/brightdata). Never scrapes.
        secrets = cfg.root / "secrets" / "reddit.env"
        creds = _rr.load_reddit_creds(secrets)
        posts = []
        if creds:
            tok, err = _rr.get_oauth_token(creds)
            if tok:
                posts, ferr = _rr.fetch_new(args.sub, tok, creds["REDDIT_USER_AGENT"],
                                            limit=int(args.limit))
                if ferr:
                    print("fetch error: %s" % ferr)
            else:
                print("oauth error: %s" % err)
        if not posts:
            pains = (cfg.product.get("pain_points")
                     or ["proxy 500 errors", "rate limits", "which API to use"])
            cat = cfg.product.get("category", "OpenAI-compatible gateway")
            comps = cfg.product.get("competitors", [])
            queries = _rr.build_search_queries(pains, cat, competitors=comps, subreddit=args.sub)
            print("No Reddit OAuth creds (secrets/reddit.env) -- run these site:reddit.com searches")
            print("through your search tooling (tavily/brightdata), then feed results back:\n")
            for q in queries[:12]:
                print("  " + q)
            return 0
        import time as _t
        ranked = _p.rank_opportunities(posts, now_ts=_t.time())
        shown = [r for r in ranked if r["_score"]["label"] in ("immediate", "build")][:int(args.top)]
        print("=" * 66)
        print("OPPORTUNITY QUEUE  r/%s  (%d scored, showing top %d actionable)"
              % (args.sub, len(ranked), len(shown)))
        print("=" * 66)
        for r in shown:
            s = r["_score"]
            print("\n[%s  score=%.2f]  %s" % (s["label"].upper(), s["total"], r["title"][:80]))
            print("  fit=%.2f need=%.2f fresh=%.2f unanswered=%.2f  %s"
                  % (s["scores"].get("expertise_fit", 0), s["scores"].get("need_intensity", 0),
                     s["scores"].get("freshness", 0), s["scores"].get("unanswered", 0),
                     r.get("permalink", "")))
        print("\n(these are SURFACED for you to consider -- draft a genuine reply with:")
        print(" promotion-assistant participate draft --url <permalink>)")
        return 0

    if sub == "draft":
        # Build a genuine-help draft grounded in the person's real expertise. Draft-only.
        from scripts import participation as _pp
        graduated = bool(args.graduated)
        product = cfg.product.get("product") or cfg.product.get("name") or "the product"
        aff = cfg.aff_base + (args.aff_code or "reddit_participation")
        # thread context: the human pastes title/body (or a fetched post could be passed); keep simple
        post = {"title": args.title or "", "body": args.body or "", "intent": args.intent}
        prompt = _pp.build_draft_prompt(post, graduated=graduated, product=product, aff_url=aff)
        draft_text = None
        try:
            import llmcall
            res = llmcall.call(prompt, mode="agent")
            draft_text = getattr(res, "text", None) or str(res)
        except Exception as e:
            print("(llmcall unavailable: %s -- here is the prompt to run manually)\n" % str(e)[:80])
            print(prompt)
            return 0
        # over-claim guard on the generated draft
        from scripts import compliance as _c
        ok, reasons = _c.check({"body": draft_text, "transport": "post"},
                               policy={"banned_claims": cfg.banned_claims},
                               suppression=set(), consent={})
        # record a 'drafted' event (attribution scaffold)
        ev = _events.make_event("reddit-participation", "drafted", platform="reddit",
                                account="self", value=0.0,
                                utm={"source": "reddit", "medium": "comment",
                                     "content": args.aff_code or "reddit_participation"},
                                graduated=graduated)
        _events.append(cfg.metrics_dir() / "events.jsonl", ev)
        print("=" * 66)
        print("DRAFT REPLY  (edit in your own voice, then post BY HAND)")
        print("=" * 66)
        if not ok:
            print("!! over-claim guard flagged the draft: %s" % "; ".join(reasons))
            print("!! revise before posting.\n")
        print("\n" + (draft_text or "").strip() + "\n")
        print("-" * 66)
        print("After you post it yourself, close the loop:")
        print("  promotion-assistant participate record --url <your-comment-permalink>")
        return 0

    if sub == "status":
        # Readiness dashboard: give-before-ask ledger + account standing + graduation criteria.
        from scripts import participation as _pp
        evs = _events.read(cfg.metrics_dir() / "events.jsonl")
        parts = [e for e in evs if e.get("channel") == "reddit-participation"]
        # ledger: 'drafted'/'sent' non-promo = give; anything carrying an aff link intent = ask.
        entries = []
        for e in parts:
            if e.get("event_type") in ("drafted", "sent"):
                is_ask = bool((e.get("utm", {}) or {}).get("content")) and e.get("graduated")
                entries.append({"type": "ask" if is_ask else "give",
                                "url": e.get("post_url"), "ts": e.get("ts")})
        account = {
            "age_days": args.age_days, "karma": args.karma,
            "sub_gives": sum(1 for x in entries if x["type"] == "give" and x.get("url")),
            "mod_strikes": args.strikes or 0,
        }
        rd = _pp.readiness(account, entries)
        print("=" * 66)
        print("PARTICIPATION READINESS")
        print("=" * 66)
        lb = rd["ledger"]
        print("give-before-ask ledger: %d gives / %d asks  (ratio %s, 9:1 %s)"
              % (lb["gives"], lb["asks"],
                 ("inf" if lb["ratio"] == float("inf") else "%.1f" % lb["ratio"]),
                 "HELD" if lb["holds_9to1"] else "NOT held"))
        print("\ngraduation criteria (%d/%d met):" % (rd["met"], rd["total"]))
        for c in rd["criteria"]:
            print("  [%s] %s" % ("x" if c["met"] else " ", c["detail"]))
        print("\n=> %s" % rd["verdict"])
        if rd["next"]:
            print("   next: %s" % rd["next"][0])
        return 0

    if sub == "record":
        res = _orch.record_participation(cfg, args.url, thread=args.thread)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("status") == "recorded" else 1

    print("unknown participate action: %r" % sub)
    return 1


def cmd_content(args):
    """Generate durable SEO setup guides (+ a proxy card) for a human to publish. Zero egress; every
    link carries register?aff=<code>; over-claim copy is refused by the compliance floor."""
    cfg = _load(args)
    from scripts import content as _content
    if args.what == "card":
        res = _content.build_proxy_card(cfg, aff_code=args.aff_code)
        if res.get("status") != "ok":
            print(json.dumps(res, ensure_ascii=False)); return 1
        print("### %s\n" % res["title"]); print(res["blurb"])
        return 0
    guides = ([_content.build_guide(cfg, args.frontend, aff_code=args.aff_code)]
              if args.frontend else _content.build_all(cfg, aff_code=args.aff_code))
    for g in guides:
        if g.get("status") != "ok":
            print("## [%s] %s" % (g.get("frontend"), g.get("reason"))); continue
        print("\n" + "=" * 70)
        print(g["markdown"])
    print("\n(publish these as your own content -- blog/Medium/dev.to; the aff link tracks conversions)")
    return 0


def cmd_refer(args):
    """Mint an advocate ref code + the invite copy they share (link carries their code -> their
    referrals attribute back to them). Zero egress; over-claim copy is refused."""
    cfg = _load(args)
    from scripts import referral as _referral
    res = _referral.invite_copy(cfg, args.handle, reward_hint=args.reward or "")
    if res.get("status") != "ok":
        print(json.dumps(res, ensure_ascii=False)); return 1
    print("advocate : %s" % res["advocate"])
    print("ref code : %s" % res["code"])
    print("aff link : %s" % res["aff_url"])
    print("\n--- invite copy (they share this) ---\n")
    print(res["copy"])
    return 0


def cmd_growth(args):
    """Generate the Discord-directory listing assets (DISBOARD/top.gg/Discadia) for the owned server,
    or the /key onboarding-bot spec. Human submits the listing; the server's own bot runs /bump."""
    cfg = _load(args)
    from scripts import growth as _growth
    if args.what == "listing":
        res = _growth.listing(cfg)
        print("### Discord server listing (submit to DISBOARD / top.gg / Discadia)\n")
        print("Name: %s" % res["name"])
        print("Tags: %s" % ", ".join(res["tags"]))
        print("\nDescription:\n%s" % res["description"])
        print("\nSubmit at:")
        for u in res["directories"]:
            print("  - %s" % u)
        print("\nBump: %s" % res["bump_note"])
    else:  # keybot
        print(_growth.keybot_spec(cfg))
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
    sr = sub.add_parser("run"); sr.add_argument("--campaign", required=True); sr.add_argument("--once", action="store_true"); sr.add_argument("--cycles", default=1); sr.add_argument("--conversion-window-days", default=0); sr.add_argument("--channel", help="restrict the bandit arm pool to one channel (per-channel go-live)"); sr.set_defaults(fn=cmd_run)
    sco = sub.add_parser("content"); sco.add_argument("what", nargs="?", default="guides", choices=["guides", "card"]); sco.add_argument("--frontend", choices=["janitorai", "sillytavern", "risu", "agnai"]); sco.add_argument("--aff-code", dest="aff_code"); sco.set_defaults(fn=cmd_content)
    sref = sub.add_parser("refer"); sref.add_argument("--handle", required=True); sref.add_argument("--reward"); sref.set_defaults(fn=cmd_refer)
    sg = sub.add_parser("growth"); sg.add_argument("what", nargs="?", default="listing", choices=["listing", "keybot"]); sg.set_defaults(fn=cmd_growth)
    spr = sub.add_parser("prep"); spr.add_argument("--campaign", required=True); spr.add_argument("--channel"); spr.set_defaults(fn=cmd_prep)
    src = sub.add_parser("record-post"); src.add_argument("--channel", required=True); src.add_argument("--url", required=True); src.add_argument("--arm-id"); src.add_argument("--campaign"); src.set_defaults(fn=cmd_record_post)
    spa = sub.add_parser("participate")
    spa.add_argument("what", choices=["discover", "draft", "status", "record"])
    spa.add_argument("--sub", help="subreddit (discover)")
    spa.add_argument("--limit", default=25, help="discover: posts to fetch")
    spa.add_argument("--top", default=8, help="discover: actionable leads to show")
    spa.add_argument("--url", help="draft-source or record: post/comment permalink")
    spa.add_argument("--title", help="draft: the thread title")
    spa.add_argument("--body", help="draft: the thread body")
    spa.add_argument("--intent", help="draft: recommendation|troubleshooting|comparison|workflow")
    spa.add_argument("--aff-code", dest="aff_code", help="draft: aff tracking code")
    spa.add_argument("--graduated", action="store_true", help="draft: account has graduated (allow 90/10 disclosed mention)")
    spa.add_argument("--age-days", dest="age_days", type=int, help="status: account age in days")
    spa.add_argument("--karma", type=int, help="status: account karma")
    spa.add_argument("--strikes", type=int, help="status: mod removals/strikes")
    spa.add_argument("--thread", help="record: source thread url")
    spa.set_defaults(fn=cmd_participate)
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
