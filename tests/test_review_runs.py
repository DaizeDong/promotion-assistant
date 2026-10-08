"""Public generated controls, using only synthetic PRIVATE metadata and effect seams."""
import copy
import json
from pathlib import Path
import subprocess

import pytest
from scripts import config, orchestrate, dispatch, providers, schedule_bridge, email_contract

SAMPLE = json.loads((Path(__file__).parent/'fixtures/promotion.json').read_text())


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path/'companion'
    root.mkdir()
    (root/'.git').mkdir()
    sample = copy.deepcopy(SAMPLE)
    for folder in ('copy', 'channels/email', 'metrics', 'compliance'):
        (root/folder).mkdir(parents=True, exist_ok=True)
    paths = {'product.json': sample['product'], 'registry.json': sample['registry'],
             'audiences.json': sample['audiences'],
             'copy/'+sample['campaign']+'.json': sample['arms'],
             'channels/email/policy.json': sample['policy']}
    for name, value in paths.items():
        (root/name).write_text(json.dumps(value), encoding='utf-8')
    (root/'compliance/consent-ledger.jsonl').write_text(
        ''.join(json.dumps(row)+'\n' for row in sample['consent']), encoding='utf-8')

    def process(argv, **kwargs):
        if argv[0] == 'git':
            if '--show-toplevel' in argv:
                answer = str(root)
            elif argv[-1:] == ['remote']:
                answer = 'origin'
            elif argv[-3:] == ['rev-parse', '--verify', 'HEAD']:
                answer = '1'*40
            elif 'get-url' in argv and '--all' in argv:
                answer = sample['origin']
            else:
                raise AssertionError('unexpected Git metadata query')
        elif argv[0] == 'gh':
            answer = json.dumps({'visibility': 'PRIVATE', 'nameWithOwner': 'example/synthetic-promotion-config'})
        else:
            raise AssertionError('unexpected external process')
        return subprocess.CompletedProcess(argv, 0, answer, '')

    monkeypatch.setattr(subprocess, 'run', process)
    sample.update(root=root, cfg=config.Config(root))
    return sample


def execute(case, **kwargs):
    return orchestrate.run_once(case['cfg'], case['campaign'], env={}, **kwargs)


def test_review_expands_full_payload_and_permission(case):
    result = execute(case)
    assert result['status'] == 'simulated' and result['counts']['simulated'] == 2
    assert len(result['items']) == 2
    for item in result['items']:
        assert item['payload']['body'] == case['arms'][0]['body']
        assert item['payload']['destination'] == item['payload']['recipient']
        assert item['eligibility']['consent'] and item['eligibility']['suppressed'] is False
    rows = [json.loads(line) for line in (case['root']/'metrics/dry-run.jsonl').read_text().splitlines()]
    assert all(row['would_send']['body'] == case['arms'][0]['body'] for row in rows)


def test_withdrawal_overrides_old_and_retained_lawful_basis(case):
    record = {**case['consent'][0], 'status': 'withdrawn'}
    with (case['root']/'compliance/consent-ledger.jsonl').open('a') as stream:
        stream.write(json.dumps(record)+'\n')
    result = execute(case)
    assert result['status'] == 'partial' and result['counts']['blocked'] == 1
    previews = [json.loads(row) for row in (case['root']/'metrics/dry-run.jsonl').read_text().splitlines()]
    assert len(previews) == 2 and any(row['status'] == 'rejected' for row in previews)
    assert all(row['payload']['body'] == case['arms'][0]['body'] for row in previews)


def test_missing_segment_is_visible_and_blocked(case):
    (case['root']/'audiences.json').write_text('{}')
    assert execute(case)['status'] == 'blocked'


@pytest.mark.parametrize('recipient', SAMPLE['invalid_recipients'])
def test_blocked_recipient_input_survives_review_preview_and_history(case, recipient):
    case['audiences']['segments']['sample'] = [
        {'recipient': recipient, 'recipient_country': 'US'}]
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    result = execute(case, run_id=case['run_id'])
    assert result['status'] == 'blocked'
    item = result['items'][0]
    assert item['payload']['destination'] == ''
    preview = json.loads((case['root']/'metrics/dry-run.jsonl').read_text().splitlines()[0])
    saved = json.loads((case['root']/'metrics/runs'/(case['run_id']+'.json')).read_text())
    for payload in (item['payload'], preview['payload'], saved['items'][0]['payload']):
        assert payload['supplied_recipient'] == recipient
        assert payload['idempotency_key'] == item['idempotency_key']


def test_distinct_blocked_inputs_keep_their_association_on_resume(case, monkeypatch):
    recipients = case['invalid_recipients'][1:3]
    case['audiences']['segments']['sample'] = [
        {'recipient': recipient, 'recipient_country': 'US'} for recipient in recipients]
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    calls = live(case, monkeypatch)
    first = authorized(case)
    assert first['counts'] == {'blocked': 2}
    original_keys = [item['idempotency_key'] for item in first['items']]
    assert len(set(original_keys)) == 2

    (case['root']/'audiences.json').write_text('{}')
    resumed = authorized(case, resume=True)
    assert resumed['counts'] == {'blocked': 2} and calls == []
    assert [item['idempotency_key'] for item in resumed['items']] == original_keys
    assert [item['payload']['supplied_recipient']
            for item in resumed['items']] == recipients


def test_equivalent_duplicates_collapse(case):
    audiences = case['audiences']
    audiences['segments']['sample'].append({'recipient': 'USER1+tag@example.com', 'recipient_country': 'us'})
    (case['root']/'audiences.json').write_text(json.dumps(audiences))
    result = execute(case)
    assert len(result['items']) == 2 and result['duplicate_count'] == 1


def test_new_run_is_durable_and_existing_id_never_overwrites(case):
    first = execute(case, run_id=case['run_id'])
    path = case['root']/'metrics/runs'/(case['run_id']+'.json')
    before = path.read_bytes()
    assert first['run_id'] == case['run_id']
    assert execute(case, run_id=case['run_id'])['status'] == 'failed'
    assert path.read_bytes() == before


@pytest.mark.parametrize('run_id', SAMPLE['invalid_runs'])
def test_invalid_run_identity_fails(case, run_id):
    assert execute(case, run_id=run_id)['status'] in {'blocked', 'failed'}


def test_missing_prep_scope_never_falls_back(case):
    assert orchestrate.prep_once(case['cfg'], case['campaign'], channel='absent')['status'] == 'blocked'


def test_explicit_missing_config_is_authoritative(case, monkeypatch):
    monkeypatch.setenv('PROMO_CONFIG_DIR', str(case['root']))
    with pytest.raises(config.ConfigError):
        config.load(str(case['root']/'missing'))


def test_schedule_non_json_cannot_confirm(case, monkeypatch):
    helper = case['root']/'synthetic-helper.py'
    helper.write_text('# Synthetic helper')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, 'not JSON', ''))
    result = schedule_bridge.ScheduleBridge(helper).schedule_item(
        title='Synthetic task', due_at='2026-01-01T00:00:00Z', idempotency_key='synthetic', ext={})
    assert result['ok'] is False


def live(case, monkeypatch, response=None):
    case['cfg'].product['send_mode'] = 'live'
    calls = []

    class Adapter:
        LIVE_TRANSPORT = True

        def publish(self, payload, *, live=False):
            calls.append(copy.deepcopy(payload))
            if response:
                return response(payload, len(calls))
            return ack(payload)

        dm = publish

    monkeypatch.setattr(providers, 'get', lambda platform: Adapter())
    return calls


def ack(payload, status='sent'):
    envelope = email_contract.request(payload) if payload.get('platform') == 'email' else {}
    return {**envelope, 'status': status, 'platform': payload['platform'],
            'idempotency_key': payload['idempotency_key'], 'destination': payload['destination'],
            'message_id': SAMPLE['message_id'], 'evidence': 'Synthetic provider proves no application',
            'evidence_kind': 'synthetic'}


def authorized(case, **kwargs):
    return orchestrate.run_once(case['cfg'], case['campaign'], run_id=case['run_id'],
                               env={'PROMO_LIVE_AUTHORIZED_EMAIL': 'synthetic-token'}, **kwargs)


@pytest.mark.parametrize('response', SAMPLE['invalid_ack'])
def test_ambiguous_acknowledgements_are_durable_uncertainty(case, monkeypatch, response):
    calls = live(case, monkeypatch, lambda payload, count: response)
    result = authorized(case)
    assert result['status'] == 'uncertain' and len(calls) == 2
    assert all(not item['safe_to_retry'] for item in result['items'])
    again = authorized(case, resume=True)
    assert again['status'] == 'uncertain' and len(calls) == 2


def test_success_requires_durable_intent_and_does_not_repeat(case, monkeypatch):
    path = case['root']/'metrics/runs'/(case['run_id']+'.json')

    def respond(payload, count):
        stored = json.loads(path.read_text())
        item = next(item for item in stored['items'] if item['idempotency_key'] == payload['idempotency_key'])
        assert item['status'] == 'uncertain'
        return ack(payload)

    calls = live(case, monkeypatch, respond)
    assert authorized(case)['status'] == 'complete' and len(calls) == 2
    assert authorized(case, resume=True)['status'] == 'complete' and len(calls) == 2


def test_reconciliation_confirms_without_resend_or_audience_expansion(case, monkeypatch):
    def respond(payload, count):
        if count == 2:
            raise TimeoutError('Synthetic ambiguous response')
        return ack(payload)

    calls = live(case, monkeypatch, respond)
    assert authorized(case)['status'] == 'uncertain'
    case['audiences']['segments']['sample'].append({'recipient': 'user3@example.com', 'recipient_country': 'US'})
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    monkeypatch.setattr(dispatch, 'reconcile_action', lambda item, **kwargs: ack(item['payload']))
    result = authorized(case, resume=True)
    assert result['status'] == 'complete' and len(result['items']) == 2 and len(calls) == 2


def test_not_applied_reconciliation_retries_same_key(case, monkeypatch):
    calls = live(case, monkeypatch, lambda payload, count: None if count == 1 else ack(payload))
    assert authorized(case)['status'] == 'uncertain'
    monkeypatch.setattr(dispatch, 'reconcile_action', lambda item, **kwargs: ack(item['payload'], 'not_applied'))
    assert authorized(case, resume=True)['status'] == 'complete'
    assert len(calls) == 3 and calls[0]['idempotency_key'] == calls[-1]['idempotency_key']


def test_scope_change_preserves_run_and_excludes_effects(case, monkeypatch):
    calls = live(case, monkeypatch)
    authorized(case)
    path = case['root']/'metrics/runs'/(case['run_id']+'.json')
    before = path.read_bytes()
    arms = case['arms']
    arms[0]['body'] += ' Synthetic changed proposal.'
    (case['root']/'copy'/(case['campaign']+'.json')).write_text(json.dumps(arms))
    assert authorized(case, resume=True)['status'] == 'failed'
    assert len(calls) == 2 and path.read_bytes() == before


def test_resume_rechecks_suppression_before_known_failed_retry(case, monkeypatch):
    calls = live(case, monkeypatch, lambda payload, count: ack(payload, 'not_applied'))
    assert authorized(case)['status'] == 'failed'
    (case['root']/'metrics/suppression.csv').write_text('USER1+alias@example.com\n')
    result = authorized(case, resume=True)
    assert result['counts']['blocked'] == 1 and len(calls) == 3


def test_persistence_failure_prevents_provider_effect(case, monkeypatch):
    from scripts import runs
    calls = live(case, monkeypatch)
    monkeypatch.setattr(runs, 'save', lambda *a: (_ for _ in ()).throw(OSError('Synthetic persistence failure')))
    assert authorized(case)['status'] in {'failed', 'uncertain'}
    assert calls == []


def test_owned_broadcast_needs_no_segment_or_country(case):
    registration = case['cfg'].registry['channels'][0]
    registration.update(platform='discord', transport='post', **case['broadcast'])
    (case['root']/'audiences.json').unlink()
    result = execute(case)
    assert result['status'] == 'simulated' and len(result['items']) == 1
    assert result['items'][0]['payload']['destination'] == case['broadcast']['destination']


def test_missing_broadcast_destination_blocks(case):
    case['cfg'].registry['channels'][0].update(platform='discord', transport='post', audience_mode='owned_broadcast')
    assert execute(case)['status'] == 'blocked'


def test_conflicting_duplicate_metadata_blocks_instead_of_choosing(case):
    case['audiences']['segments']['sample'].append({'recipient': 'USER1+tag@example.com', 'recipient_country': 'DE'})
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    result = execute(case)
    assert result['counts']['blocked'] == 1 and result['duplicate_count'] == 1


def test_channel_capabilities_and_doctor_are_not_live_proof(case, monkeypatch, capsys):
    from scripts import cli
    resource = case['root']/'synthetic-mail.ps1'
    resource.write_text('# Synthetic resource')
    (case['root'] / 'secrets').mkdir(exist_ok=True)
    (case['root'] / 'secrets/runtime.env').write_text('PROMO_SEND_GMAIL='+str(resource)+'\n')
    assert cli.main(['--config', str(case['root']), 'channels', 'list', '--json']) == 0
    rows = json.loads(capsys.readouterr().out)['channels']
    assert rows[0]['implemented'] and rows[0]['configured'] and rows[0]['live_proven'] == 'not_run'
    assert cli.main(['--config', str(case['root']), 'doctor', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'ready'


def test_unavailable_selected_resource_is_not_ready(case, monkeypatch, capsys):
    from scripts import cli
    monkeypatch.setenv('PROMO_SEND_GMAIL', str(case['root']/'missing-helper'))
    assert cli.main(['--config', str(case['root']), 'doctor', '--json']) != 0
    assert json.loads(capsys.readouterr().out)['status'] == 'not_ready'


@pytest.mark.parametrize('platform', ['discord', 'mastodon', 'bluesky'])
@pytest.mark.parametrize('response', SAMPLE['adapter_responses'])
def test_actual_network_adapters_require_remote_proof(monkeypatch, platform, response):
    import urllib.request
    for name, value in SAMPLE['credentials'].items():
        monkeypatch.setenv(name, value)
    payload = {**SAMPLE['adapter_payload'], 'platform': platform}
    if platform in SAMPLE['owned_accounts']:
        payload.update(SAMPLE['owned_accounts'][platform]['payload'])
    requests = []

    class Reply:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.value).encode()

    def respond(request, **kwargs):
        if request.full_url.endswith('verify_credentials'):
            return Reply(SAMPLE['owned_accounts']['mastodon']['authenticated'])
        requests.append(request)
        return Reply(SAMPLE['session'] if request.full_url.endswith('createSession') else response['remote'])

    monkeypatch.setattr(urllib.request, 'urlopen', respond)
    result = providers.get(platform).publish(payload, live=True)
    assert (result['status'] == 'sent') is response['confirmed']
    assert len(requests) == (2 if platform == 'bluesky' else 1)
    if response['confirmed']:
        assert dispatch.matching_receipt(result, payload)
    if platform == 'mastodon':
        import hashlib
        headers = {key.lower(): value for key, value in requests[0].header_items()}
        assert headers['idempotency-key'] == hashlib.sha256(payload['idempotency_key'].encode()).hexdigest()


@pytest.mark.parametrize('response', SAMPLE['adapter_responses'])
def test_actual_email_requires_structured_message_id(case, monkeypatch, response):
    resource = case['root']/'synthetic-mail.ps1'
    resource.write_text('# Synthetic process seam')
    monkeypatch.setattr(providers, 'SEND_GMAIL_PS1', resource)
    payload = copy.deepcopy(SAMPLE['email_payload'])
    reply = {**email_contract.request(payload), **SAMPLE['receipt'], 'message_id': response['remote'].get('id')}
    calls = []

    def process(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(reply), '')

    monkeypatch.setattr(subprocess, 'run', process)
    result = providers.EmailProvider().publish(payload, live=True)
    assert (result['status'] == 'sent') is response['confirmed'] and len(calls) == 1
    if response['confirmed']:
        assert dispatch.matching_receipt(result, payload)


@pytest.mark.parametrize('reply', SAMPLE['schedule_responses'])
def test_schedule_receipt_and_cli_exit_agree(case, monkeypatch, capsys, reply):
    from scripts import cli
    helper = case['root']/'synthetic-reminder.py'
    helper.write_text('# Synthetic process seam')
    monkeypatch.setattr(schedule_bridge, 'REMINDER', helper)
    calls = []

    def process(argv, **kwargs):
        calls.append(argv)
        if argv[2] == 'creation-preflight':
            return subprocess.CompletedProcess(argv, 0, json.dumps(
                {'ok': True, 'complete': True, 'decision': 'create', 'matches': []}), '')
        return subprocess.CompletedProcess(argv, reply['rc'], reply['stdout'], '')

    monkeypatch.setattr(subprocess, 'run', process)
    rc = cli.main(['--config', str(case['root']), 'plan', '--campaign', case['campaign']])
    result = json.loads(capsys.readouterr().out)
    assert (rc == 0) is reply['ok'] and (result['status'] == 'complete') is reply['ok']
    assert result['scheduled'] == int(reply['ok']) and len(calls) == 2


def test_interruption_keeps_uncertainty_and_does_not_resend(case, monkeypatch):
    def interrupted(payload, count):
        raise KeyboardInterrupt

    calls = live(case, monkeypatch, interrupted)
    with pytest.raises(KeyboardInterrupt):
        authorized(case)
    stored = json.loads((case['root']/'metrics/runs'/(case['run_id']+'.json')).read_text())
    assert stored['items'][0]['status'] == 'uncertain'
    live(case, monkeypatch)
    result = authorized(case, resume=True)
    assert result['status'] == 'uncertain' and len(calls) == 1


@pytest.mark.parametrize('malformed', [None, {}, [], {'schema_version': 0}])
def test_malformed_saved_run_is_preserved(case, malformed):
    directory = case['root']/'metrics/runs'
    directory.mkdir()
    path = directory/(case['run_id']+'.json')
    path.write_text(json.dumps(malformed))
    before = path.read_bytes()
    assert execute(case, run_id=case['run_id'], resume=True)['status'] == 'failed'
    assert path.read_bytes() == before


def test_cli_run_dry_and_blocked_exit_contract(case, capsys):
    from scripts import cli
    args = ['--config', str(case['root']), 'run', '--once', '--campaign', case['campaign'], '--run-id', case['run_id']]
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'simulated' and sum(result['counts'].values()) == len(result['items'])
    assert cli.main(args) != 0
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'
    assert cli.main(args + ['--resume']) == 0
    capsys.readouterr()
    assert cli.main(['--config', str(case['root']), 'run', '--campaign', case['campaign'], '--channel', 'absent']) != 0
    assert json.loads(capsys.readouterr().out)['status'] == 'blocked'


@pytest.mark.parametrize('linked', [False, True])
@pytest.mark.parametrize('visibility', SAMPLE['visibility_responses'])
def test_private_api_boundary_normal_and_linked(tmp_path, monkeypatch, synthetic_private_metadata, linked, visibility):
    from scripts import private_storage
    from types import SimpleNamespace
    monkeypatch.setattr(private_storage, 'repository', synthetic_private_metadata)
    root = tmp_path/'synthetic-companion'
    root.mkdir()
    if linked:
        (root/'.git').write_text('gitdir: ../synthetic-control/worktrees/example\n')
    else:
        (root/'.git').mkdir()
    (root/'product.json').write_text(json.dumps(SAMPLE['product']))
    (root/'registry.json').write_text(json.dumps(SAMPLE['registry']))
    api = private_storage._guard_api()
    calls = []
    def proof(repo, visibility_map=None):
        calls.append(('proof', repo))
        if visibility != SAMPLE['visibility_responses'][0]:
            raise api.GitError('synthetic rejected visibility receipt')
        return SimpleNamespace(root=str(root), repositories=('example/synthetic-promotion-config',),
                               signature='synthetic-publication')
    def read(proof, *arguments):
        calls.append(('read', arguments))
        return SimpleNamespace(stdout='1'*40, returncode=1 if arguments[0] == 'check-ignore' else 0)
    monkeypatch.setattr(api, 'prove_private_companion', proof)
    monkeypatch.setattr(api, 'read_private_companion_git', read)
    if visibility == SAMPLE['visibility_responses'][0]:
        assert config.Config(root).metrics_dir() == root/'metrics'
    else:
        with pytest.raises(config.ConfigError):
            config.Config(root)
        assert not (root/'metrics').exists()
    assert calls[0] == ('proof', root)


def test_unversioned_and_source_storage_fail_before_metadata(tmp_path, monkeypatch, synthetic_private_metadata):
    from scripts import private_storage
    monkeypatch.setattr(private_storage, 'repository', synthetic_private_metadata)
    monkeypatch.setattr(private_storage, '_guard_api', lambda: pytest.fail('unversioned/source roots need no metadata lookup'))
    for root in (tmp_path, private_storage.ROOT):
        with pytest.raises(config.ConfigError):
            config.Config(root)


@pytest.mark.parametrize('relative', ['metrics', 'metrics/runs', 'metrics/events.jsonl',
                                      'compliance/consent-ledger.jsonl', 'audiences.json',
                                      'copy/'+SAMPLE['campaign']+'.json'])
def test_escaping_data_links_are_rejected(case, tmp_path, monkeypatch, relative):
    path = case['root']/relative
    outside = tmp_path/'synthetic-outside'
    outside.mkdir()
    directory = relative in {'metrics', 'metrics/runs'}
    if path.exists():
        if path.is_dir():
            path.rmdir()  # The generated metrics directory is empty in a fresh case.
        else:
            path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    target = outside if directory else outside/'synthetic-data.json'
    if not directory:
        target.write_text(json.dumps(SAMPLE['arms'] if relative.startswith('copy/') else SAMPLE['audiences']))
    if directory:
        import os
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(target), str(path))
        else:
            path.symlink_to(target, target_is_directory=True)
    else:
        # Windows file symlinks need unavailable privileges. Control only canonicalization;
        # actual directory junctions above exercise the filesystem boundary too.
        original_resolve = Path.resolve

        def resolved(value, *args, **kwargs):
            return target if value == path else original_resolve(value, *args, **kwargs)

        monkeypatch.setattr(Path, 'resolve', resolved)
    result = execute(case)
    assert result['status'] in {'failed', 'blocked'}
    assert not (outside/'events.jsonl').exists()


def test_highest_environment_selection_does_not_fall_through(case, monkeypatch):
    monkeypatch.setenv('PROMO_CONFIG_DIR', str(case['root']/'missing'))
    monkeypatch.setenv('PROMOTION_ASSISTANT_CONFIG', str(case['root']))
    with pytest.raises(config.ConfigError):
        config.load()


@pytest.mark.parametrize('platform', ['email', 'discord', 'mastodon', 'bluesky'])
def test_existing_provider_dry_gate_control(platform):
    # Positive controls also pass in the immutable initial source; unmocked effects fail globally.
    result = providers.get(platform).publish(SAMPLE['adapter_payload'], live=False)
    assert result['status'] != 'sent'


def test_existing_suppression_gate_control():
    from scripts import compliance
    payload = {**SAMPLE['adapter_payload'], 'platform': 'email', 'transport': 'smtp',
               'recipient_country': SAMPLE['audiences']['segments']['sample'][0]['recipient_country'],
               'from_addr': SAMPLE['product']['from_addr'],
               'physical_address': SAMPLE['product']['compliance']['physical_address'],
               'unsubscribe': SAMPLE['product']['compliance']['unsubscribe_url']}
    assert compliance.check(payload, policy={}, suppression=set(), consent={})[0]
    assert not compliance.check(payload, policy={}, suppression={payload['recipient']}, consent={})[0]


@pytest.mark.parametrize('recipient', SAMPLE['invalid_recipients'])
def test_malformed_email_never_becomes_guessed_destination(case, recipient):
    case['audiences']['segments']['sample'][0]['recipient'] = recipient
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    result = execute(case)
    assert result['counts']['blocked'] == 1 and result['items'][0]['status'] == 'blocked'


@pytest.mark.parametrize('country', SAMPLE['invalid_countries'])
def test_invalid_recipient_country_blocks(case, country):
    case['audiences']['segments']['sample'][0]['recipient_country'] = country
    (case['root']/'audiences.json').write_text(json.dumps(case['audiences']))
    assert execute(case)['counts']['blocked'] == 1


def test_review_checks_the_end_of_full_body(case):
    case['arms'][0]['body'] = SAMPLE['late_banned_claim']
    (case['root']/'copy'/(case['campaign']+'.json')).write_text(json.dumps(case['arms']))
    result = execute(case)
    assert result['status'] == 'blocked' and result['counts']['blocked'] == 2
    assert all(item['payload']['body'] == SAMPLE['late_banned_claim'] for item in result['items'])


@pytest.mark.parametrize('platform', ['discord', 'mastodon', 'bluesky'])
def test_oversized_reviewed_payload_is_not_silently_truncated(monkeypatch, platform):
    for name, value in SAMPLE['credentials'].items():
        monkeypatch.setenv(name, value)
    payload = {**SAMPLE['adapter_payload'], 'body': SAMPLE['oversized_body'], 'platform': platform}
    result = providers.get(platform).publish(payload, live=True)
    assert dispatch.matching_receipt(result, payload, 'not_applied')
