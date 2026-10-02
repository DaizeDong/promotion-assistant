"""Generated synthetic regressions for Promotion5; no live effects are used."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from scripts import cli, config, events, orchestrate, participation, runs
from test_owned_identity import owned
from test_review_runs import case

ROOT = Path(__file__).resolve().parents[1]


def test_cli_conversion_window_uses_production_clock_and_preserves_event_policy(
        case, monkeypatch, capsys):
    now = [2000000000.0]
    monkeypatch.setattr(runs.time, "time", lambda: now[0])
    monkeypatch.setattr(cli, "_load", lambda args: case["cfg"])
    args = ["run", "--campaign", case["campaign"], "--once",
            "--conversion-window-days", "1", "--run-id", case["run_id"]]
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "simulated" and first["reward_status"] == "censored"
    assert first["reward"] is None
    state_path = case["root"] / "metrics/bandit-state.json"
    state = json.loads(state_path.read_text())
    assert len(state["observation_credits"]) == len(first["items"]) > 0
    assert all(credit["status"] == "censored" for credit in state["observation_credits"].values())
    assert all(arm["alpha"] == arm["beta"] == 1.0 for arm in state["arms"].values())
    before = state_path.read_bytes()
    now[0] += 2 * 86400
    assert cli.main(args + ["--resume"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["reward_status"] == "no-new-observations"
    assert state_path.read_bytes() == before


def test_injected_learning_clock_still_overrides_production_time(case, monkeypatch):
    monkeypatch.setattr(events, "now_ts", lambda: 1000.0)
    monkeypatch.setattr(runs.time, "time", lambda: 1000000.0)
    result = orchestrate.run_once(case["cfg"], case["campaign"], env={},
                                 clock=lambda: 1050.0, conversion_window_s=100)
    assert result["reward"] is None and result["reward_status"] == "censored"


def test_identity_preflight_429_retains_not_applied_and_persists_cooldown(
        owned, case, monkeypatch):
    now = [2000000000.0]
    requests = []
    def limited(request, **kwargs):
        requests.append(request.full_url)
        assert request.full_url.endswith(("createSession", "verify_credentials"))
        raise urllib.error.HTTPError(request.full_url, 429, "Synthetic rate limit", {},
                                     io.BytesIO(b"Synthetic response"))
    monkeypatch.setattr(urllib.request, "urlopen", limited)
    first = owned["run"](clock=lambda: now[0])
    assert first["status"] == "failed" and len(requests) == 1
    item = owned["saved"]()["items"][0]
    assert item["safe_to_retry"] is True
    assert item["receipt"]["status"] == "not_applied" and item["receipt"]["rate_limited"] is True
    assert item["receipt"]["code"] == 429 and "No publish request" in item["receipt"]["evidence"]
    throttle_path = case["root"] / "metrics/throttle-state.json"
    persisted = json.loads(throttle_path.read_text())
    assert persisted["cooldowns"] and min(persisted["cooldowns"].values()) > now[0]
    before = throttle_path.read_bytes()
    assert owned["run"](resume=True, clock=lambda: now[0])["status"] == "deferred"
    assert len(requests) == 1 and throttle_path.read_bytes() == before
    platform = owned["platform"]
    fresh = orchestrate.run_once(
        config.Config(case["root"]), case["campaign"], run_id="synthetic-next-run",
        env={"PROMO_LIVE_AUTHORIZED_" + platform.upper(): "synthetic-token"}, clock=lambda: now[0])
    assert fresh["status"] == "deferred" and len(requests) == 1
    now[0] = max(persisted["cooldowns"].values()) + 1
    assert owned["run"](resume=True, clock=lambda: now[0])["status"] == "failed"
    assert len(requests) == 2 and owned["posts"] == []


@pytest.mark.parametrize("base", ["https://example.com/item", "https://news.ycombinator.com/item"])
def test_functional_query_ids_survive_manual_recording_and_tracking_deduplication(case, base):
    args = {"channel": "synthetic-manual", "arm_id": "synthetic-arm", "campaign": "synthetic-campaign"}
    first = orchestrate.record_post(case["cfg"], url=base + "?id=10001", **args)
    second = orchestrate.record_post(case["cfg"], url=base + "?id=10002", **args)
    repeated = orchestrate.record_post(
        case["cfg"], url=base + "?utm_source=synthetic&id=10001&utm_medium=example#fragment", **args)
    assert first["status"] == second["status"] == repeated["status"] == "recorded"
    assert first["event_id"] != second["event_id"]
    assert repeated["event_id"] == first["event_id"]
    assert first["url"] == base + "?id=10001" and second["url"] == base + "?id=10002"
    rows = events.read(case["root"] / "metrics/events.jsonl")
    assert len(rows) == 2 and len({row["decision_id"] for row in rows}) == 2
    assert {row["post_url"] for row in rows} == {first["url"], second["url"]}


@pytest.mark.parametrize("query", ["id=10001&id=10002", "id=&mode=full", "key=a%2Fb+z&sig=abc%3D"])
def test_unknown_query_fields_are_preserved_verbatim(query):
    base = "https://example.com/item?"
    assert participation.canonical_permalink(base + query + "&utm_source=synthetic") == base + query


def generator():
    spec = importlib.util.spec_from_file_location("synthetic_promotion_fixture_generator",
                                                  ROOT / "tools/make_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_export_reproduces_every_declared_fixture_and_check_detects_drift(
        tmp_path, monkeypatch):
    module = generator()
    out = tmp_path / "export"
    monkeypatch.setattr(sys, "argv", ["make_fixtures.py", "--out", str(out)])
    module.main()
    declared = json.loads((ROOT / ".dataclass.json").read_text())["fixture"]
    expected = {}
    for relative in declared:
        content = (ROOT / relative).read_bytes()
        name = Path(relative).name
        assert name not in expected or expected[name] == content
        expected[name] = content
        assert (out / name).read_bytes() == content
    assert {path.name for path in out.iterdir()} == set(expected)
    assert len([name for name in expected if name.endswith(".py")]) >= 9
    monkeypatch.setattr(sys, "argv", ["make_fixtures.py", "--out", str(out), "--check"])
    module.main()
    assert {path.name: path.read_bytes() for path in out.iterdir()} == expected
    altered = out / "test_promotion_v5.py"
    altered.write_text("# Synthetic damaged export\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="generated synthetic output mismatch"):
        module.main()


def test_fixture_export_rejects_conflicting_basename_before_writing(tmp_path, monkeypatch):
    module = generator()
    monkeypatch.setitem(module.TEXT_OUTPUTS, "synthetic/promotion.json", "Synthetic collision")
    out = tmp_path / "export"
    monkeypatch.setattr(sys, "argv", ["make_fixtures.py", "--out", str(out)])
    with pytest.raises(ValueError, match="basename collision"):
        module.main()
    assert not out.exists()


@pytest.mark.parametrize("url", [None, "", "http://example.com/source", "https://user1@example.com/source",
                                 "https://www.reddit.com/r/synthetic/", "not-a-url"])
def test_draft_refuses_invalid_source_before_model_or_event(case, monkeypatch, capsys, url):
    monkeypatch.setattr(cli, "_load", lambda args: case["cfg"])
    calls = []
    def model(*args, **kwargs):
        calls.append(args)
        pytest.fail("invalid source reached model")
    monkeypatch.setitem(sys.modules, "llmcall", SimpleNamespace(call=model))
    args = ["participate", "draft", "--title", "Synthetic question", "--body", "Synthetic context"]
    if url is not None:
        args += ["--url", url]
    assert cli.main(args) == 2
    assert calls == [] and "invalid draft source --url" in capsys.readouterr().err
    assert not (case["root"] / "metrics/events.jsonl").exists()


@pytest.mark.parametrize("use_draft", [False, True])
def test_documented_participation_source_and_record_contract(case, monkeypatch, capsys, use_draft):
    monkeypatch.setattr(cli, "_load", lambda args: case["cfg"])
    calls = []
    def model(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return SimpleNamespace(text="Synthetic reply for human review.")
    monkeypatch.setitem(sys.modules, "llmcall", SimpleNamespace(call=model))
    thread = "https://www.reddit.com/r/synthetic/comments/abc/topic"
    args = ["participate", "record", "--url", thread + "/xyz",
            "--thread", thread, "--type", "give"]
    if use_draft:
        assert cli.main(["participate", "draft", "--url", thread,
                         "--title", "Synthetic question", "--body", "Synthetic context"]) == 0
        draft = events.read(case["root"] / "metrics/events.jsonl")[0]
        assert draft["thread"] == participation.thread_identity(thread)
        assert calls[0][1] == {"mode": "agent"}
        args += ["--draft-id", draft["event_id"]]
        capsys.readouterr()
    assert cli.main(args) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "recorded" and record["participation_type"] == "give"
    assert bool(record["linked_draft"]) is use_draft
    skill = (ROOT / "skills/promotion-assistant/SKILL.md").read_text(encoding="utf-8")
    draft_line = next(line for line in skill.splitlines() if line.startswith("python scripts/cli.py participate draft "))
    record_line = next(line for line in skill.splitlines() if line.startswith("python scripts/cli.py participate record "))
    assert "--url <source-thread>" in draft_line
    assert all(flag in record_line for flag in ("--url", "--thread", "--type"))
    assert "[--draft-id <draft-id>]" in record_line
