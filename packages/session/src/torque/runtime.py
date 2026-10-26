"""Private update records and inherited process leases; no privileged actions."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

UPDATE_ID = re.compile(r'[0-9a-f]{32}\Z')
RELEASE_ID = re.compile(r'\d+\.\d+\.\d+-[0-9a-f]{12}\Z')


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('Expected a private owned directory: ' + str(path))
    return path


def read_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError('Expected a private owned record: ' + str(path))
        return json.load(stream)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class Lock:
    def __init__(self, path, *, shared=False):
        self.path, self.shared, self.fd = Path(path), shared, None

    def __enter__(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_mode & 0o077 or info.st_nlink != 1):
                raise RuntimeError('Unsafe update lock: ' + str(self.path))
            try:
                fcntl.flock(fd, (fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A Torque update or managed program is using the runtime') from None
            self.fd = fd
            return self
        except BaseException:
            os.close(fd)
            raise

    def __exit__(self, *_):
        # Closing, rather than LOCK_UN, preserves the inherited child's lease.
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Store:
    def __init__(self, state):
        self.root = private_dir(Path(state)/'updates')
        self.records = private_dir(self.root/'transactions')
        self.leases = private_dir(self.root/'release-use')

    def lock(self):
        return Lock(self.root/'deploy.lock')

    def use(self, *, shared=False):
        return Lock(self.root/'programs.lock', shared=shared)

    def release_use(self, release):
        if not RELEASE_ID.fullmatch(release):
            raise ValueError('Invalid release identity')
        return Lock(self.leases/(release+'.lock'), shared=True)

    def path(self, update_id):
        if not isinstance(update_id, str) or not UPDATE_ID.fullmatch(update_id):
            raise ValueError('Invalid update identity')
        return self.records/(update_id+'.json')

    def get(self, update_id):
        value = read_json(self.path(update_id))
        if not isinstance(value,dict) or value.get('id') != update_id or not isinstance(value.get('phase'),str):
            raise RuntimeError('Update record identity mismatch')
        return value

    def save(self, record):
        write_json(self.path(record['id']), record)

    def pending(self):
        path = self.root/'active.json'
        if not path.exists() and not path.is_symlink():
            return None
        pointer = read_json(path)
        if not isinstance(pointer,dict) or 'id' not in pointer:
            raise RuntimeError('Malformed active update pointer')
        return self.get(pointer['id'])

    def activate(self, update_id):
        previous = self.pending()
        if previous and previous['id'] != update_id:
            raise RuntimeError('Another update needs recovery first')
        self.get(update_id)
        write_json(self.root/'active.json', {'id': update_id})

    def clear(self, update_id):
        current = self.pending()
        if current and current['id'] != update_id:
            raise RuntimeError('Cannot release another update transaction')
        (self.root/'active.json').unlink(missing_ok=True)
        sync_dir(self.root)


def pinned_python():
    # Resolve the venv directory, never its interpreter's /usr/bin symlink.
    release = managed_release()
    if release is None:
        return sys.executable
    return str(release/'runtime/python/bin/python')


def managed_release(path=None):
    path = Path(path or __file__).resolve()
    for parent in path.parents:
        if (RELEASE_ID.fullmatch(parent.name) and parent.parent.name == 'releases' and
                (parent/'release.json').is_file()):
            return parent
    return None


@contextmanager
def process_lease(*, live=False, release=None, settings=None):
    """Hold flock descriptions through child exec, even if its frontend dies."""
    release = managed_release() if release is None else release
    if release is None:
        yield ()
        return
    if settings is None:
        settings = json.loads((Path.home()/'.config/torque/settings.json').read_text())
    store = Store(settings['state_dir'])
    with store.release_use(Path(release).name) as resource:
        if live:
            with store.use(shared=True) as program:
                if store.pending():
                    raise RuntimeError('A runtime update needs recovery; new programs are fenced')
                yield (resource.fd, program.fd)
        else:
            yield (resource.fd,)
