"""Round-2 audit-fix regression guards (each fails on the PRE-fix code, passes after).

Covers the three round-2 audit findings:
  F1 (low) dispatch doc/impl drift  -> second factor can now ENFORCE a configured expected token
            (constant-time equality) instead of accepting any non-empty value; existence-only
            stays the documented default when no expected token is configured.
  F2 (low) live email subprocess arg-binding -> recipient is validated as a single email and any
            recipient/subject/body that starts with '-' is refused BEFORE spawning powershell.
  F3 (info) over-broad `*.jsonl` ignore -> narrowed so committed test fixtures / reference shards
            are no longer silently swallowed, while stray runtime jsonl stays ignored.

These are deterministic, hermetic, and never perform real egress (the email subprocess is spied).
"""
import json
import subprocess as _sp
import tempfile
from pathlib import Path

import pytest

from scripts import config as CFG
from scripts import dispatch as D
from scripts import providers as P

_ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- F1
def _mk_cfg(tmp, *, channel_extra=None):
    root = Path(tmp)
    (root / "product.json").write_text(json.dumps({
        "name": "T", "send_mode": "live", "banned_claims": [],
    }), encoding="utf-8")
    ch = {"slug": "email-pool", "platform": "email", "warmup_state": "normal"}
    if channel_extra:
        ch.update(channel_extra)
    (root / "registry.json").write_text(json.dumps({"channels": [ch]}), encoding="utf-8")
    return CFG.Config(root)


def test_f1_authorized_enforces_configured_expected_token():
    env_good = {"PROMO_LIVE_AUTHORIZED_EMAIL": "s3cret"}
    env_wrong = {"PROMO_LIVE_AUTHORIZED_EMAIL": "WRONG-but-nonempty"}
    # match required when an expected secret is configured
    assert D._authorized("email", "live", env=env_good, expected="s3cret")[0] is True
    # the core fix: a NON-EMPTY but mismatching token must NOT authorize (pre-fix it did)
    assert D._authorized("email", "live", env=env_wrong, expected="s3cret")[0] is False
    # existence-only fallback preserved when no expected secret is configured
    assert D._authorized("email", "live", env=env_wrong, expected=None)[0] is True
    # factor-1 + presence still fail-closed
    assert D._authorized("email", "dry_run", env=env_good, expected=None)[0] is False
    assert D._authorized("email", "live", env={}, expected=None)[0] is False


def test_f1_config_exposes_per_channel_expected_token():
    with tempfile.TemporaryDirectory() as t:
        cfg = _mk_cfg(t, channel_extra={"live_authorize_token": "abc123"})
        assert cfg.live_authorize_token("email-pool") == "abc123"
    with tempfile.TemporaryDirectory() as t:
        cfg = _mk_cfg(t)  # unset -> existence-only default
        assert cfg.live_authorize_token("email-pool") is None
        assert cfg.live_authorize_token("missing-channel") is None


# ----------------------------------------------------------------------------- F2
class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, *a, **kw):
        self.calls.append(cmd)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()


def _wire_email(monkeypatch, tmpdir):
    ps1 = Path(tmpdir) / "send-gmail.ps1"
    ps1.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(P, "SEND_GMAIL_PS1", ps1)
    spy = _Spy()
    monkeypatch.setattr(P.subprocess, "run", spy)
    return spy


def test_f2_dash_leading_recipient_refused_without_spawning(monkeypatch):
    with tempfile.TemporaryDirectory() as t:
        spy = _wire_email(monkeypatch, t)
        prov = P.EmailProvider()
        r = prov.publish({"recipient": "--Command", "subject": "s", "body": "b"}, live=True)
        assert r["status"] == "error"
        assert spy.calls == [], "must refuse BEFORE spawning powershell"


def test_f2_non_email_recipient_refused(monkeypatch):
    with tempfile.TemporaryDirectory() as t:
        spy = _wire_email(monkeypatch, t)
        prov = P.EmailProvider()
        r = prov.publish({"recipient": "not-an-email", "subject": "s", "body": "b"}, live=True)
        assert r["status"] == "error"
        assert spy.calls == []


def test_f2_dash_leading_subject_or_body_refused(monkeypatch):
    with tempfile.TemporaryDirectory() as t:
        spy = _wire_email(monkeypatch, t)
        prov = P.EmailProvider()
        assert prov.publish({"recipient": "a@b.com", "subject": "-Foo", "body": "b"},
                            live=True)["status"] == "error"
        assert prov.publish({"recipient": "a@b.com", "subject": "s", "body": "-rm"},
                            live=True)["status"] == "error"
        assert spy.calls == []


def test_f2_valid_email_still_reaches_live_transport(monkeypatch):
    with tempfile.TemporaryDirectory() as t:
        spy = _wire_email(monkeypatch, t)
        prov = P.EmailProvider()
        r = prov.publish({"recipient": "user@example.com", "subject": "Hi", "body": "ok"}, live=True)
        assert r["status"] == "sent"
        assert len(spy.calls) == 1, "valid recipient must still invoke the live path"
        cmd = spy.calls[0]
        assert "-To" in cmd and "user@example.com" in cmd


# ----------------------------------------------------------------------------- F3
def _check_ignored(path: str):
    """Return True if `path` is git-ignored at the repo root, None if git is unavailable."""
    try:
        r = _sp.run(["git", "-C", str(_ROOT), "check-ignore", "-q", path],
                    capture_output=True, text=True)
    except Exception:
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None  # 128 = not a git work tree


def test_f3_legit_fixture_jsonl_not_ignored():
    res = _check_ignored("tests/fixtures/sample_events.jsonl")
    if res is None:
        pytest.skip("git unavailable / not a work tree")
    assert res is False, "committed test-fixture .jsonl must NOT be ignored (over-broad ignore fix)"


def test_f3_runtime_jsonl_still_ignored():
    for stray in ("metrics/events.jsonl", "stray_runtime.jsonl", "dry-run.jsonl"):
        res = _check_ignored(stray)
        if res is None:
            pytest.skip("git unavailable / not a work tree")
        assert res is True, "runtime jsonl %r must stay ignored (defensive default preserved)" % stray


def test_f3_fixture_file_exists_on_disk():
    # the fixture is really committed (proves the ignore narrowing is load-bearing, not just text)
    assert (_ROOT / "tests" / "fixtures" / "sample_events.jsonl").is_file()
