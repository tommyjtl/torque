#!/usr/bin/env python3
"""Configure stock fx for Modular Cloud without putting keys in argv or JSON."""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request

from fx_common import (ROOT, KEY_RELATIVE, SetupError, atomic_write, fx_path,
                       discover_models, load_catalog, saved_key, select_model, validate_key)

START = '# >>> fx-modular-cloud-uno-q >>>'
END = '# <<< fx-modular-cloud-uno-q <<<'
BLOCK = f'''{START}
if [ -r "$HOME/.config/fx/modular-env.sh" ]; then
    . "$HOME/.config/fx/modular-env.sh"
fi
{END}
'''
HOOK = b'''# Managed by fx-modular-cloud-uno-q. The key is plain text, never shell code.
if [ -s "$HOME/.config/fx/modular-api-key" ]; then
    IFS= read -r MODULAR_API_KEY < "$HOME/.config/fx/modular-api-key" || :
    export MODULAR_API_KEY
fi
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) PATH="$HOME/.local/bin:$PATH" ;;
esac
export PATH
'''


def managed_hook(text):
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise SetupError('Unexpected shell hook markers; review the startup file before rerunning.')
    if START in text:
        text = re.sub(re.escape(START) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.S)
    # Prepend before Debian's noninteractive .bashrc early return.
    return BLOCK + text


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SetupError('Duplicate JSON fields in settings; resolve them before setup.')
        result[key] = value
    return result


def configure(home, catalog, key, model, available=None):
    """Merge owned fields, back up changed non-secret files, then write atomically."""
    home = Path(home)
    validate_key(key)
    if model not in catalog['provider']['model_metadata']:
        raise SetupError('Unknown model ID; choose an ID listed in config/models.json.')
    if available is not None and model not in available:
        raise SetupError('Selected model is not visible; profile not changed.')
    settings = home / '.fx/settings.json'
    if settings.is_symlink():
        raise SetupError('settings.json is a symlink; resolve its destination explicitly before setup.')
    try:
        data = json.loads(settings.read_text(), object_pairs_hook=unique_object) if settings.exists() else {}
    except (ValueError, UnicodeError):
        raise SetupError('settings.json is not valid UTF-8 JSON; it was not changed.') from None
    if not isinstance(data, dict):
        raise SetupError('settings.json must contain an object.')
    for field in ['providers', 'models']:
        if not isinstance(data.get(field, {}), dict):
            raise SetupError('Unexpected settings schema for ' + field)
    providers = data.setdefault('providers', {})
    previous = providers.get('modular', {})
    if not isinstance(previous, dict):
        raise SetupError('The existing modular provider must contain an object.')
    provider = previous.copy()
    old_metadata = provider.get('model_metadata', {})
    if not isinstance(old_metadata, dict):
        raise SetupError('Existing model_metadata must contain an object.')
    known = catalog['provider']['model_metadata']
    # Prune only entries this catalog owns. Preserve user-defined model metadata.
    metadata = {name: value for name, value in old_metadata.items()
                if available is None or name not in known or name in available}
    for name, values in known.items():
        if available is not None and name not in available:
            continue
        existing = metadata.get(name, {})
        if not isinstance(existing, dict):
            raise SetupError('Unexpected existing model metadata.')
        metadata[name] = dict(existing, **values)
    provider.update(catalog['provider'])
    provider['model_metadata'] = metadata
    providers['modular'] = provider
    data.setdefault('models', {})['modular'] = model
    data['provider'] = 'modular'
    encoded = (json.dumps(data, indent=2) + '\n').encode()
    if key.encode() in encoded:
        raise SetupError('A credential is present in settings; remove it privately before setup.')

    login = next((home / name for name in ['.bash_profile', '.bash_login', '.profile']
                  if (home / name).exists()), home / '.profile')
    planned = {settings: encoded, home / '.config/fx/modular-env.sh': HOOK}
    for path in [home / '.bashrc', login]:
        if path.is_symlink():
            raise SetupError('Refusing to edit a shell startup symlink: ' + str(path))
        planned[path] = managed_hook(path.read_text() if path.exists() else '').encode()
    changed = {p: content for p, content in planned.items()
               if not p.exists() or p.read_bytes() != content}
    key_path = home / KEY_RELATIVE
    if key_path.is_symlink():
        raise SetupError('The credential file must not be a symlink.')
    if key_path.exists():
        saved_key(home)  # Check ownership and permissions before replacing it.
    private = home / '.config/fx'
    if private.is_symlink():
        raise SetupError('The private credential directory must not be a symlink.')
    backup = None
    if changed:
        backup_root = home / '.fx/backups'
        backup_root.mkdir(parents=True, exist_ok=True)
        prefix = 'uno-q-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
        backup = Path(tempfile.mkdtemp(prefix=prefix, dir=backup_root))
        absent = []
        for path in changed:
            relative = path.relative_to(home)
            if path.exists():
                destination = backup / relative
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(path, destination)
                destination.chmod(0o600)
            else:
                absent.append(str(relative))
        atomic_write(backup / 'originally-absent.json', (json.dumps(absent) + '\n').encode())
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    atomic_write(key_path, (key + '\n').encode())
    for path, content in changed.items():
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        if path in [settings, home / '.config/fx/modular-env.sh']:
            mode = 0o600
        atomic_write(path, content, mode)
    (home / '.fx').chmod(0o700)
    settings.chmod(0o600)
    return backup


def ensure_board():
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        raise SetupError('Run setup on the UNO Q: Linux aarch64 is required.')
    path = Path('/sys/firmware/devicetree/base/compatible')
    if not path.exists() or b'arduino,imola' not in path.read_bytes().split(b'\0'):
        raise SetupError('This device does not identify as an Arduino UNO Q (arduino,imola).')


def ensure_fx(home):
    binary = fx_path(home)
    if binary is None:
        print('Installing official fx v0.0.14 in ~/.local/bin; no other software is upgraded.', flush=True)
        with urllib.request.urlopen('https://fx.sh/setup.sh', timeout=30) as response:
            installer = response.read(1024 * 1024)
        with tempfile.TemporaryDirectory(prefix='fx-installer-') as tmp:
            path = Path(tmp) / 'setup.sh'
            path.write_bytes(installer)
            env = os.environ.copy()
            env.pop('MODULAR_API_KEY', None)
            env['HOME'] = str(home)
            env['FX_INSTALL_DIR'] = str(home / '.local/bin')
            # The vendor installer skips startup-file edits when its bin dir
            # is already on PATH. Our backed-up managed hook owns that change.
            env['PATH'] = str(home / '.local/bin') + os.pathsep + env.get('PATH', '')
            result = subprocess.run(['bash', str(path), 'v0.0.14'], env=env, capture_output=True, timeout=180)
        if result.returncode:
            raise SetupError('Official fx installation failed. See https://fx.sh/docs/getting-started/installation')
        binary = fx_path(home)
    if binary is None:
        raise SetupError('fx was not found after installation.')
    result = subprocess.run([binary, '--version'], text=True, capture_output=True, timeout=15)
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', result.stdout)
    if result.returncode or not match or tuple(map(int, match.groups())) < (0, 0, 14):
        raise SetupError('fx v0.0.14 or newer is required. Existing fx was not upgraded or modified.')
    print('Using fx ' + match.group(0), flush=True)
    return binary


def obtain_key(home, replace):
    if not replace:
        if os.environ.get('MODULAR_API_KEY'):
            return validate_key(os.environ['MODULAR_API_KEY'])
        existing = saved_key(home)
        if existing:
            return existing
    try:
        with open('/dev/tty', 'r+') as terminal:
            return validate_key(getpass.getpass('Modular API key (hidden): ', stream=terminal))
    except OSError:
        raise SetupError('No terminal for private key entry. Use an interactive SSH session or an existing private credential file.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', help='Exact model ID from config/models.json')
    parser.add_argument('--replace-key', action='store_true', help='Prompt privately for a replacement key')
    parser.add_argument('--no-verify', action='store_true', help='Skip inference tests; Models API discovery still runs')
    args = parser.parse_args()
    ensure_board()
    home = Path.home()
    catalog = load_catalog()
    if args.model and args.model not in catalog['provider']['model_metadata']:
        raise SetupError('Unknown model ID; see config/models.json.')
    key = obtain_key(home, args.replace_key)
    print('Discovering model IDs using the Modular Models API (no inference).', flush=True)
    visible = discover_models(key)
    model = select_model(catalog, visible, args.model)
    known = set(catalog['provider']['model_metadata'])
    print('Adding ' + str(len(known & visible)) + ' known visible models; ' +
          str(len(known - visible)) + ' catalog entries are not returned by this key.', flush=True)
    if visible - known:
        print(str(len(visible - known)) + ' additional IDs have no verified local metadata and will not be added automatically.', flush=True)
    ensure_fx(home)
    backup = configure(home, catalog, key, model, available=visible)
    print('Configured modular / ' + model, flush=True)
    print('Credentials saved owner-only, outside settings and the repository.', flush=True)
    print('Backup: ' + str(backup) if backup else 'Configuration already current; no duplicate hooks added.', flush=True)
    (ROOT / 'projects').mkdir(exist_ok=True)
    if not args.no_verify:
        print('Verifying with two small fx requests (uses API credits).', flush=True)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify-fx.py')])
        if result.returncode:
            raise SetupError('Configuration saved, but verification failed. See docs/model-compatibility.md.')
    else:
        print('Inference verification skipped; model visibility was checked, but generation/tool use has not been verified by this run.', flush=True)
    print('Open a fresh SSH login, then run:', flush=True)
    import shlex
    print('  cd ' + shlex.quote(str(ROOT)) + ' && fx', flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SetupError, KeyboardInterrupt, EOFError) as error:
        print('Setup: ' + (str(error) or 'cancelled'), file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print('Setup failed (' + type(error).__name__ + '); credential values are suppressed.', file=sys.stderr)
        sys.exit(1)
