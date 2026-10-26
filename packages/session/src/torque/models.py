"""Modular discovery and explicit profiles. Credentials never enter caches."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time
import urllib.error
import urllib.request

BASE_URL = 'https://api.modular.com/v1'
TTL = 3600
EXPERIMENTAL_BUDGET = 16384
FIELDS = {'contextWindow', 'maxOutputTokens', 'supportsToolUse', 'supportsVision'}


def private_json(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Configuration/cache must be an owner-only regular file')
    if info.st_size > 2 * 1024 * 1024:
        raise ValueError('Configuration/cache is too large')
    return json.loads(path.read_text())


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Configuration/cache directory must be owner-only')
    if path.exists() or path.is_symlink():
        private_json(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def model_id(value):
    if not isinstance(value, str) or not 0 < len(value) <= 1024 or any(not c.isprintable() or c.isspace() for c in value):
        raise ValueError('Invalid model ID')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Model discovery redirected; credentials were not forwarded')


def discover(key):
    request = urllib.request.Request(BASE_URL + '/models', headers={
        'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError
        value = json.loads(raw)
        entries = value.get('data') if isinstance(value, dict) else None
        if not isinstance(entries, list) or len(entries) > 2000:
            raise ValueError
        ids = sorted({model_id(entry['id']) for entry in entries})
        if any(key in name for name in ids):
            raise ValueError
        return ids
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        raise RuntimeError(f'Model discovery failed (HTTP {code})') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError('Cannot reach Modular Models API') from None
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise RuntimeError('Invalid Modular Models API response') from None


def metadata(value):
    result = {}
    for key, item in value.items():
        parts = key.split('_')
        key = parts[0] + ''.join(part.title() for part in parts[1:])
        if key not in FIELDS:
            continue
        if key.startswith('supports'):
            if type(item) is not bool:
                raise ValueError('Invalid model capability metadata')
        elif type(item) is not int or not 1 <= item <= 100_000_000:
            raise ValueError('Invalid model token metadata')
        result[key] = item
    return result


class ModelCatalog:
    def __init__(self, config, *, cache=None, fetch=discover, clock=time.time):
        self.config = config
        self.path = Path(cache) if cache else Path.home() / '.cache/torque/model-catalog/catalog.json'
        self.fetch, self.clock = fetch, clock

    def credential(self):
        path = Path(self.config['key_file'])
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384:
            raise RuntimeError('Credential must be an owner-only regular file')
        key = path.read_text().strip()
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise RuntimeError('Credential unavailable or invalid')
        stamp = [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size]
        generation = hashlib.sha256((BASE_URL + json.dumps(stamp)).encode()).hexdigest()
        return key, generation

    def curated(self):
        path = Path(self.config['release_root']) / 'config/models.json'
        if path.exists():
            catalog = json.loads(path.read_text())['provider']['model_metadata']
        else:
            catalog = {}
        return {name: metadata(value) for name, value in catalog.items()}

    def profile(self, name):
        model_id(name)
        known = self.curated()
        profile = known.get(name, {}).copy()
        profile.update(metadata(self.config.get('models', {}).get(name, {})))
        origin = self.config.get('model_profiles', {}).get(name, {}).get('source')
        experimental = origin == 'experimental' or name not in known and name not in self.config.get('models', {})
        if experimental:
            profile = {'contextWindow': EXPERIMENTAL_BUDGET, 'maxOutputTokens': 2048,
                       'supportsVision': False, **profile}
        return {'id': name, 'metadata': profile, 'source': 'experimental' if experimental else 'configured',
                'tool_support': 'unverified' if 'supportsToolUse' not in profile else
                                'yes' if profile['supportsToolUse'] else 'no',
                'eligible': profile.get('supportsToolUse') is not False}

    def load(self, generation):
        try:
            cache = private_json(self.path)
            if (cache.get('schema') != 1 or cache.get('base_url') != BASE_URL or
                    cache.get('generation') != generation or
                    not isinstance(cache.get('retrieved_at'), (int, float)) or
                    not math.isfinite(cache['retrieved_at']) or
                    not isinstance(cache.get('checks', {}), dict) or
                    not isinstance(cache.get('ids'), list) or len(cache['ids']) > 2000):
                return None
            for name in cache['ids']:
                model_id(name)
            return cache
        except (OSError, ValueError, TypeError):
            return None

    def listing(self, *, refresh=False):
        error = None
        cache = None
        source = 'configured'
        try:
            key, generation = self.credential()
            cache = self.load(generation)
            if refresh or not cache or not 0 <= self.clock() - cache['retrieved_at'] < TTL:
                try:
                    ids = self.fetch(key)
                    if not isinstance(ids, list) or len(ids) > 2000 or any(key in model_id(name) for name in ids):
                        raise ValueError('Invalid model discovery IDs')
                    cache = {'schema': 1, 'base_url': BASE_URL, 'generation': generation,
                             'retrieved_at': self.clock(), 'ids': ids,
                             'checks': cache.get('checks', {}) if cache else {}}
                    save_json(self.path, cache)
                    source = 'online'
                except (RuntimeError, OSError, ValueError) as failure:
                    error = str(failure).replace(key, '[REDACTED]')
                    source = 'stale' if cache else 'configured'
            else:
                source = 'cache'
        except (RuntimeError, OSError, ValueError):
            error = 'Credential unavailable or invalid; discovery not performed'
        visible = set(cache['ids']) if cache else set()
        names = visible | set(self.curated()) | set(self.config.get('models', {})) | {self.config['model']}
        rows = []
        total, size = len(names), 0
        for name in sorted(names, key=lambda name: (name != self.config['model'], name)):
            profile = self.profile(name)
            row = {**profile, 'selected': name == self.config['model'],
                   'discovered': name in visible if cache else None,
                   'verification': self.check(name, cache)}
            size += len(json.dumps(row).encode())
            if size > 100000:
                break
            rows.append(row)
        return {'model': self.config['model'], 'models': rows, 'source': source, 'total': total,
                'truncated': len(rows) < total,
                'retrieved_at': cache['retrieved_at'] if cache else None,
                'stale': source in ('stale', 'configured'), 'error': error,
                'ok': not error if refresh else True}

    def signature(self, name):
        identity = {'profile': self.profile(name), 'engine': 'libfx@0.0.14', 'probe_schema': 1}
        worker = Path(self.config['release_root']) / 'engines/fx/worker.mjs'
        if worker.exists():
            identity['worker_sha256'] = hashlib.sha256(worker.read_bytes()).hexdigest()
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def check(self, name, cache):
        result = (cache or {}).get('checks', {}).get(name)
        if not isinstance(result, dict) or type(result.get('passed')) is not bool or result.get('signature') != self.signature(name):
            return None
        return result

    def record(self, name, result, *, generation=None):
        _, current = self.credential()
        if generation is not None and generation != current:
            return
        generation = current
        cache = self.load(generation)
        if cache:
            cache.setdefault('checks', {})[name] = {**result, 'signature': self.signature(name), 'checked_at': self.clock()}
            save_json(self.path, cache)

    def selectable(self, name):
        model_id(name)
        listing = self.listing()
        selected = next((row for row in listing['models'] if row['id'] == name), None)
        if selected is None and listing['truncated']:
            _, generation = self.credential()
            cache = self.load(generation)
            if cache and name in cache['ids']:
                selected = {**self.profile(name), 'discovered': True}
        if not selected or selected['discovered'] is not True:
            raise ValueError('Model was not returned by discovery; refresh the model list')
        if not selected['eligible']:
            raise ValueError('Model is configured as incompatible with agent tool use')
        return selected, listing
