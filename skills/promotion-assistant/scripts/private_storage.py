"""Check DATA destination paths and serialize durable state changes.

These are filesystem checks only and start no process: the destination must sit in a Git
worktree that is separate from this public source tree, with no Git metadata, ambiguous
components or hardlinked files. Repository visibility is not checked at runtime.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import uuid
import time

ROOT = Path(__file__).resolve().parents[3]


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


def companion_root(repo):
    """Return the separate Git worktree that holds ``repo``'s runtime DATA."""
    return _check(repo)[1]


def _check(requested):
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
    return path, repo


def check(requested):
    """Return the resolved destination once the local path checks pass."""
    return _check(requested)[0]


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


def authorize(path):
    """Path-only admission for a DATA write."""
    return check(path)


def read_text(path, *, missing=''):
    return _read_current(check(path), missing)


@contextmanager
def exclusive(path, *, timeout=10):
    """Cooperating writers serialize; stale locks require explicit recovery."""
    target = authorize(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name('.'+target.name+'.lock')
    authorize(lock)
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
            if check(lock) != lock:
                raise ValueError('runtime lock destination changed')
            lock.unlink()


def _replace(path, payload):
    if not isinstance(payload, str):
        raise ValueError('runtime state transform must return text')
    temporary = None
    try:
        if check(path) != path:
            raise ValueError('runtime state destination changed')
        temporary = authorize(path.with_name('.'+path.name+'-'+uuid.uuid4().hex))
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if check(path) != path:
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
