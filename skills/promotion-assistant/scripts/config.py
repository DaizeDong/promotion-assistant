#!/usr/bin/env python3
"""L0 config/credential locator (product-agnostic).

Resolves the selected PRIVATE companion and loads product/channel configuration.
Provider resources are read from its secrets/runtime.env without changing global
process environment. Live authorization remains a separate process-local gate.

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
import re
from pathlib import Path
from .private_storage import prove

try:  # optional; copy/audiences may be YAML if PyYAML present, else JSON sidecars
    import yaml  # type: ignore
    _HAS_YAML = True
except Exception:
    _HAS_YAML = False


class ConfigError(Exception):
    pass


def find_config_dir(explicit: str | None = None) -> Path:
    selected = explicit
    # env vars: PROMO_CONFIG_DIR stays primary (the user-chosen canonical name); the
    # config-spec canonical aliases are honored too so spec and code agree (additive).
    for ev in ("PROMO_CONFIG_DIR", "PROMOTION_ASSISTANT_CONFIG", "PROMOTION_ASSISTANT_CONFIG_DIR"):
        if selected is None and os.environ.get(ev):
            selected = os.environ[ev]
    if selected is not None:
        if not isinstance(selected, (str, os.PathLike)) or not str(selected).strip() or not Path(selected).expanduser().is_dir():
            raise ConfigError('selected config directory is missing or invalid')
        return Path(selected).expanduser().resolve()
    cands = []
    cands.append(Path.home() / ".promotion-assistant-config")
    cands.append(Path.home() / ".config" / "promotion-assistant-config")
    for c in cands:
        if c and c.is_dir():
            return c.resolve()
    raise ConfigError(
        "no product config found. Set PROMO_CONFIG_DIR to your config repo "
        "(see runbooks/new-machine.md), e.g. export PROMO_CONFIG_DIR=~/CodesClaude/promotion-assistant-config"
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
        try:
            self.root = prove(root)
            self.product = _load_doc(self.data_path('product.json'))
            self.registry = _load_doc(self.data_path('registry.json'))
            if self.registry is None:
                self.registry = {"channels": []}
            if not isinstance(self.product, dict) or not isinstance(self.registry, dict):
                raise ValueError('product and registry must be objects')
            channels = self.registry.get('channels', [])
            if (not isinstance(channels, list) or any(not isinstance(row, dict)
                    or not isinstance(row.get('slug'), str) or not row['slug'] for row in channels)
                    or len({row['slug'] for row in channels}) != len(channels)):
                raise ValueError('registry channels must have unique nonempty slugs')
            if not isinstance(self.product.get('compliance', {}), dict):
                raise ValueError('product compliance must be an object')
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            raise ConfigError(str(exc)) from exc
        if not self.product:
            raise ConfigError("product.json missing/empty in %s" % root)

    def settings_errors(self):
        errors = []
        for label, doc in (('product', self.product), ('registry', self.registry)):
            if type(doc.get('schema_version')) is not int or doc['schema_version'] != 1:
                errors.append(label + '.schema_version must equal 1')
        name = self.product.get('name')
        if not isinstance(name, str) or not name.strip() or name.strip().startswith('<'):
            errors.append('product.name must be a configured nonempty name')
        if self.send_mode not in {'dry_run', 'live'}:
            errors.append('product.send_mode must be dry_run or live')
        for channel in self.channels():
            slug = channel.get('slug', '')
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
                errors.append('registry.channels.slug must be a safe lowercase slug')
            if not isinstance(channel.get('platform'), str) or not channel['platform'].strip():
                errors.append('registry.channels.platform is required')
        return errors

    def runtime_env(self):
        """Read one selected-root resource binding; never inherit ambient credentials."""
        from .private_storage import read_text
        allowed = {'PROMO_SEND_GMAIL', 'PROMO_DISCORD_BOT_TOKEN',
                   'PROMO_DISCORD_ANNOUNCE_CHANNEL_ID', 'PROMO_DISCORD_ALLOW_EMBED',
                   'PROMO_MASTODON_INSTANCE', 'PROMO_MASTODON_TOKEN',
                   'PROMO_BLUESKY_HANDLE', 'PROMO_BLUESKY_APP_PASSWORD'}
        try:
            body = read_text(self.data_path('secrets', 'runtime.env'), missing='')
            result = {}
            for number, line in enumerate(body.splitlines(), 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                key, separator, value = line.partition('=')
                key, value = key.strip(), value.strip()
                if not separator or key not in allowed or key in result:
                    raise ValueError('invalid or duplicate resource key at line ' + str(number))
                if value.startswith(('"', "'")):
                    if len(value) < 2 or value[-1] != value[0]:
                        raise ValueError('unclosed resource quote at line ' + str(number))
                    value = value[1:-1]
                if '\x00' in value or value.startswith('<'):
                    raise ValueError('unconfigured resource at line ' + str(number))
                result[key] = value
            if result.get('PROMO_SEND_GMAIL'):
                helper = Path(result['PROMO_SEND_GMAIL']).expanduser()
                result['PROMO_SEND_GMAIL'] = str(helper if helper.is_absolute() else self.root / helper)
            return result
        except (OSError, ValueError, RuntimeError) as exc:
            raise ConfigError('selected secrets/runtime.env is invalid: ' + str(exc)) from exc

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
        doc = _load_doc(self.data_path('channels', slug, 'policy.json')) or {}
        if not isinstance(doc, dict):
            raise ConfigError('channel policy must be an object')
        return doc

    def copy(self, campaign: str) -> list:
        self.data_path('copy', "%s.json" % campaign)  # Prove the optional YAML fallback too.
        doc = _load_doc(self.data_path('copy', "%s.yaml" % campaign))
        if doc is None:
            doc = _load_doc(self.data_path('copy', "%s.json" % campaign))
        if doc is not None and (not isinstance(doc, list) or any(not isinstance(arm, dict) for arm in doc)):
            raise ConfigError('copy library must be a list of arms')
        return doc or []

    def audiences(self) -> dict:
        self.data_path('audiences.json')
        doc = _load_doc(self.data_path('audiences.yaml'))
        if doc is None:
            doc = _load_doc(self.data_path('audiences.json'))
        return doc or {}

    def data_path(self, *parts) -> Path:
        try:
            path = prove(self.root.joinpath(*parts))
            if not path.is_relative_to(self.root):
                raise ValueError('runtime path escapes selected config root')
            return path
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            raise ConfigError(str(exc)) from exc

    # Runtime DATA is versioned in the PRIVATE companion.
    def metrics_dir(self) -> Path:
        d = self.data_path('metrics')
        for name in ('events.jsonl', 'dry-run.jsonl', 'bandit-state.json', 'throttle-state.json', 'suppression.csv', 'runs'):
            self.data_path('metrics', name)
        from .private_storage import authorize
        authorize(d / "events.jsonl")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def compliance_dir(self) -> Path:
        d = self.data_path('compliance')
        from .private_storage import authorize
        authorize(d / "consent-ledger.jsonl")
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
