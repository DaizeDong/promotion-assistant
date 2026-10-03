"""Generated native storage admission controls; no transport or account operation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import private_storage as storage
from conftest import _real_run


@pytest.fixture
def native_storage(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('promotion_storage_fixtures', root/'tools/make_fixtures.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    commands = []
    def local_git(argv, *args, **kwargs):
        assert isinstance(argv, (list, tuple)) and argv[0] == 'git'
        assert not {'push', 'fetch', 'ls-remote', 'clone'}.intersection(argv)
        commands.append(list(argv))
        return _real_run(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', local_git)
    fixture = generator.make_storage_native_fixture(tmp_path/'generated')
    for key in list(os.environ):
        monkeypatch.delenv(key)
    for key, value in fixture['env'].items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location('promotion_native_guard', root/'guards/tools/data_boundary.py')
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    api = SimpleNamespace(
        GitError=boundary.GitError,
        prove_private_companion=lambda path: boundary.prove_private_companion(path, fixture['receipt']),
        read_private_companion_git=boundary.read_private_companion_git)
    monkeypatch.setattr(storage, '_guard_api', lambda: api, raising=False)
    # Preserve a pre-fix comparison: only legacy gh visibility is synthetic.
    if hasattr(storage, '_run'):
        original = storage._run
        def legacy_metadata(argv):
            if argv[0] == 'gh':
                identity = argv[3].removeprefix('https://github.com/')
                return json.dumps({'nameWithOwner': identity,
                                   'visibility': fixture['visibility'].get(identity, 'UNKNOWN')})
            return original(argv)
        monkeypatch.setattr(storage, '_run', legacy_metadata)
    fixture.update(boundary=boundary, commands=commands)
    return fixture


@pytest.mark.parametrize('unsafe', ['tls-disabled', 'ssh-command', 'effective-public-push'])
def test_native_unsafe_transport_or_rewrite_cannot_authorize_data(native_storage, monkeypatch, unsafe):
    fixture = native_storage
    repo = fixture['repos']['private']
    if unsafe == 'tls-disabled':
        fixture['git'](repo, 'config', 'http.sslVerify', 'false')
    elif unsafe == 'ssh-command':
        fixture['git'](repo, 'remote', 'set-url', 'origin',
                       'git@github.com:example-owner/synthetic-private.git')
        fixture['git'](repo, 'config', 'core.sshCommand', fixture['sentinel'])
    else:
        monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
        monkeypatch.setenv('GIT_CONFIG_KEY_0',
                           'url.https://github.com/example-owner/synthetic-public.git.pushInsteadOf')
        monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'https://github.com/example-owner/synthetic-private.git')
        effective = subprocess.run(['git', '-C', str(repo), 'remote', 'get-url', '--push', 'origin'],
                                   capture_output=True, text=True, check=True)
        assert effective.stdout.strip().endswith('/synthetic-public.git')
    target = repo/'new.json'
    with pytest.raises(ValueError):
        storage.update_text(target, lambda before: ('synthetic state\n', None))
    assert not target.exists()


def test_native_private_and_public_controls(native_storage):
    fixture = native_storage
    private = fixture['repos']['private']/'state.json'
    assert storage.prove(private) == private
    storage.update_text(private, lambda before: ('synthetic state\n', 'saved'))
    assert storage.read_text(private) == 'synthetic state\n'
    with pytest.raises(ValueError):
        storage.prove(fixture['repos']['public']/'state.json')


def test_native_caller_repository_selector_does_not_redirect_proof(native_storage, monkeypatch):
    fixture = native_storage
    caller = fixture['repos']['public']
    monkeypatch.setenv('GIT_DIR', str(caller/'.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(caller))
    target = fixture['repos']['private']/'state.json'
    assert storage.prove(target) == target


def test_native_publication_change_during_transform_preserves_state(native_storage):
    fixture = native_storage
    repo = fixture['repos']['private']
    target = repo/'state.json'
    target.write_text('synthetic retained state\n')
    def transform(before):
        fixture['git'](repo, 'config', 'http.sslVerify', 'false')
        return 'synthetic replacement\n', None
    with pytest.raises(ValueError):
        storage.update_text(target, transform)
    assert target.read_text() == 'synthetic retained state\n'


@pytest.mark.parametrize('placement', ['origin-push', 'second-fetch', 'second-push'])
@pytest.mark.parametrize('visibility', ['PUBLIC', 'UNKNOWN', 'missing'])
def test_native_all_configured_destinations_require_private_receipts(native_storage, placement, visibility):
    fixture = native_storage
    repo = fixture['repos']['private']
    other = 'https://github.com/example-owner/synthetic-secondary.git'
    if placement == 'origin-push':
        fixture['git'](repo, 'config', '--add', 'remote.origin.pushurl', other)
    else:
        fixture['git'](repo, 'remote', 'add', 'secondary',
                       other if placement == 'second-fetch' else
                       'https://github.com/example-owner/synthetic-private.git')
        if placement == 'second-push':
            fixture['git'](repo, 'config', 'remote.secondary.pushurl', other)
    receipt = dict(fixture['visibility'])
    if visibility != 'missing':
        receipt['example-owner/synthetic-secondary'] = visibility
    fixture['receipt'].write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        storage.prove(repo/'state.json')


@pytest.mark.parametrize('url', ['https://example.com/owner/repo', 'file:///synthetic',
                                 'https://user@example.com/owner/repo', 'ext::synthetic-helper'])
def test_native_unproved_remote_routes_are_refused(native_storage, url):
    fixture = native_storage
    repo = fixture['repos']['private']
    fixture['git'](repo, 'remote', 'set-url', 'origin', url)
    with pytest.raises(ValueError):
        storage.prove(repo/'state.json')


@pytest.mark.parametrize('state', ['missing', 'malformed', 'stale', 'future', 'unknown'])
def test_native_missing_or_invalid_receipt_cannot_authorize_storage(native_storage, state):
    fixture = native_storage
    receipt = dict(fixture['visibility'])
    if state == 'missing':
        fixture['receipt'].unlink()
    elif state == 'malformed':
        fixture['receipt'].write_text('{')
    else:
        if state == 'unknown':
            receipt['example-owner/synthetic-private'] = 'UNKNOWN'
        else:
            receipt['_refreshed'] = ('2000' if state == 'stale' else '2100') + '-01-01T00:00:00Z'
        fixture['receipt'].write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        storage.prove(fixture['repos']['private']/'state.json')


def test_native_unborn_history_is_rejected(native_storage):
    fixture = native_storage
    repo = fixture['repos']['private']
    fixture['git'](repo, 'symbolic-ref', 'HEAD', 'refs/heads/synthetic-unborn')
    with pytest.raises(ValueError):
        storage.prove(repo/'state.json')


def test_native_linked_private_and_nested_public_boundaries(native_storage, tmp_path):
    fixture = native_storage
    linked = tmp_path/'linked-private'
    fixture['git'](fixture['repos']['private'], 'worktree', 'add', '--detach', str(linked))
    assert storage.prove(linked/'state.json') == linked/'state.json'
    nested = fixture['repos']['private']/'nested-public'
    fixture['git'](fixture['repos']['public'], 'worktree', 'add', '--detach', str(nested))
    with pytest.raises(ValueError):
        storage.prove(nested/'state.json')


def test_native_config_drift_before_replace_preserves_state(native_storage, monkeypatch):
    fixture = native_storage
    repo = fixture['repos']['private']
    target = repo/'state.json'
    target.write_text('synthetic retained state\n')
    original = storage.os.fsync
    def drift(descriptor):
        original(descriptor)
        fixture['git'](repo, 'config', 'core.autocrlf', 'true')
    monkeypatch.setattr(storage.os, 'fsync', drift)
    with pytest.raises(ValueError, match='destination changed'):
        storage.update_text(target, lambda before: ('synthetic replacement\n', None))
    assert target.read_text() == 'synthetic retained state\n'
