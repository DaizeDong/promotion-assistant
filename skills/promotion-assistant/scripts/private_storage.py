"""Prove PRIVATE destinations and serialize durable state changes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]


def _run(argv):
    try:
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith('GIT_') and key.upper() != 'GH_HOST'}
        env['GIT_OPTIONAL_LOCKS'] = '0'
        if argv[0] == 'gh':
            if len(argv) < 4 or argv[:3] != ['gh', 'repo', 'view']:
                raise ValueError('unsupported companion visibility lookup')
            # Bind the actual subprocess, including calls from unqualified metadata seams.
            identity = _remote_identity('https://github.com/'+argv[3])
            argv = [*argv[:3], 'https://github.com/'+identity, *argv[4:]]
            env['GH_HOST'] = 'github.com'
        result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                                errors='strict', timeout=20, env=env)
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise ValueError('PRIVATE companion verification unavailable: '+argv[0]) from exc
    if result.returncode:
        raise ValueError('PRIVATE companion verification failed: '+argv[0])
    return result.stdout.strip()


def _git(repo, *args):
    return _run(['git', '-c', 'core.fsmonitor=false', '-C', str(repo), *args])


def repository(existing):
    for candidate in (existing, *existing.parents):
        if os.path.lexists(candidate/'.git'):
            root = Path(_git(candidate, 'rev-parse', '--show-toplevel')).resolve()
            if root != candidate:
                raise ValueError('invalid or nested Git worktree boundary')
            return root
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


def _remote_identity(remote):
    if remote.startswith(('https://', 'ssh://')):
        value = urlsplit(remote)
        if (value.password or value.query or value.fragment or value.port is not None
                or (value.scheme == 'https' and value.username is not None)
                or (value.scheme == 'ssh' and value.username not in (None, 'git'))):
            raise ValueError('unsupported companion publication URL')
        host, name = value.hostname, value.path.lstrip('/')
    else:
        match = re.fullmatch(r'(?:[^@/:\s]+@)?([^/:\s]+):([^\s]+)', remote)
        if not match:
            raise ValueError('unverifiable companion publication URL')
        host, name = match.groups()
    if host != 'github.com':
        raise ValueError('companion publication host must identify GitHub')
    name = name.removesuffix('.git')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
        raise ValueError('invalid companion repository identity')
    return name


def publication_destinations(repo):
    """Git expands URL rewrites; every effective fetch and push URL must be PRIVATE."""
    remotes = _git(repo, 'remote').splitlines()
    if 'origin' not in remotes or len(remotes) != len(set(remotes)):
        raise ValueError('PRIVATE companion requires an origin and unambiguous remotes')
    accepted = []
    for remote in sorted(remotes):
        if not remote or remote.startswith('-') or any(char.isspace() for char in remote):
            raise ValueError('invalid companion remote name')
        for direction in ('fetch', 'push'):
            flags = ['--push'] if direction == 'push' else []
            urls = _git(repo, 'remote', 'get-url', *flags, '--all', remote).splitlines()
            if not urls:
                raise ValueError('companion publication URL is missing')
            for url in urls:
                identity = _remote_identity(url)
                answer = json.loads(_run(['gh', 'repo', 'view', identity,
                                          '--json', 'nameWithOwner,visibility']))
                if (not isinstance(answer, dict) or answer.get('visibility') != 'PRIVATE'
                        or not isinstance(answer.get('nameWithOwner'), str)
                        or answer['nameWithOwner'].lower() != identity.lower()):
                    raise ValueError('companion publication destination is PUBLIC or unknown')
                accepted.append((remote, direction, identity))
    return tuple(accepted)


def prove(requested):
    """Fresh publication authority is established for each operation, never cached."""
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
    commit = _git(repo, 'rev-parse', '--verify', 'HEAD')
    if not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', commit):
        raise ValueError('companion must have a committed versioned history')
    publication_destinations(repo)
    return path


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
        checked = prove(path)
        if checked != path:
            raise ValueError('runtime state destination changed')
        descriptor, name = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if prove(path) != path:
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
