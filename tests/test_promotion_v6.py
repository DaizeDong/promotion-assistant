"""Generated synthetic controls for host binding, hot quotas and listing decisions."""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from scripts import cli, growth, participation, private_storage, throttle

@pytest.mark.parametrize('selected_host', [None, 'github.com', 'github.example.invalid'])
@pytest.mark.parametrize('allowed', [False, True])
def test_publication_report_delegates_without_clearing_process_policy(
        tmp_path, monkeypatch, selected_host, allowed):
    if selected_host is None:
        monkeypatch.delenv('GH_HOST', raising=False)
    else:
        monkeypatch.setenv('GH_HOST', selected_host)
    monkeypatch.setenv('GIT_CONFIG_COUNT', '5')
    api = private_storage._guard_api()
    calls = []
    def proof(repo):
        calls.append(repo)
        assert private_storage.os.environ.get('GH_HOST') == selected_host
        assert private_storage.os.environ['GIT_CONFIG_COUNT'] == '5'
        if not allowed:
            raise api.GitError('synthetic unsafe effective policy')
        return SimpleNamespace(root=str(repo), repositories=('example/synthetic-promotion-config',),
                               signature='synthetic-publication')
    monkeypatch.setattr(api, 'prove_private_companion', proof)
    if allowed:
        assert private_storage.publication_destinations(tmp_path) == ('example/synthetic-promotion-config',)
    else:
        with pytest.raises(ValueError, match='PRIVATE companion verification failed'):
            private_storage.publication_destinations(tmp_path)
    assert calls == [tmp_path]


def instance(path, now):
    return throttle.Throttle(path, clock=lambda: now[0])


def reserve(controller, identity, cap):
    return controller.reserve(
        "synthetic-account", "discord", "post",
        {"day_cap": cap, "min_gap_sec": 0},
        reservation_id=identity, payload={"body": "Acme synthetic announcement"})


def saved_bucket(path):
    document = json.loads(path.read_text())
    assert len(document["buckets"]) == 1
    return next(iter(document["buckets"].values()))


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("rollover", [False, True])
def test_zero_policy_blocks_existing_bucket_and_old_reservations(
        tmp_path, restart, retry, rollover):
    now = [1000.0]
    path = tmp_path / "state.json"
    controller = instance(path, now)
    assert reserve(controller, "synthetic-initial", 50)[0]
    now[0] += 86400 if rollover else 1
    if restart:
        controller = instance(path, now)
    result = reserve(controller, "synthetic-initial" if retry else "synthetic-new", 0)
    assert result[0] is False and "daily cap" in result[1]
    bucket = saved_bucket(path)
    assert bucket["base_cap"] == 0 and bucket["tokens"] == 0
    assert len(json.loads(path.read_text())["reservations"]) == 1


@pytest.mark.parametrize("spent", [0, 1, 3, 7])
@pytest.mark.parametrize("restart", [False, True])
def test_reduced_limit_preserves_consumed_quota(tmp_path, spent, restart):
    now = [1000.0]
    path = tmp_path / "state.json"
    controller = instance(path, now)
    controller._bucket("synthetic-account", "discord", "post", {"day_cap": 10})
    controller.save()
    for index in range(spent):
        assert reserve(controller, "synthetic-before-%d" % index, 10)[0]
    previous_period = saved_bucket(path)["last_refill"]
    now[0] += 1
    if restart:
        controller = instance(path, now)
    outcomes = [reserve(controller, "synthetic-after-%d" % index, 3)[0] for index in range(4)]
    assert sum(outcomes) == max(0, 3-spent)
    bucket = saved_bucket(path)
    assert bucket["period_used"] == max(spent, 3)
    assert bucket["last_refill"] == previous_period
    assert bucket["base_cap"] == 3 and bucket["tokens"] == 0


def test_limit_changes_never_reset_usage_or_mint_midperiod_tokens(tmp_path):
    now = [1000.0]
    path = tmp_path / "state.json"
    controller = instance(path, now)
    for index in range(7):
        assert reserve(controller, "synthetic-before-%d" % index, 10)[0]
    for cap in (5, 0, 9):
        controller = instance(path, now)
        assert reserve(controller, "synthetic-after-%d" % cap, cap)[0] is False
        assert saved_bucket(path)["period_used"] == 7
        assert saved_bucket(path)["last_refill"] == 1000
    now[0] += 86400
    controller = instance(path, now)
    assert sum(reserve(controller, "synthetic-next-%d" % index, 9)[0]
               for index in range(10)) == 9
    assert saved_bucket(path)["period_used"] == 9


def test_policy_reduction_preserves_aimd_capacity_and_consumption(tmp_path):
    now = [1000.0]
    path = tmp_path / "state.json"
    controller = instance(path, now)
    for index in range(2):
        assert reserve(controller, "synthetic-before-%d" % index, 20)[0]
    controller.record_throttle_signal(
        "synthetic-account", "discord", "post",
        {"day_cap": 20, "backoff": {"factor": 0.25, "cooldown_h": 1}})
    now[0] += 3601
    controller = instance(path, now)
    assert sum(reserve(controller, "synthetic-after-%d" % index, 8)[0]
               for index in range(4)) == 3
    bucket = saved_bucket(path)
    assert bucket["cap"] == 5 and bucket["base_cap"] == 8
    assert bucket["period_used"] == 5 and bucket["tokens"] == 0
    now[0] = 87400
    controller = instance(path, now)
    assert sum(reserve(controller, "synthetic-refill-%d" % index, 8)[0]
               for index in range(6)) == 5


def test_concurrent_reservations_share_the_reduced_current_limit(tmp_path):
    now = [1000.0]
    path = tmp_path / "state.json"
    controller = instance(path, now)
    for index in range(2):
        assert reserve(controller, "synthetic-initial-%d" % index, 50)[0]
    controllers = [instance(path, now), instance(path, now)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, item, "synthetic-race-%d" % index, 3)
                   for index, item in enumerate(controllers)]
        outcomes = [future.result()[0] for future in futures]
    assert sum(outcomes) == 1
    bucket = saved_bucket(path)
    assert bucket["period_used"] == 3 and bucket["tokens"] == 0
    assert len(json.loads(path.read_text())["reservations"]) == 3


@pytest.mark.parametrize("cap", [-1, float("nan"), float("inf")])
def test_invalid_policy_is_checked_for_existing_buckets(tmp_path, cap):
    now = [1000.0]
    path = tmp_path / "state.json"
    controller = instance(path, now)
    assert reserve(controller, "synthetic-initial", 10)[0]
    before = path.read_bytes()
    with pytest.raises(ValueError, match="day_cap"):
        reserve(instance(path, now), "synthetic-new", cap)
    assert path.read_bytes() == before


@pytest.mark.parametrize("learned,base,remaining", [(5, 20, 4), (15, 10, 7)])
def test_legacy_aimd_bucket_waits_for_normal_refill(tmp_path, learned, base, remaining):
    now = [1000.0]
    path = tmp_path / "state.json"
    assert reserve(instance(path, now), "synthetic-initial", base)[0]
    document = json.loads(path.read_text())
    bucket = next(iter(document["buckets"].values()))
    bucket.pop("period_used")
    bucket.update(cap=learned, base_cap=base, tokens=learned)
    path.write_text(json.dumps(document))
    for identity in ("synthetic-current", "synthetic-initial"):
        assert reserve(instance(path, now), identity, 8)[0] is False
    bucket = saved_bucket(path)
    assert bucket["usage_known"] is False and bucket["tokens"] == 0
    assert bucket["last_refill"] == 1000 and bucket["cap"] == learned
    now[0] += 86400
    assert reserve(instance(path, now), "synthetic-next", 8)[0]
    bucket = saved_bucket(path)
    assert bucket["usage_known"] is True
    assert bucket["period_used"] == 1 and bucket["tokens"] == remaining


@pytest.mark.parametrize("usage", [-1, float("nan"), float("inf"), "synthetic-invalid"])
def test_malformed_durable_usage_is_rejected_without_rewrite(tmp_path, usage):
    now = [1000.0]
    path = tmp_path / "state.json"
    assert reserve(instance(path, now), "synthetic-initial", 10)[0]
    document = json.loads(path.read_text())
    next(iter(document["buckets"].values()))["period_used"] = usage
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="period usage"):
        instance(path, now)
    assert path.read_bytes() == before


def config(banned):
    return SimpleNamespace(
        product={"product": "AcmeCorp", "value_props": ["Documented usage limits"]},
        banned_claims=banned)


@pytest.mark.parametrize("claim", ["free model", "acmecorp", "compatible"])
def test_rejected_listing_never_becomes_submission_copy(monkeypatch, capsys, claim):
    cfg = config([claim])
    result = growth.listing(cfg)
    assert result["status"] == "blocked" and result["description"] is None
    assert result["reasons"] and any(claim in reason.lower() for reason in result["reasons"])
    monkeypatch.setattr(cli, "_load", lambda args: cfg)
    assert cli.cmd_growth(SimpleNamespace(what="listing")) == 1
    rendered = capsys.readouterr().out
    assert "Listing blocked:" in rendered
    assert "Description:" not in rendered and "Submit at:" not in rendered


def test_safe_listing_remains_available_to_library_and_cli(monkeypatch, capsys):
    cfg = config([])
    result = growth.listing(cfg)
    assert result["status"] == "ready" and result["reasons"] == []
    assert "AcmeCorp" in result["description"] and result["directories"]
    monkeypatch.setattr(cli, "_load", lambda args: cfg)
    assert cli.cmd_growth(SimpleNamespace(what="listing")) == 0
    rendered = capsys.readouterr().out
    assert result["description"] in rendered and "Submit at:" in rendered


@pytest.mark.parametrize("gives,asks,holds,next_ok", [
    (0, 0, True, False),
    (8, 0, True, False),
    (9, 0, True, True),
    (9, 1, True, False),
    (17, 1, True, False),
    (18, 1, True, True),
    (18, 2, True, False),
    (27, 2, True, True),
    (8, 1, False, False),
])
def test_next_ask_flag_accounts_for_the_prospective_ask(gives, asks, holds, next_ok):
    ledger = [{"type": "give"} for _ in range(gives)] + [{"type": "ask"} for _ in range(asks)]
    result = participation.ledger_balance(ledger)
    assert result["gives"] == gives and result["asks"] == asks
    assert result["holds_9to1"] is holds
    assert result["next_ask_ok"] is next_ok
