"""Generator-backed owned-account regressions through the real saved-run caller."""
import copy
import json
import urllib.request

import pytest
from scripts import config, orchestrate, runs
from test_review_runs import SAMPLE, case


@pytest.fixture(params=['bluesky', 'mastodon'])
def owned(case, monkeypatch, request):
    platform = request.param
    sample = copy.deepcopy(SAMPLE['owned_accounts'][platform])
    root = case['root']
    product = {**case['product'], 'send_mode': 'live'}
    registration = {'slug': platform, 'platform': platform, 'audience_mode': 'owned_broadcast',
                    'account_handle': sample['payload']['account'], 'destination': sample['payload']['destination']}
    arm = {**case['arms'][0], 'channel': platform, 'body': SAMPLE['adapter_payload']['body']}
    (root / 'product.json').write_text(json.dumps(product))
    (root / 'registry.json').write_text(json.dumps({'channels': [registration]}))
    (root / 'copy' / (case['campaign'] + '.json')).write_text(json.dumps([arm]))
    (root / 'channels' / platform).mkdir()
    (root / 'channels' / platform / 'policy.json').write_text(json.dumps(case['policy']))
    cfg = config.Config(root)
    for key, value in SAMPLE['credentials'].items():
        monkeypatch.setenv(key, value)
    lookup, posts = [], []

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
        if request.full_url.endswith(('createSession', 'verify_credentials')):
            lookup.append(request)
            return Reply(sample['authenticated'])
        posts.append(request)
        return Reply(sample['published'])

    monkeypatch.setattr(urllib.request, 'urlopen', respond)

    def run(**kwargs):
        return orchestrate.run_once(cfg, case['campaign'], run_id=case['run_id'],
                                    env={'PROMO_LIVE_AUTHORIZED_' + platform.upper(): 'synthetic-token'}, **kwargs)

    def saved():
        return json.loads((root / 'metrics/runs' / (case['run_id'] + '.json')).read_text())

    return dict(sample=sample, platform=platform, run=run, saved=saved, lookups=lookup, posts=posts,
                path=root / 'metrics/runs' / (case['run_id'] + '.json'))


def test_configured_identity_mismatch_prevents_auth_and_publish(owned, monkeypatch):
    for key, value in owned['sample']['wrong_environment'].items():
        monkeypatch.setenv(key, value)
    result = owned['run']()
    assert result['status'] == 'failed'
    assert owned['lookups'] == [] and owned['posts'] == []
    item = owned['saved']()['items'][0]
    assert item['status'] == 'failed' and item['safe_to_retry'] is True
    assert item['receipt']['status'] == 'not_applied' and item['receipt']['evidence']


def test_authenticated_identity_mismatch_is_not_a_publish_and_can_retry(owned):
    original = owned['sample']['authenticated']
    owned['sample']['authenticated'] = owned['sample']['other_authenticated']
    first = owned['run']()
    assert first['status'] == 'failed' and len(owned['lookups']) == 1 and owned['posts'] == []
    item = owned['saved']()['items'][0]
    assert item['safe_to_retry'] is True and item['receipt']['status'] == 'not_applied'
    assert 'publish' in item['receipt']['evidence'].lower()
    assert 'no provider request' not in item['receipt']['evidence'].lower()
    owned['sample']['authenticated'] = original
    second = owned['run'](resume=True)
    assert second['status'] == 'complete' and len(owned['posts']) == 1
    assert second['items'][0]['idempotency_key'] == item['idempotency_key']


@pytest.mark.parametrize('field', ['other_published', 'incomplete_published'])
def test_post_identity_uncertainty_survives_resume_without_duplicate(owned, field):
    owned['sample']['published'] = owned['sample'][field]
    result = owned['run']()
    assert result['status'] == 'uncertain' and len(owned['posts']) == 1
    item = owned['saved']()['items'][0]
    assert item['status'] == 'uncertain' and item['safe_to_retry'] is False
    assert item['receipt']['status'] == 'uncertain'
    again = owned['run'](resume=True)
    assert again['status'] == 'uncertain' and len(owned['posts']) == 1


def test_matching_identity_completes_once_with_observed_receipt(owned):
    result = owned['run']()
    assert result['status'] == 'complete'
    assert len(owned['lookups']) == 1 and len(owned['posts']) == 1
    item = owned['saved']()['items'][0]
    assert item['payload']['account'] == owned['sample']['payload']['account']
    assert item['receipt']['account'] == owned['sample']['payload']['account']
    body = json.loads(owned['posts'][0].data)
    text = body['record']['text'] if owned['platform'] == 'bluesky' else body['status']
    assert item['payload']['body'] in text
    assert owned['run'](resume=True)['status'] == 'complete' and len(owned['posts']) == 1


def test_incomplete_authenticated_identity_prevents_publication(owned):
    owned['sample']['authenticated'] = {}
    result = owned['run']()
    assert result['status'] == 'failed' and owned['posts'] == []
    assert owned['saved']()['items'][0]['safe_to_retry'] is True


def test_post_fields_cannot_disagree_with_each_other(owned):
    if owned['platform'] == 'bluesky':
        # A session can return the configured handle but a different reviewed DID.
        owned['sample']['authenticated']['did'] = owned['sample']['other_authenticated']['did']
        result = owned['run']()
        assert result['status'] == 'failed' and owned['posts'] == []
    else:
        # A matching account object cannot vouch for a different account's status URL.
        owned['sample']['published']['url'] = owned['sample']['other_published']['url']
        result = owned['run']()
        assert result['status'] == 'uncertain' and len(owned['posts']) == 1
        assert owned['run'](resume=True)['status'] == 'uncertain' and len(owned['posts']) == 1


def test_legacy_payload_uses_frozen_account_without_rewriting_intent(owned):
    authenticated = owned['sample']['authenticated']
    owned['sample']['authenticated'] = {}
    assert owned['run']()['status'] == 'failed'
    record = owned['saved']()
    record['items'][0]['payload'].pop('account')
    record['intent_sha256'] = runs.intent(record)
    owned['path'].write_text(json.dumps(record))
    owned['sample']['authenticated'] = authenticated
    assert owned['run'](resume=True)['status'] == 'complete'
    assert owned['run'](resume=True)['status'] == 'complete' and len(owned['posts']) == 1
    assert owned['saved']()['intent_sha256'] == record['intent_sha256']
