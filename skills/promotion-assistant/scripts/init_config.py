#!/usr/bin/env python3
"""Stamp a spec-conformant companion config repo for promotion-assistant (config-spec E3/E4).

Mode B (secrets gitignored). Deterministic + template-driven: re-running with the same --out
produces byte-identical skeleton files, so two people generate the same structure (E4). Never
writes or echoes secrets.

This mirrors CONFIG.md and reference/config-schema.md. It writes setup guidance for
selected-root runtime.env. No companion apply helper or MCP template is required.

Discovery convention the skill uses (also in CONFIG.md, E2): $PROMOTION_ASSISTANT_CONFIG, then
the proven sibling promotion-assistant-config through the fleet-guards companion resolver.

Usage:
  python init_config.py [--out <dir>] [--force]

--out   target config-repo dir (required unless PROMOTION_ASSISTANT_CONFIG selects one; the
        initializer has no default location).
Stdlib only. Cross-platform.
"""
import argparse
import json
import os
import sys

PRIMARY_ENV = "PROMOTION_ASSISTANT_CONFIG"
NO_COMPANION = ("no destination: pass --out <dir> to your PRIVATE companion clone "
                "(promotion-assistant-config beside this repository), or set PROMOTION_ASSISTANT_CONFIG")

# Mode B secrets gate for the COMPANION config repo (config-spec E6). Real values never enter git.
GITIGNORE = """\
# Secrets gate (config-spec E6 / Mode B) — real values never enter git.
secrets/*
!secrets/README.md
!secrets/.gitkeep
*.env
!*.env.template
!env.template
!/runtime.env
claude.json
.claude.json
*credentials*.json
*.key
*.pem
!*.key.template
!*.pem.template

# Runtime DATA is versioned in this PRIVATE companion.
# Only transient run locks are ignored.

"""

SECRETS_README = """\
# secrets/ — Mode B (gitignored)

Credential values never live in this repository. Provider resources are bound in `../runtime.env`
as `cv://<record>/<credential>` references into the external credential vault, resolved when the
source reads them. Anything here is **gitignored** (see ../.gitignore).

Only `*.env.template` files and this README are committed. On a new machine restore the credential
vault, then run `python scripts/verify_config.py` from the skill repo.
Files MUST be UTF-8 without BOM.
"""

PRODUCT_JSON = {
    "schema_version": 1,
    "name": "<product-name>",
    "send_mode": "dry_run",
    "aff_base": "",
    "banned_claims": [],
    "compliance": {"physical_address": "", "unsubscribe_url": ""},
}

REGISTRY_JSON = {"schema_version": 1, "channels": []}

AUDIENCES_JSON = {"segments": {}}

APPLY_README = """# Runtime resource validation

The source reads runtime.env from the selected PRIVATE companion on each dispatch.
Run the source doctor after restoring the companion and the credential vault. Source apply validates local resources only;
it does not execute this companion directory or modify host-wide settings.
"""

RUNBOOKS = {
    'new-machine.md': '# New machine\n\nRestore the PRIVATE companion and the external credential vault. Select the root with PROMOTION_ASSISTANT_CONFIG, then run the source scripts/verify_config.py. runtime.env binds credentials as cv:// references (keys in CONFIG.md). READY is local configuration/resource proof only.\n',
    'live-authorize.md': '# Live authorization\n\nStore the channel credentials in the external credential vault, bind them in runtime.env as cv:// references (never values) and verify the selected root with source doctor. Product send_mode=live and separate process-local PROMO_LIVE_AUTHORIZED_<CHANNEL> remain required.\n',
    'ban-recovery.md': '# Recovery\n\nPause dispatch and reconcile state, scheduling receipts and unresolved provider outcomes before retrying. Preserve all protected lock and receipt files until their dependencies close.\n',
}


def write(path, content, force):
    if os.path.exists(path) and not force:
        print("  SKIP (exists): %s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("  wrote: %s" % path)


def jdump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Stamp a spec-conformant promotion-assistant config repo (Mode B).")
    ap.add_argument("--out", default=None, help="target config-repo dir (default: $PROMOTION_ASSISTANT_CONFIG)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    selected = a.out or os.environ.get(PRIMARY_ENV)
    if not selected:
        ap.error(NO_COMPANION)
    out = os.path.abspath(os.path.expanduser(selected))
    print("Init promotion-assistant config repo (Mode B) at %s" % out)
    print("Discovery env var: %s  (then the proven sibling companion)" % PRIMARY_ENV)

    write(os.path.join(out, "product.json"), jdump(PRODUCT_JSON), a.force)
    write(os.path.join(out, "registry.json"), jdump(REGISTRY_JSON), a.force)
    write(os.path.join(out, "audiences.json"), jdump(AUDIENCES_JSON), a.force)
    write(os.path.join(out, ".gitignore"), GITIGNORE, a.force)
    write(os.path.join(out, "channels", ".gitkeep"), "", a.force)
    write(os.path.join(out, "copy", ".gitkeep"), "", a.force)
    write(os.path.join(out, "compliance", ".gitkeep"), "", a.force)
    write(os.path.join(out, "metrics", ".gitkeep"), "", a.force)
    write(os.path.join(out, "secrets", "README.md"), SECRETS_README, a.force)
    write(os.path.join(out, "secrets", ".gitkeep"), "", a.force)
    write(os.path.join(out, "scripts", "apply.README.md"), APPLY_README, a.force)
    for fn, body in RUNBOOKS.items():
        write(os.path.join(out, "runbooks", fn), body, a.force)

    print("\nNext:")
    print("  Initialize this directory as a separate PRIVATE Git companion outside the source repository.")
    print("  1) Fill product.json (name, aff_base, compliance.*) and add channels to registry.json.")
    print("  2) Per channel: channels/<slug>/policy.json (caps/gap/warmup/backoff) +")
    print("     secrets/<slug>.env.template (key names only). Credential values stay in your external")
    print("     credential vault; never write them into this repository.")
    print("  3) Write runtime.env with the channel keys (source CONFIG.md) as cv://<record>/<credential>")
    print("     references, then run source doctor.")
    print("  4) export %s=%s   (or use the default path)" % (PRIMARY_ENV, out))
    print("  5) python scripts/verify_config.py   # doctor: confirms the config is ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
