"""Generated selected-resource and scheduling artifact regressions."""
import json
from pathlib import Path
import pytest
from scripts import config, capabilities, providers, private_storage
from test_review_runs import case, SAMPLE, live, authorized


def configure_resources(root, values):
    (root / 'secrets').mkdir(exist_ok=True)
    (root / 'secrets/runtime.env').write_text(''.join(k+'='+v+'\n' for k, v in values.items()))


def test_selected_resources_ignore_ambient_other_product(case, monkeypatch):
    cfg = config.Config(case['root'])
    configure_resources(case['root'], SAMPLE['credentials'])
    monkeypatch.setenv('PROMO_DISCORD_BOT_TOKEN', 'synthetic-other-product')
    assert cfg.runtime_env() == SAMPLE['credentials']
    with providers.runtime_environment(cfg.runtime_env()):
        assert providers._environment()['PROMO_DISCORD_BOT_TOKEN'] == SAMPLE['credentials']['PROMO_DISCORD_BOT_TOKEN']
    assert providers._environment()['PROMO_DISCORD_BOT_TOKEN'] == 'synthetic-other-product'


def test_missing_selected_credentials_never_inherit_ambient(case, monkeypatch):
    for key, value in SAMPLE['credentials'].items():
        monkeypatch.setenv(key, value)
    cfg = config.Config(case['root'])
    assert cfg.runtime_env() == {}
    with providers.runtime_environment(cfg.runtime_env()):
        assert providers._environment() == {}


@pytest.mark.parametrize('field', ['schema_version', 'name'])
def test_doctor_rejects_missing_product_field_for_manual_channel(case, field):
    product = dict(case['product'])
    product.pop(field, None)
    (case['root'] / 'product.json').write_text(json.dumps(product))
    (case['root'] / 'registry.json').write_text(json.dumps({'schema_version': 1, 'channels': [{'slug': 'hackernews', 'platform': 'hackernews'}]}))
    result = capabilities.doctor(config.Config(case['root']))
    assert result['status'] == 'not_ready'
    assert any(field in row['name'] and not row['ok'] for row in result['checks'])


def test_runtime_mapping_rejects_authorization_token(case):
    configure_resources(case['root'], {'PROMO_LIVE_AUTHORIZED_EMAIL': 'synthetic'})
    with pytest.raises(config.ConfigError):
        config.Config(case['root']).runtime_env()


def test_schedule_receipt_and_staging_are_owned(case):
    root = case['root']
    target = root / 'metrics/schedule-requests' / ('a'*64+'.json')
    private_storage.update_text(target, lambda before: ('{}', None))
    assert target.read_text() == '{}'
    assert [p.name for p in target.parent.iterdir()] == [target.name]
    with pytest.raises(ValueError, match='owner'):
        private_storage.update_text(root / 'metrics/unknown/new.json', lambda before: ('{}', None))
    assert not (root / 'metrics/unknown').exists()


def test_same_process_config_switch_uses_selected_root_resources(case, monkeypatch):
    root_a = case['root']
    root_b = root_a.parent / 'synthetic-second-product'
    root_b.mkdir()
    for name in ('product.json', 'registry.json'):
        (root_b / name).write_bytes((root_a / name).read_bytes())
    resources_a = dict(SAMPLE['credentials'])
    resources_b = {**resources_a, 'PROMO_DISCORD_BOT_TOKEN': 'synthetic-second-token'}
    configure_resources(root_a, resources_a)
    configure_resources(root_b, resources_b)
    monkeypatch.setenv('PROMO_CONFIG_DIR', str(root_a))
    assert config.load().runtime_env() == resources_a
    monkeypatch.setenv('PROMO_CONFIG_DIR', str(root_b))
    selected = config.load()
    assert selected.root == root_b and selected.runtime_env() == resources_b
    assert config.load(str(root_a)).runtime_env() == resources_a


def test_doctor_rejects_missing_registry_schema(case):
    (case['root'] / 'registry.json').write_text(json.dumps({'channels': [{'slug': 'hackernews', 'platform': 'hackernews'}]}))
    result = capabilities.doctor(config.Config(case['root']))
    assert result['status'] == 'not_ready'
    assert any('registry.schema_version' in row['name'] and not row['ok'] for row in result['checks'])


@pytest.mark.parametrize('malformed', [
    'PROMO_DISCORD_BOT_TOKEN=synthetic-first\nPROMO_DISCORD_BOT_TOKEN=synthetic-second\n',
    'PROMO_DISCORD_BOT_TOKEN="synthetic-unclosed\n',
])
def test_invalid_runtime_resources_remain_retryable_before_provider_intent(case, monkeypatch, malformed):
    calls = live(case, monkeypatch)
    configure_resources(case['root'], SAMPLE['credentials'])
    resources = case['root'] / 'secrets/runtime.env'
    resources.write_text(malformed)
    result = authorized(case)
    assert calls == []
    assert all(item['status'] == 'failed' and item['safe_to_retry'] for item in result['items'])
    assert all(item['receipt']['status'] == 'not_applied' for item in result['items'])
    path = case['root'] / 'metrics/runs' / (case['run_id']+'.json')
    saved = json.loads(path.read_text())
    assert all(item['status'] == 'failed' and item['safe_to_retry'] for item in saved['items'])
    configure_resources(case['root'], SAMPLE['credentials'])
    resumed = authorized(case, resume=True)
    assert resumed['status'] == 'complete' and len(calls) == len(result['items'])
    assert [item['idempotency_key'] for item in resumed['items']] == [item['idempotency_key'] for item in result['items']]
