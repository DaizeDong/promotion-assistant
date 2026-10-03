"""Generated synthetic regressions for Promotion4. Reproduce with tools/make_fixtures.py."""
import copy
import datetime
import hashlib
import itertools
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import threading

import pytest

from scripts import (bandit, capabilities, dispatch, email_contract, events, learning,
                     orchestrate, participation, private_storage, providers, runs, seqtest, throttle)
from test_review_runs import SAMPLE, case, execute, live, authorized, ack


def test_tagged_case_sensitive_transport_address_is_preserved(case):
    selected = 'User1+Selected@example.com'
    case['audiences']['segments']['sample'][0]['recipient'] = selected
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    result = execute(case)
    payload = result['items'][0]['payload']
    assert result['status'] == 'simulated'
    assert payload['recipient'] == payload['destination'] == selected
    assert payload['suppression_key'] == 'user1@example.com'
    assert payload['audience_metadata']['recipient'] == selected
    stored = json.loads((case['root']/'metrics/runs'/(result['run_id']+'.json')).read_text())
    assert stored['items'][0]['payload']['recipient'] == selected


def test_alias_suppression_still_blocks_selected_transport(case, monkeypatch):
    case['audiences']['segments']['sample'][0]['recipient'] = 'User1+Selected@example.com'
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    (case['root']/'metrics/suppression.csv').write_text('USER1+blocked@example.com\n')
    calls = live(case, monkeypatch)
    result = authorized(case)
    assert result['counts'] == {'blocked': 1, 'complete': 1}
    assert len(calls) == 1 and calls[0]['recipient'] == 'user2@example.com'


def email_fixture():
    return copy.deepcopy(SAMPLE['email_payload'])


def wire_helper(case, monkeypatch, responder):
    helper = case['root']/'synthetic-mail.ps1'
    helper.write_text('# synthetic helper seam')
    monkeypatch.setattr(providers, 'SEND_GMAIL_PS1', helper)
    calls = []
    def process(argv, **kwargs):
        request = json.loads(argv[argv.index('-RequestJson')+1])
        calls.append(request)
        return subprocess.CompletedProcess(argv, 0, json.dumps(responder(request)), '')
    monkeypatch.setattr(providers.subprocess, 'run', process)
    return calls


def helper_receipt(request):
    return {field: request[field] for field in
            ('contract', 'platform', 'idempotency_key', 'destination', 'recipient', 'sender', 'request_sha256')} | {
                'status': 'sent', 'message_id': 'synthetic-remote-id'}


def test_email_helper_receives_complete_frozen_request(case, monkeypatch):
    calls = wire_helper(case, monkeypatch, helper_receipt)
    payload = email_fixture()
    payload['recipient'] = payload['destination'] = 'User1+Selected@example.com'
    result = providers.EmailProvider().publish(payload, live=True)
    assert dispatch.matching_receipt(result, payload)
    request = calls[0]
    assert request['recipient'] == 'User1+Selected@example.com'
    assert request['sender'] == payload['from_addr'] and request['subject'] == payload['subject']
    assert request['body'] == '\n\n'.join(payload[field] for field in
                                         ('body', 'cta', 'physical_address', 'unsubscribe'))
    unsigned = {key: value for key, value in request.items() if key != 'request_sha256'}
    assert request['request_sha256'] == hashlib.sha256(json.dumps(
        unsigned, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


@pytest.mark.parametrize('field', ['contract', 'platform', 'idempotency_key', 'destination',
                                  'recipient', 'sender', 'request_sha256', 'message_id'])
@pytest.mark.parametrize('mutation', ['missing', 'wrong'])
def test_email_receipt_must_prove_each_required_field(case, monkeypatch, field, mutation):
    def response(request):
        result = helper_receipt(request)
        if mutation == 'missing':
            result.pop(field)
        else:
            result[field] = '' if field == 'message_id' else 'synthetic-wrong'
        return result
    calls = wire_helper(case, monkeypatch, response)
    result = providers.EmailProvider().publish(email_fixture(), live=True)
    assert result['status'] == 'uncertain' and len(calls) == 1
    assert not dispatch.matching_receipt(result, email_fixture())


def test_unconfigured_email_contract_is_proven_not_applied(case, monkeypatch):
    calls = wire_helper(case, monkeypatch, helper_receipt)
    payload = email_fixture()
    payload.pop('email_helper_contract')
    result = providers.EmailProvider().publish(payload, live=True)
    assert dispatch.matching_receipt(result, payload, 'not_applied') and calls == []
    assert 'reviewed-email-v1' in result['reason']


@pytest.mark.parametrize('field', ['body', 'cta', 'physical_address', 'unsubscribe'])
def test_changed_email_rendering_is_not_sent(case, monkeypatch, field):
    calls = wire_helper(case, monkeypatch, helper_receipt)
    payload = email_fixture()
    payload[field] += ' synthetic changed value'
    result = providers.EmailProvider().publish(payload, live=True)
    assert dispatch.matching_receipt(result, payload, 'not_applied') and calls == []


@pytest.mark.parametrize('platform', ['email', 'discord', 'mastodon', 'bluesky'])
def test_missing_provider_setup_is_retryable_without_publication(case, monkeypatch, platform):
    payload = {**email_fixture(), 'platform': platform}
    for key in SAMPLE['credentials']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(providers, 'SEND_GMAIL_PS1', case['root']/'absent-helper')
    def effect(*args, **kwargs):
        pytest.fail('known setup failure must not publish')
    monkeypatch.setattr(providers.subprocess, 'run', effect)
    monkeypatch.setattr(providers.urllib.request, 'urlopen', effect)
    result = providers.get(platform).publish(payload, live=True)
    assert dispatch.matching_receipt(result, payload, 'not_applied')


def test_missing_email_helper_can_retry_exact_saved_action(case, monkeypatch):
    case['cfg'].product['send_mode'] = 'live'
    monkeypatch.setattr(providers, 'SEND_GMAIL_PS1', case['root']/'absent-helper')
    first = authorized(case)
    assert first['status'] == 'failed' and all(item['safe_to_retry'] for item in first['items'])
    keys = [item['idempotency_key'] for item in first['items']]
    calls = wire_helper(case, monkeypatch, helper_receipt)
    second = authorized(case, resume=True)
    assert second['status'] == 'complete'
    assert [payload['idempotency_key'] for payload in calls] == keys


def test_shared_admission_failure_stops_storage(case, monkeypatch):
    api = private_storage._guard_api()
    calls = []
    def refused(repo):
        calls.append(repo)
        raise api.GitError('synthetic PUBLIC or unknown route')
    monkeypatch.setattr(api, 'prove_private_companion', refused)
    with pytest.raises(ValueError, match='PRIVATE companion verification failed'):
        private_storage.prove(case['root']/'metrics/state.json')
    assert calls == [case['root']]


def test_private_proof_names_all_accepted_destinations_and_is_fresh(case, monkeypatch):
    api = private_storage._guard_api()
    assert private_storage.publication_destinations(case['root']) == ('example/synthetic-promotion-config',)
    path = case['root']/'metrics/events.jsonl'
    events.append(path, events.make_event('synthetic', 'drafted'))
    previous = path.read_bytes()
    def refused(repo):
        raise api.GitError('synthetic visibility changed')
    monkeypatch.setattr(api, 'prove_private_companion', refused)
    with pytest.raises(ValueError):
        events.append(path, events.make_event('synthetic', 'drafted'))
    assert path.read_bytes() == previous


def reserve(thr, key, *, policy=None, payload=None, action='post'):
    return thr.reserve('synthetic-account', 'email', action, policy or {'day_cap': 1, 'min_gap_sec': 0},
                       reservation_id=key, payload=payload or {'body': 'synthetic'})


def test_two_preloaded_writers_cannot_overspend_shared_cap(case):
    path = case['root']/'metrics/throttle-state.json'
    first, second = [throttle.Throttle(path, clock=lambda: 1000) for _ in range(2)]
    barrier = threading.Barrier(2)
    def attempt(pair):
        instance, key = pair
        barrier.wait(timeout=5)
        return reserve(instance, key)[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [(first, 'synthetic-a'), (second, 'synthetic-b')]))
    assert sum(results) == 1
    saved = json.loads(path.read_text())
    assert len(saved['reservations']) == 1
    assert next(iter(saved['buckets'].values()))['tokens'] == 0


def test_reservation_survives_lost_process_and_reuses_only_same_intent(case):
    path = case['root']/'metrics/throttle-state.json'
    assert reserve(throttle.Throttle(path, clock=lambda: 1000), 'synthetic-a')[0]
    restarted = throttle.Throttle(path, clock=lambda: 1001)
    assert not reserve(restarted, 'synthetic-b')[0]
    assert reserve(restarted, 'synthetic-a')[0]
    with pytest.raises(ValueError, match='collides'):
        reserve(restarted, 'synthetic-a', payload={'body': 'changed synthetic intent'})
    with pytest.raises(ValueError, match='collides'):
        reserve(restarted, 'synthetic-a', action='dm')


@pytest.mark.parametrize('malformed', ['', '{', '[]', '{"schema_version":true}', '{"bucket":{}}'])
def test_malformed_throttle_never_resets_capacity(case, malformed):
    path = case['root']/'metrics/throttle-state.json'
    path.write_text(malformed)
    with pytest.raises(ValueError):
        throttle.Throttle(path, clock=lambda: 1000)
    assert path.read_text() == malformed


def test_old_reservation_cannot_skip_new_period_cap(case):
    now = [1000]
    instance = throttle.Throttle(case['root']/'metrics/throttle-state.json', clock=lambda: now[0])
    assert reserve(instance, 'synthetic-a')[0]
    now[0] += 86401
    assert reserve(instance, 'synthetic-b')[0]
    assert not reserve(instance, 'synthetic-a')[0]


def test_same_reservation_obeys_current_pacing_and_account_cooldown(case):
    now = [1000]
    instance = throttle.Throttle(case['root']/'metrics/throttle-state.json', clock=lambda: now[0])
    policy = {'day_cap': 2, 'min_gap_sec': 100, 'backoff': {'factor': 0.5, 'cooldown_h': 1}}
    assert reserve(instance, 'synthetic-a', policy=policy)[0]
    assert not reserve(instance, 'synthetic-a', policy=policy)[0]
    instance.record_throttle_signal('synthetic-account', 'email', 'post', policy)
    restarted = throttle.Throttle(instance.path, clock=lambda: now[0]+200)
    assert not reserve(restarted, 'synthetic-a', policy=policy)[0]
    assert not reserve(restarted, 'synthetic-dm', policy=policy, action='dm')[0]


def test_429_persists_cooldown_before_next_item_and_next_run(case, monkeypatch):
    calls = live(case, monkeypatch, lambda payload, count: {
        'status': 'throttled', 'rate_limited': True, 'reason': 'synthetic 429'})
    first = authorized(case)
    assert first['counts'] == {'uncertain': 1, 'deferred': 1} and len(calls) == 1
    saved = json.loads((case['root']/'metrics/throttle-state.json').read_text())
    assert saved['cooldowns'] and not first['items'][0]['safe_to_retry']
    second = orchestrate.run_once(case['cfg'], case['campaign'], run_id='synthetic-next',
                                 env={'PROMO_LIVE_AUTHORIZED_EMAIL': 'synthetic-token'})
    assert second['counts'] == {'deferred': 2} and len(calls) == 1


def test_cooldown_persistence_failure_stops_remaining_effects(case, monkeypatch):
    calls = live(case, monkeypatch, lambda payload, count: {
        'status': 'throttled', 'rate_limited': True, 'reason': 'synthetic 429'})
    def failed(*args, **kwargs):
        raise OSError('synthetic cooldown write failure')
    monkeypatch.setattr(throttle.Throttle, 'record_throttle_signal', failed)
    result = authorized(case)
    assert result['status'] == 'uncertain' and len(calls) == 1
    saved = json.loads((case['root']/'metrics/runs'/(case['run_id']+'.json')).read_text())
    assert saved['items'][0]['status'] == 'uncertain' and saved['items'][1]['status'] == 'pending'


def test_complete_resume_does_not_recredit_and_delayed_event_credits_once(case, monkeypatch):
    calls = live(case, monkeypatch)
    first = authorized(case)
    path = case['root']/'metrics/bandit-state.json'
    baseline = path.read_bytes()
    assert authorized(case, resume=True)['reward_status'] == 'no-new-observations'
    assert path.read_bytes() == baseline and len(calls) == 2
    decision = first['items'][0]['idempotency_key']
    ev = events.make_event('email', 'conversion', arm_id=first['arm'], decision_id=decision)
    events.append(case['root']/'metrics/events.jsonl', ev)
    assert authorized(case, resume=True)['reward_status'] == 'ok'
    updated = path.read_bytes()
    assert updated != baseline
    assert authorized(case, resume=True)['reward_status'] == 'no-new-observations'
    assert path.read_bytes() == updated
    assert json.loads(updated)['arms'][first['arm']]['n_pulls'] == 3


def test_unrelated_arm_history_is_not_credited_to_this_run(case, monkeypatch):
    events.append(case['root']/'metrics/events.jsonl', events.make_event(
        'email', 'conversion', arm_id=SAMPLE['arms'][0]['id'], decision_id='synthetic-other-decision'))
    live(case, monkeypatch)
    result = authorized(case)
    saved = json.loads((case['root']/'metrics/bandit-state.json').read_text())
    assert saved['arms'][result['arm']]['n_pulls'] == 2
    assert all(credit['decision_id'] != 'synthetic-other-decision'
               for credit in saved['observation_credits'].values())


def test_censored_event_waits_for_new_linked_evidence(case):
    path = case['root']/'metrics/bandit-state.json'
    row = events.make_event('email', 'sent', arm_id='synthetic-arm', decision_id='synthetic-decision',
                            ts=1000, propensity_p=1.0, policy_version='synthetic')
    args = {'arm_id': 'synthetic-arm', 'decision_ids': ['synthetic-decision'], 'conversion_window_s': 100}
    assert learning.credit_observations(path, [row], now=1001, **args) == (None, 'censored')
    baseline = path.read_bytes()
    assert learning.credit_observations(path, [row], now=1200, **args) == (None, 'no-new-observations')
    assert path.read_bytes() == baseline
    conversion = events.make_event('email', 'conversion', arm_id='synthetic-arm',
                                   decision_id='synthetic-decision', ts=1200)
    assert learning.credit_observations(path, [row, conversion], now=1200, **args)[1] == 'ok'
    assert json.loads(path.read_text())['arms']['synthetic-arm']['n_pulls'] == 1


def test_legacy_posterior_baselines_history_without_recredit(case):
    path = case['root']/'metrics/bandit-state.json'
    legacy = {'policy_version': 'synthetic', 'arms': {
        'synthetic-arm': {'arm_id': 'synthetic-arm', 'alpha': 3.0, 'beta': 2.0, 'n_pulls': 3}}}
    path.write_text(json.dumps(legacy))
    row = events.make_event('email', 'conversion', arm_id='synthetic-arm', decision_id='synthetic-decision')
    result = learning.credit_observations(path, [row], arm_id='synthetic-arm', decision_ids=['synthetic-decision'])
    assert result == (None, 'legacy-baseline-established')
    saved = json.loads(path.read_text())
    assert saved['arms'] == legacy['arms']
    assert saved['observation_credits'][row['event_id']]['status'] == 'legacy-observed'


def test_reused_observation_id_with_changed_content_is_rejected(case):
    path = case['root']/'metrics/bandit-state.json'
    row = events.make_event('email', 'conversion', arm_id='synthetic-arm', decision_id='synthetic-decision')
    args = {'arm_id': 'synthetic-arm', 'decision_ids': ['synthetic-decision']}
    learning.credit_observations(path, [row], **args)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='identity changed'):
        learning.credit_observations(path, [{**row, 'value': 2.0}], **args)
    assert path.read_bytes() == before


def test_manual_arm_choice_has_truthful_human_provenance_and_deduplicates(case):
    args = {'channel': 'synthetic-manual', 'url': 'https://example.com/posts/synthetic',
            'arm_id': 'synthetic-arm', 'campaign': 'synthetic-campaign'}
    first = orchestrate.record_post(case['cfg'], **args)
    second = orchestrate.record_post(case['cfg'], **args)
    assert first['status'] == second['status'] == 'recorded' and first['event_id'] == second['event_id']
    row = events.read(case['root']/'metrics/events.jsonl')[0]
    assert row['decision_origin'] == row['actuator'] == 'human'
    assert row['propensity_p'] is None and row['policy_version'] is None
    assert events.validate_event(row) == []
    assert events.validate_event({**row, 'propensity_p': 0.5})
    assert orchestrate.record_post(case['cfg'], **{**args, 'arm_id': 'other-arm'})['status'] == 'error'


def manual_case(case):
    case['cfg'].registry['channels'][0].update(slug='synthetic-manual', platform='reddit', transport='post')
    case['arms'][0]['channel'] = 'synthetic-manual'
    (case['root']/'copy'/(case['campaign']+'.json')).write_text(json.dumps(case['arms']))
    return case


def test_prepared_choice_retains_real_probability(case):
    manual_case(case)
    result = orchestrate.prep_once(case['cfg'], case['campaign'])
    assert result['status'] == 'prepared'
    recorded = orchestrate.record_post(case['cfg'], 'synthetic-manual', 'https://example.com/posts/synthetic',
                                        decision_id=result['decision_id'])
    assert recorded['status'] == 'recorded'
    rows = events.read(case['root']/'metrics/events.jsonl')
    assert rows[-1]['decision_origin'] == 'bandit'
    assert rows[-1]['propensity_p'] == rows[0]['propensity_p'] > 0
    assert rows[-1]['policy_version'] == rows[0]['policy_version']


def test_manual_prep_checks_actual_copy_before_prepared_event(case):
    manual_case(case)
    case['arms'][0]['body'] = 'Synthetic copy with unlimited free promises'
    (case['root']/'copy'/(case['campaign']+'.json')).write_text(json.dumps(case['arms']))
    result = orchestrate.prep_once(case['cfg'], case['campaign'])
    assert result['status'] == 'blocked' and result['reasons']
    assert events.read(case['root']/'metrics/events.jsonl') == []


def test_participation_requires_explicit_thread_draft_and_final_type(case):
    path = case['root']/'metrics/events.jsonl'
    first_thread = 'https://www.reddit.com/r/synthetic/comments/abc/topic'
    second_thread = 'https://www.reddit.com/r/synthetic/comments/def/other'
    first = events.make_event('reddit-participation', 'drafted', platform='reddit',
                              thread=participation.thread_identity(first_thread), graduated=True,
                              compliance_ok=True, utm={'content': 'synthetic-aff'})
    later = events.make_event('reddit-participation', 'drafted', platform='reddit',
                              thread=participation.thread_identity(second_thread), graduated=False)
    for row in [first, later]:
        events.append(path, row)
    assert participation.confirmed_entries(events.read(path)) == []
    kwargs = {'thread': first_thread, 'draft_id': first['event_id'], 'participation_type': 'ask'}
    url = first_thread+'/xyz'
    result = orchestrate.record_participation(case['cfg'], url, **kwargs)
    assert result['status'] == 'recorded' and result['linked_draft'] == first['event_id']
    repeated = orchestrate.record_participation(case['cfg'], url+'?utm_source=synthetic', **kwargs)
    assert repeated['event_id'] == result['event_id']
    rows = events.read(path)
    assert rows[-1]['graduated'] is True and rows[-1]['participation_type'] == 'ask'
    ledger = participation.ledger_balance(participation.confirmed_entries(rows))
    assert ledger['gives'] == 0 and ledger['asks'] == 1
    assert orchestrate.record_participation(case['cfg'], url, **{**kwargs, 'draft_id': later['event_id']})['status'] == 'error'
    assert orchestrate.record_participation(case['cfg'], url, **{**kwargs, 'participation_type': 'give'})['status'] == 'error'
    assert orchestrate.record_participation(case['cfg'], url, thread=first_thread)['status'] == 'error'


@pytest.mark.parametrize('alpha', [0.05, 0.2, 0.5])
def test_two_sided_p_agrees_with_crossing_and_finite_null_peeking(alpha):
    rejected = 0
    horizon = 10
    for signs in itertools.product((0, 1), repeat=horizon):
        test = seqtest.SequentialABTest(alpha=alpha)
        prior = 1.0
        for sign in signs:
            snapshot = test.update(sign, 1-sign)
            assert snapshot['p_value'] == min(1.0, 2.0/snapshot['max_one_sided_wealth'])
            assert snapshot['p_value'] <= prior
            assert (snapshot['p_value'] <= alpha) == snapshot['reject']
            prior = snapshot['p_value']
        rejected += test.reject
    # Exact enumeration of the independent, conditionally symmetric paired-sign null.
    assert rejected/(2**horizon) <= alpha


def test_schedule_keys_include_obligation_and_respect_horizon(case):
    class Bridge:
        def __init__(self):
            self.calls = []
        def available(self):
            return True
        def schedule_item(self, **kwargs):
            self.calls.append(kwargs)
            return {'ok': True, 'item': {'id': kwargs['idempotency_key']}}
    arms = [{**SAMPLE['arms'][0], 'id': 'synthetic-arm-'+str(index)} for index in range(3)]
    (case['root']/'copy'/(case['campaign']+'.json')).write_text(json.dumps(arms))
    (case['root']/'channels/email/policy.json').write_text(json.dumps({'min_gap_sec': 172800}))
    start = datetime.datetime(2026, 1, 1)
    short, long = Bridge(), Bridge()
    assert orchestrate.plan(case['cfg'], case['campaign'], start=start, days=1, bridge=short)['scheduled'] == 1
    assert orchestrate.plan(case['cfg'], case['campaign'], start=start, days=5, bridge=long)['scheduled'] == 3
    assert short.calls[0]['idempotency_key'] == long.calls[0]['idempotency_key']
    alternate = 'synthetic-other-campaign'
    (case['root']/'copy'/(alternate+'.json')).write_text(json.dumps(arms))
    changed = Bridge()
    orchestrate.plan(case['cfg'], alternate, start=start, days=1, bridge=changed)
    assert changed.calls[0]['idempotency_key'] != short.calls[0]['idempotency_key']
    case['cfg'].registry['channels'][0]['account_handle'] = 'synthetic-other-account'
    account = Bridge()
    orchestrate.plan(case['cfg'], case['campaign'], start=start, days=1, bridge=account)
    assert account.calls[0]['idempotency_key'] != short.calls[0]['idempotency_key']
    with pytest.raises(ValueError):
        orchestrate.plan(case['cfg'], case['campaign'], days=0, bridge=Bridge())


def test_email_resource_without_reviewed_contract_is_not_ready(case, monkeypatch):
    helper = case['root']/'synthetic-helper.ps1'
    helper.write_text('# synthetic')
    case['cfg'].registry['channels'][0].pop('email_helper_contract')
    result = capabilities.doctor(case['cfg'], env={'PROMO_SEND_GMAIL': str(helper)})
    assert result['status'] == 'not_ready'
    assert not result['channels'][0]['configured'] and result['live_proven'] == 'not_run'


@pytest.mark.parametrize('name', ['events.jsonl', 'throttle-state.json', 'bandit-state.json', 'synthetic-run.json'])
def test_existing_output_hardlinks_are_refused(case, name):
    source = case['root']/'synthetic-original.txt'
    source.write_text('synthetic retained content')
    target = case['root']/'metrics'/name
    os.link(source, target)
    assert target.stat().st_nlink == 2
    with pytest.raises(ValueError, match='hardlink'):
        private_storage.prove(target)
    assert source.read_text() == target.read_text() == 'synthetic retained content'


def test_repeated_same_dispatch_outcome_has_one_observation_identity(case, monkeypatch):
    (case['root']/'metrics/suppression.csv').write_text('user1@example.com\nuser2@example.com\n')
    live(case, monkeypatch)
    first = authorized(case)
    assert first['counts'] == {'blocked': 2}
    path = case['root']/'metrics/bandit-state.json'
    before = path.read_bytes()
    assert authorized(case, resume=True)['reward_status'] == 'no-new-observations'
    assert path.read_bytes() == before
    rows = events.read(case['root']/'metrics/events.jsonl')
    assert len(rows) == 2 and len({row['event_id'] for row in rows}) == 2


def test_throttle_semantically_corrupt_capacity_is_not_accepted(case):
    path = case['root']/'metrics/throttle-state.json'
    instance = throttle.Throttle(path, clock=lambda: 1000)
    assert reserve(instance, 'synthetic-a')[0]
    document = json.loads(path.read_text())
    next(iter(document['buckets'].values()))['tokens'] = 99
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='exceed'):
        throttle.Throttle(path, clock=lambda: 1001)
    assert path.read_bytes() == before
