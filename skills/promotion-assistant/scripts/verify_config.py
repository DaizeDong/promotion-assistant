#!/usr/bin/env python3
"""Doctor for the promotion-assistant companion config (config-spec E3).

Resolves the config dir via the documented discovery order, validates it against the real schema
(/CONFIG.md + reference/config-schema.md), and prints PASS/FAIL per check naming exactly what is
missing. Exit 0 = ready, 1 = not ready, 2 = usage error. Never echoes secret values.

Discovery order (config-spec E2; first hit wins):
  1. $PROMO_CONFIG_DIR  2. $PROMOTION_ASSISTANT_CONFIG  3. $PROMOTION_ASSISTANT_CONFIG_DIR
  4. ~/.promotion-assistant-config/   5. ~/.config/promotion-assistant-config/

Usage:
  python verify_config.py [--config-dir <dir>]
Stdlib only.
"""
import argparse
import json
import os
import sys

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
ENV_VARS = ("PROMO_CONFIG_DIR", "PROMOTION_ASSISTANT_CONFIG", "PROMOTION_ASSISTANT_CONFIG_DIR")
SEND_MODES = ("dry_run", "sim", "test_account", "live")


def discover(override):
    if override:
        return os.path.abspath(os.path.expanduser(override)), "explicit (--config-dir)"
    for v in ENV_VARS:
        val = os.environ.get(v)
        if val:
            return os.path.abspath(os.path.expanduser(val)), "env:%s" % v
    for d in (os.path.expanduser("~/.promotion-assistant-config"),
              os.path.expanduser("~/.config/promotion-assistant-config")):
        if os.path.isdir(d):
            return d, "default:%s" % d
    return None, None


def _load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="Validate the promotion-assistant companion config (Mode B).")
    ap.add_argument("--config-dir", default=None)
    a = ap.parse_args()

    cfg, how = discover(a.config_dir)
    print("Config doctor for skill 'promotion-assistant'")
    print("Discovery: %s (first hit wins)" % " -> ".join("$" + v for v in ENV_VARS))
    if not cfg:
        print("  [%s] config located -> none found." % FAIL)
        print("       Set %s=<dir> or run: python scripts/init_config.py" % ENV_VARS[0])
        return 1
    print("  resolved via %s -> %s" % (how, cfg))
    print("-" * 64)

    results = []  # (name, ok, level, detail)

    def check(name, ok, detail="", level=FAIL):
        results.append((name, ok, level, detail))

    check("config dir exists", os.path.isdir(cfg))

    # product.json, required, drives the global send_mode gate.
    prod = os.path.join(cfg, "product.json")
    prod_ok = os.path.isfile(prod)
    check("product.json present", prod_ok)
    if prod_ok:
        try:
            p = _load_json(prod)
            check("product.json valid JSON", True)
            sm = p.get("send_mode", "dry_run")
            check("send_mode in {dry_run,sim,test_account,live}", sm in SEND_MODES, "got %r" % sm)
            check("product.json has name", bool(p.get("name")) and p.get("name") != "<product-name>",
                  "name is empty/placeholder", level=WARN)
        except Exception as e:
            check("product.json valid JSON", False, str(e))

    # registry.json, channels list; each channel needs a slug.
    reg = os.path.join(cfg, "registry.json")
    reg_ok = os.path.isfile(reg)
    check("registry.json present", reg_ok)
    channels = []
    if reg_ok:
        try:
            r = _load_json(reg)
            check("registry.json valid JSON", True)
            channels = r.get("channels", [])
            check("registry.channels[] is a list", isinstance(channels, list),
                  "type %s" % type(channels).__name__)
            if isinstance(channels, list):
                bad = [i for i, c in enumerate(channels) if not (isinstance(c, dict) and c.get("slug"))]
                check("every channel has a slug", not bad, "rows missing slug: %s" % bad)
        except Exception as e:
            check("registry.json valid JSON", False, str(e))

    # per-channel policy is hot-swappable; missing policy is a WARN (defaults apply), not a hard fail.
    if isinstance(channels, list):
        for c in channels:
            if isinstance(c, dict) and c.get("slug"):
                slug = c["slug"]
                pol = os.path.join(cfg, "channels", slug, "policy.json")
                check("channels/%s/policy.json present" % slug, os.path.isfile(pol),
                      "no policy -> engine defaults apply", level=WARN)

    # structure dirs
    check("secrets/ dir present", os.path.isdir(os.path.join(cfg, "secrets")))

    # secrets gate (Mode B, E6)
    gi = os.path.join(cfg, ".gitignore")
    gi_ok = os.path.isfile(gi)
    check(".gitignore present", gi_ok)
    if gi_ok:
        txt = open(gi, "r", encoding="utf-8", errors="replace").read()
        check(".gitignore blocks secrets (secrets/* + *.env)", "secrets/" in txt and "*.env" in txt)

    # apply.py forked? informational, cli handles its absence gracefully.
    check("scripts/apply.py forked from companion config kit",
          os.path.isfile(os.path.join(cfg, "scripts", "apply.py")),
          "fork it before `promotion-assistant apply` (see scripts/apply.README.md)", level=WARN)

    # self-contained (E5): no absolute-path leakage in committed config files.
    leak = []
    for rel in ("product.json", "registry.json", "audiences.json", ".gitignore",
                os.path.join("secrets", "README.md")):
        p = os.path.join(cfg, rel)
        if os.path.isfile(p):
            t = open(p, "r", encoding="utf-8", errors="replace").read()
            if any(s in t for s in ("C:\\", "C:/", "/home/", "/Users/", "/root/")):
                leak.append(rel)
    check("self-contained (no hardcoded absolute paths)", not leak, "leaks in %s" % leak)

    # report
    n_fail = sum(1 for _, ok, lvl, _ in results if not ok and lvl == FAIL)
    n_warn = sum(1 for _, ok, lvl, _ in results if not ok and lvl == WARN)
    for nm, ok, lvl, detail in results:
        mark = PASS if ok else lvl
        line = "  [%s] %s" % (mark, nm)
        if detail and not ok:
            line += "  -> %s" % detail
        print(line)
    print("-" * 64)
    if n_fail:
        print("NOT READY: %d failed, %d warning(s). Fix FAILs (or re-run init_config.py)." % (n_fail, n_warn))
        return 1
    print("READY: config at %s conforms (%d warning(s))." % (cfg, n_warn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
