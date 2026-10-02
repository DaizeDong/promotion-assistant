"""Pytest path setup so `from scripts import ...` resolves the skill engine.

The engine lives at skills/promotion-assistant/scripts (a `scripts` package). Putting
skills/promotion-assistant on sys.path mirrors selftest.py's own bootstrap.
"""
import pathlib
import sys
import builtins
import io
import os
import socket
import subprocess
import tempfile
import urllib.request

# Install safety seams before importing the engine or collecting business tests.
for _key in list(os.environ):
    if _key.startswith(('PROMO_', 'PROMOTION_ASSISTANT_')):
        os.environ.pop(_key)


def _no_network(*args, **kwargs):
    raise AssertionError('test attempted an unmocked network operation')


socket.socket.connect = _no_network
socket.create_connection = _no_network
urllib.request.urlopen = _no_network
_real_run = subprocess.run


def _safe_process(argv, *args, **kwargs):
    if isinstance(argv, (list, tuple)) and argv[0] == 'git' and 'check-ignore' in argv:
        return _real_run(argv, *args, **kwargs)
    raise AssertionError('test attempted an unmocked external process')


subprocess.run = _safe_process
_real_open = io.open
_temporary = pathlib.Path(tempfile.gettempdir()).resolve()


def _safe_open(file, *args, **kwargs):
    if isinstance(file, (str, os.PathLike)):
        path = pathlib.Path(file).resolve()
        if path.name in {'product.json', 'registry.json', 'audiences.json', 'consent-ledger.jsonl', 'suppression.csv'}:
            if not path.is_relative_to(_temporary) and 'tests' not in path.parts:
                raise AssertionError('test attempted real runtime data access')
    return _real_open(file, *args, **kwargs)


io.open = _safe_open
builtins.open = _safe_open

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PKG = _ROOT / "skills" / "promotion-assistant"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import pytest


@pytest.fixture(autouse=True)
def synthetic_private_metadata(monkeypatch):
    # The same controls also run against the immutable pre-change source.
    import importlib.util
    if importlib.util.find_spec('scripts.private_storage') is None:
        return
    from scripts import private_storage
    actual_repository = private_storage.repository

    def repository(existing):
        if not existing.is_relative_to(_temporary):
            raise ValueError('test destination must be synthetic temporary storage')
        return next((node for node in (existing, *existing.parents)
                     if (node/'product.json').is_file() or (node/'.git').exists()), existing)

    def metadata(argv):
        if argv[0] == 'git':
            if argv[-1:] == ['remote']:
                return 'origin'
            if argv[-3:] == ['rev-parse', '--verify', 'HEAD']:
                return '1'*40
            if (('get-url' in argv and '--all' in argv and argv[-1] == 'origin')
                    or argv[-3:] == ['remote', 'get-url', 'origin']):
                return 'https://github.com/example/synthetic-promotion-config.git'
            raise AssertionError('unexpected Git metadata query')
        if argv[0] == 'gh' and argv[1:4] == ['repo', 'view', 'example/synthetic-promotion-config']:
            return '{"visibility":"PRIVATE","nameWithOwner":"example/synthetic-promotion-config"}'
        raise AssertionError('unexpected metadata operation')

    monkeypatch.setattr(private_storage, 'repository', repository)
    monkeypatch.setattr(private_storage, '_run', metadata)
    return actual_repository
