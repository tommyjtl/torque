"""Shared, dependency-free profile and process helpers. Never log credentials."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
KEY_RELATIVE = Path('.config/fx/modular-api-key')


class SetupError(Exception):
    pass


def load_catalog():
    return json.loads((ROOT / 'config/models.json').read_text())


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SetupError('Model discovery was redirected; credentials were not forwarded.')


def discover_models(key):
    """Read visible model IDs without inference; refuse credential redirects."""
    validate_key(key)
    request = urllib.request.Request('https://api.modular.com/v1/models',
                                     headers={'Authorization': 'Bearer ' + key,
                                              'Accept': 'application/json'})
    try:
        opener = urllib.request.build_opener(NoCredentialRedirect())
        with opener.open(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise SetupError('Model discovery response exceeded the size limit.')
        value = json.loads(raw)
        entries = value.get('data') if isinstance(value, dict) else None
        if not isinstance(entries, list) or len(entries) > 2000:
            raise ValueError
        ids = set()
        for entry in entries:
            model = entry.get('id') if isinstance(entry, dict) else None
            if not isinstance(model, str) or not model or len(model) > 1024 or any(ord(c) < 32 for c in model):
                raise ValueError
            ids.add(model)
        return ids
    except urllib.error.HTTPError as error:
        # Do not echo response bodies, headers, or the credential.
        code = error.code
        error.close()
        raise SetupError('Model discovery failed (HTTP ' + str(code) + '); profile not changed.') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SetupError('Cannot reach the Modular Models API; profile not changed.') from None
    except (ValueError, UnicodeError):
        raise SetupError('Unexpected Modular Models API response; profile not changed.') from None


def select_model(catalog, visible, requested=None):
    known = catalog['provider']['model_metadata']
    if requested:
        if requested not in known:
            raise SetupError('Unknown model ID; metadata must be added to config/models.json first.')
        if requested not in visible:
            raise SetupError('The requested model was not returned by the Models API; profile not changed.')
        return requested
    preferred = [catalog['default_model'], *catalog.get('preferred_models', [])]
    for model in dict.fromkeys(preferred):
        if model in visible and model in known:
            return model
    raise SetupError('No preferred compatible model was returned. Check model access or explicitly select a visible known model with --model.')


def validate_key(key):
    if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise SetupError('The key must be one nonempty line without whitespace or control characters.')
    return key


def saved_key(home):
    path = Path(home) / KEY_RELATIVE
    if path.is_symlink():
        raise SetupError('The credential file must not be a symlink.')
    if not path.exists():
        return None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise SetupError('The credential must be an owner-owned regular file with mode 600.')
    text = path.read_text()
    if not text:
        return None
    return validate_key(text.rstrip('\r\n'))


def fx_path(home):
    found = shutil.which('fx')
    if found:
        return found
    local = Path(home) / '.local/bin/fx'
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise SetupError('Refusing to replace a symlink: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run_fx(binary, args, home, key=None, cwd=None, timeout=120):
    env = os.environ.copy()
    env['HOME'] = str(home)
    if key is not None:
        env['MODULAR_API_KEY'] = key
    try:
        result = subprocess.run([binary, *args], env=env, cwd=cwd, text=True,
                                capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SetupError('fx timed out; no automatic API retry was sent.') from None
    except OSError:
        raise SetupError('Could not execute fx.') from None
    # Redact before returning diagnostics to any caller.
    if key:
        result.stdout = result.stdout.replace(key, '[REDACTED]')
        result.stderr = result.stderr.replace(key, '[REDACTED]')
    return result
