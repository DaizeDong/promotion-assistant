"""Generated native storage path controls; checks are local and start no process."""
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

from scripts import private_storage as storage
from conftest import _real_run


@pytest.fixture
def native_storage(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('promotion_storage_fixtures', root/'tools/make_fixtures.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    monkeypatch.setattr(subprocess, 'run', _real_run)
    fixture = generator.make_storage_native_fixture(tmp_path/'generated')
    for key in list(os.environ):
        monkeypatch.delenv(key)
    for key, value in fixture['env'].items():
        monkeypatch.setenv(key, value)
    launched = []
    def refuse(argv, *args, **kwargs):
        launched.append(list(argv))
        raise AssertionError('runtime storage starts no process')
    monkeypatch.setattr(subprocess, 'run', refuse)
    fixture.update(launched=launched)
    return fixture


def test_native_companion_write_and_read_start_no_process(native_storage):
    fixture = native_storage
    target = fixture['repos']['private']/'metrics/events.jsonl'
    assert storage.check(target) == target
    storage.update_text(target, lambda before: ('synthetic state\n', 'saved'))
    assert storage.read_text(target) == 'synthetic state\n'
    assert fixture['launched'] == []


def test_native_destination_outside_any_worktree_is_refused(native_storage, tmp_path):
    loose = tmp_path/'loose'
    loose.mkdir()
    with pytest.raises(ValueError, match='Git companion'):
        storage.update_text(loose/'events.jsonl', lambda before: ('synthetic state\n', None))
    assert not (loose/'events.jsonl').exists()


@pytest.mark.parametrize('where', ['source', 'git-metadata'])
def test_native_source_tree_and_git_metadata_are_refused(native_storage, where):
    target = (storage.ROOT/'metrics/events.jsonl' if where == 'source'
              else native_storage['repos']['private']/'.git/events.jsonl')
    with pytest.raises(ValueError):
        storage.check(target)
    assert not target.exists()


def test_native_caller_repository_selector_does_not_redirect(native_storage, monkeypatch):
    fixture = native_storage
    caller = fixture['repos']['other']
    monkeypatch.setenv('GIT_DIR', str(caller/'.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(caller))
    target = fixture['repos']['private']/'metrics/events.jsonl'
    assert storage.companion_root(target) == fixture['repos']['private']


def test_native_linked_worktree_and_nearest_nested_repository(native_storage, tmp_path, monkeypatch):
    fixture = native_storage
    monkeypatch.setattr(subprocess, 'run', _real_run)
    linked = tmp_path/'linked-private'
    fixture['git'](fixture['repos']['private'], 'worktree', 'add', '--detach', str(linked))
    nested = fixture['repos']['private']/'nested'
    fixture['git'](fixture['repos']['other'], 'worktree', 'add', '--detach', str(nested))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('runtime storage starts no process'))
    assert storage.check(linked/'metrics/events.jsonl') == linked/'metrics/events.jsonl'
    assert storage.companion_root(nested/'metrics/events.jsonl') == nested


def test_native_existing_hardlink_is_refused(native_storage):
    repo = native_storage['repos']['private']
    source = repo/'synthetic-original.txt'
    source.write_text('synthetic retained content')
    target = repo/'metrics/events.jsonl'
    os.link(source, target)
    with pytest.raises(ValueError, match='hardlink'):
        storage.update_text(target, lambda before: ('synthetic replacement\n', None))
    assert source.read_text() == 'synthetic retained content'
