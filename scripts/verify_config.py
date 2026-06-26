#!/usr/bin/env python3
"""Spec-canonical config doctor entry point for promotion-assistant (config-spec E3/E5).

Thin, path-stable delegator to the real doctor at
skills/promotion-assistant/scripts/verify_config.py (one source of truth — no drift). Mirrored at
the repo-root `scripts/` because the config-bearing acceptance gate (G8) and the discovery
convention resolve init/verify at <repo-root>/scripts/.

Arguments (e.g. --config-dir <dir>), environment (PROMO_CONFIG_DIR / PROMOTION_ASSISTANT_CONFIG[_DIR]
discovery), exit code and stdout/stderr are all forwarded verbatim, so the env-var hot-swap proof
(E5) resolves the pointed-at config identically here or in the skill. Stdlib only. Never echoes
secret values.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.abspath(
    os.path.join(HERE, "..", "skills", "promotion-assistant", "scripts", "verify_config.py")
)

if __name__ == "__main__":
    if not os.path.isfile(TARGET):
        sys.stderr.write("verify_config: implementation not found at %s\n" % TARGET)
        sys.exit(2)
    sys.exit(subprocess.run([sys.executable, TARGET] + sys.argv[1:]).returncode)
