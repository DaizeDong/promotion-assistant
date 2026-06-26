#!/usr/bin/env python3
"""L0 config/credential locator (product-agnostic).

Resolves the active per-product config repo (Mode B: secrets gitignored) and loads
product.json / registry.json / channel policy / copy library / audiences. Never reads
secrets/*.env values into the process beyond what apply.py needs — credentials are
bridged into the live MCP/active config by the config repo's own apply.py, not here.

Discovery order (first hit wins):
  1. $PROMO_CONFIG_DIR                        (explicit, recommended — primary)
  2. $PROMOTION_ASSISTANT_CONFIG             (config-spec canonical alias)
  3. $PROMOTION_ASSISTANT_CONFIG_DIR         (config-spec canonical alias)
  4. ~/.promotion-assistant-config/          (dotfile-in-home fallback)
  5. ~/.config/promotion-assistant-config/   (XDG-style fallback)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:  # optional; copy/audiences may be YAML if PyYAML present, else JSON sidecars
    import yaml  # type: ignore
    _HAS_YAML = True
except Exception:
    _HAS_YAML = False


class ConfigError(Exception):
    pass


def find_config_dir(explicit: str | None = None) -> Path:
    cands = []
    if explicit:
        cands.append(Path(explicit))
    # env vars: PROMO_CONFIG_DIR stays primary (the user-chosen canonical name); the
    # config-spec canonical aliases are honored too so spec and code agree (additive).
    for ev in ("PROMO_CONFIG_DIR", "PROMOTION_ASSISTANT_CONFIG", "PROMOTION_ASSISTANT_CONFIG_DIR"):
        if os.environ.get(ev):
            cands.append(Path(os.environ[ev]))
    cands.append(Path.home() / ".promotion-assistant-config")
    cands.append(Path.home() / ".config" / "promotion-assistant-config")
    for c in cands:
        if c and c.is_dir():
            return c.resolve()
    raise ConfigError(
        "no product config found. Set PROMO_CONFIG_DIR to your config repo "
        "(see runbooks/new-machine.md), e.g. export PROMO_CONFIG_DIR=~/CodesSelf/promotion-assistant-config"
    )


def _load_doc(path: Path):
    """Load a JSON or YAML doc; prefers a .json sibling when YAML is unavailable."""
    if path.suffix in (".yaml", ".yml"):
        if _HAS_YAML and path.is_file():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        sib = path.with_suffix(".json")
        if sib.is_file():
            return json.loads(sib.read_text(encoding="utf-8"))
        if path.is_file():
            raise ConfigError("YAML config %s present but PyYAML not installed and no .json sibling" % path)
        return None
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


class Config:
    """In-memory view of one product's config repo."""

    def __init__(self, root: Path):
        self.root = root
        self.product = _load_doc(root / "product.json") or {}
        self.registry = _load_doc(root / "registry.json") or {"channels": []}
        if not self.product:
            raise ConfigError("product.json missing/empty in %s" % root)

    # --- product-level gates ---
    @property
    def send_mode(self) -> str:
        return str(self.product.get("send_mode", "dry_run"))

    @property
    def aff_base(self) -> str:
        return str(self.product.get("aff_base", ""))

    @property
    def banned_claims(self) -> list:
        return list(self.product.get("banned_claims", []))

    # --- channels ---
    def channels(self) -> list:
        chans = self.registry.get("channels", [])
        return chans if isinstance(chans, list) else []

    def channel(self, slug: str) -> dict | None:
        for c in self.channels():
            if c.get("slug") == slug:
                return c
        return None

    def live_authorize_token(self, slug: str) -> str | None:
        """Optional per-channel EXPECTED value for the PROMO_LIVE_AUTHORIZED_<CH> env token.

        When a channel declares `live_authorize_token` in registry.json, dispatch's second
        factor is strengthened from existence-only to a constant-time equality check (the env
        value must EQUAL this configured secret). Returns None when unset -> existence-only
        (any non-empty env value authorizes), which is the documented default.
        """
        ch = self.channel(slug) or {}
        tok = ch.get("live_authorize_token")
        if tok in (None, ""):
            return None
        return str(tok)

    def policy(self, slug: str) -> dict:
        doc = _load_doc(self.root / "channels" / slug / "policy.json") or {}
        return doc

    def copy(self, campaign: str) -> list:
        doc = _load_doc(self.root / "copy" / ("%s.yaml" % campaign))
        if doc is None:
            doc = _load_doc(self.root / "copy" / ("%s.json" % campaign))
        return doc or []

    def audiences(self) -> dict:
        doc = _load_doc(self.root / "audiences.yaml")
        if doc is None:
            doc = _load_doc(self.root / "audiences.json")
        return doc or {}

    # --- metrics paths (gitignored dir in the config repo) ---
    def metrics_dir(self) -> Path:
        d = self.root / "metrics"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def compliance_dir(self) -> Path:
        d = self.root / "compliance"
        d.mkdir(parents=True, exist_ok=True)
        return d


def load(explicit: str | None = None) -> Config:
    return Config(find_config_dir(explicit))


if __name__ == "__main__":
    import sys
    try:
        cfg = load(sys.argv[1] if len(sys.argv) > 1 else None)
    except ConfigError as e:
        print("CONFIG ERROR:", e)
        raise SystemExit(2)
    print("config root :", cfg.root)
    print("product     :", cfg.product.get("name"))
    print("send_mode   :", cfg.send_mode)
    print("channels    :", [c.get("slug") for c in cfg.channels()])
