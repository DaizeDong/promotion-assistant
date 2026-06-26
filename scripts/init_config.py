#!/usr/bin/env python3
"""Spec-canonical config initializer entry point for promotion-assistant (config-spec E3/E4).

This is a thin, path-stable delegator: the real, template-driven, deterministic implementation
lives at skills/promotion-assistant/scripts/init_config.py (one source of truth — no drift). It is
mirrored here at the repo-root `scripts/` because the config-bearing acceptance gate (G8) and the
config-spec discovery convention resolve init/verify at <repo-root>/scripts/.

All arguments (e.g. --out <dir>, --force) and stdout/stderr are forwarded verbatim, so determinism
(E4) and the env-var hot-swap doctor (E5) behave identically whether invoked here or in the skill.
Stdlib only. Never writes or echoes secrets.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.abspath(
    os.path.join(HERE, "..", "skills", "promotion-assistant", "scripts", "init_config.py")
)

if __name__ == "__main__":
    if not os.path.isfile(TARGET):
        sys.stderr.write("init_config: implementation not found at %s\n" % TARGET)
        sys.exit(2)
    sys.exit(subprocess.run([sys.executable, TARGET] + sys.argv[1:]).returncode)
