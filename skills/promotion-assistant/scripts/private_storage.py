"""Prove PRIVATE destinations and serialize durable state changes."""
from contextlib import contextmanager
from functools import lru_cache
import importlib.util
import os
from pathlib import Path
import re
import stat
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _guard_api():
    """Load the pinned kit; only the module is cached, never a PRIVATE proof."""
    path = ROOT/'guards/tools/data_boundary.py'
    try:
        spec = importlib.util.spec_from_file_location('_promotion_guard_boundary', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not all(callable(getattr(module, name, None)) for name in (
                'prove_private_companion', 'read_private_companion_git', 'GitError')):
            raise ValueError('pinned Guards kit lacks the supported companion API')
    except (OSError, ImportError, AttributeError) as exc:
        raise ValueError('pinned Guards companion API is unavailable; initialize its submodule') from exc
    return module


def repository(existing):
    for candidate in (existing, *existing.parents):
        if os.path.lexists(candidate/'.git'):
            return candidate
    raise ValueError('runtime data requires a versioned PRIVATE Git companion')


def _file_guard(path):
    """An existing file may not alias another directory entry through a hardlink."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ValueError('runtime file must have exactly one hardlink')
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
        raise ValueError('runtime destination is not a regular file or directory')


def publication_destinations(repo):
    """Return freshly verified PRIVATE repository identities from the shared policy."""
    return _prove(repo)[1].repositories


def _prove(requested):
    path = Path(requested).expanduser()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if any(part.lower() == '.git' or ':' in part or part.endswith((' ', '.')) for part in parts):
        raise ValueError('ambiguous runtime path')
    _file_guard(path)
    path = path.resolve()
    _file_guard(path)
    if path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise ValueError('runtime data cannot be stored in the source tree')
    existing = path
    while not existing.exists():
        existing = existing.parent
    repo = repository(existing.parent if existing.is_file() else existing)
    if ROOT.is_relative_to(repo) or repo.is_relative_to(ROOT) or not path.is_relative_to(repo):
        raise ValueError('runtime data requires a separate companion')
    api = _guard_api()
    try:
        proof = api.prove_private_companion(repo)
        if Path(proof.root) != repo:
            raise ValueError('invalid or nested Git worktree boundary')
        commit = api.read_private_companion_git(proof, 'rev-parse', '--verify', 'HEAD').stdout.strip()
    except api.GitError as exc:
        raise ValueError('PRIVATE companion verification failed; check its receipt and Git configuration') from exc
    if not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', commit):
        raise ValueError('companion must have a committed versioned history')
    return path, proof


def prove(requested):
    """Fresh publication authority is established for each operation, never cached."""
    return _prove(requested)[0]


def _read_current(path, missing=None):
    _file_guard(path)
    try:
        with path.open('r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('runtime input must be a single-link regular file')
            return stream.read()
    except FileNotFoundError:
        return missing


def read_text(path, *, missing=''):
    return _read_current(prove(path), missing)


@contextmanager
def exclusive(path, *, timeout=10):
    """Cooperating writers serialize; stale locks require explicit recovery."""
    target = prove(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name('.'+target.name+'.lock')
    prove(lock)
    deadline = time.monotonic()+timeout
    descriptor = None
    try:
        while descriptor is None:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ValueError('runtime state lock is busy; inspect active writers or a stale lock')
                time.sleep(0.025)
        yield target
    finally:
        if descriptor is not None:
            os.close(descriptor)
            if prove(lock) != lock:
                raise ValueError('runtime lock destination changed')
            lock.unlink()


def _replace(path, payload):
    if not isinstance(payload, str):
        raise ValueError('runtime state transform must return text')
    temporary = None
    try:
        checked, before = _prove(path)
        if checked != path:
            raise ValueError('runtime state destination changed')
        descriptor, name = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        checked, after = _prove(path)
        if (checked != path or (after.root, after.repositories, after.signature) !=
                (before.root, before.repositories, before.signature)):
            raise ValueError('runtime state destination changed')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            _file_guard(temporary)
            temporary.unlink(missing_ok=True)


def update_text(path, transform):
    """Lock read/transform/replace; the callback returns (new_text, result)."""
    with exclusive(path) as checked:
        before = _read_current(checked)
        after, result = transform(before)
        if after != before:
            _replace(checked, after)
        return result
