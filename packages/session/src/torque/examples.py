"""Data-only example discovery and launch, shared by the CLI and Python callers."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import string
import subprocess
import sys
import tomllib

SLUG = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
SKIP = {'__pycache__', 'build', 'dist', 'node_modules'}


@dataclass(frozen=True)
class Mode:
    args: tuple
    requires: tuple


@dataclass(frozen=True)
class Example:
    slug: str
    title: str
    description: str
    directory: Path
    entrypoint: Path
    modes: dict


def _text(value, label, limit=300):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid example ' + label)
    return value


def _contained(directory, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Example entrypoint must be a relative contained path')
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory) or not path.is_file() or path.suffix != '.py':
        raise ValueError('Example entrypoint is missing or outside its directory')
    return path


def read_manifest(path):
    path = Path(path).resolve()
    if path.stat().st_size > 32768:
        raise ValueError('Example manifest is too large')
    with path.open('rb') as stream:
        data = tomllib.load(stream)
    if set(data) - {'schema_version','slug','title','description','entrypoint','modes'}:
        raise ValueError('Unknown example manifest field')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Unsupported example manifest schema')
    slug = _text(data.get('slug'), 'slug', 80)
    if not SLUG.fullmatch(slug):
        raise ValueError('Invalid example slug')
    title = _text(data.get('title'), 'title', 100)
    description = _text(data.get('description'), 'description')
    directory = path.parent
    entrypoint = _contained(directory, data.get('entrypoint'))
    profiles = data.get('modes')
    if not isinstance(profiles, dict) or 'run' not in profiles or len(profiles) > 16:
        raise ValueError('Example modes must include run')
    modes = {}
    for name, profile in profiles.items():
        if not SLUG.fullmatch(name) or not isinstance(profile, dict) or set(profile) - {'args','requires'}:
            raise ValueError('Invalid example launch mode')
        args, requires = profile.get('args', []), profile.get('requires', [])
        if not isinstance(args, list) or len(args) > 128 or any(not isinstance(a, str) or '\0' in a or len(a) > 4096 for a in args):
            raise ValueError('Example mode args must be a string array')
        if not isinstance(requires, list) or any(not isinstance(r, str) or not SLUG.fullmatch(r) for r in requires):
            raise ValueError('Example requirements must be capability names')
        for arg in args:
            for _, field, spec, conversion in string.Formatter().parse(arg):
                if field is not None and (field not in ('workspace','output_dir') or spec or conversion):
                    raise ValueError('Unsupported example argument substitution')
        modes[name] = Mode(tuple(args), tuple(requires))
    return Example(slug, title, description, directory, entrypoint, modes)


def default_root():
    module = Path(__file__).resolve()
    packaged = module.parent / '_examples'
    if packaged.is_dir():
        return packaged
    checkout = module.parents[4]
    if module == checkout / 'packages/session/src/torque/examples.py' and (checkout/'examples').is_dir():
        return checkout / 'examples'
    raise RuntimeError('The example catalog is missing from this installation')


def discover(root=None):
    root = Path(root).resolve() if root is not None else default_root()
    if not root.is_dir():
        raise ValueError('Example catalog directory is missing')
    catalog = {}
    for manifest in sorted(root.glob('*/example.toml')):
        if not manifest.resolve().is_relative_to(root):
            raise ValueError('Example manifest is outside the catalog')
        try:
            example = read_manifest(manifest)
        except (OSError, ValueError) as error:
            raise ValueError('Invalid example manifest ' + str(manifest.relative_to(root)) + ': ' + str(error)) from error
        if example.slug in catalog:
            raise ValueError('Duplicate example slug: ' + example.slug)
        catalog[example.slug] = example
    return catalog


def resource_files(example):
    """Build-time resources; local helpers/assets follow their example automatically."""
    for path in sorted(example.directory.rglob('*')):
        relative = path.relative_to(example.directory)
        if any(part.startswith('.') or part in SKIP for part in relative.parts) or path.suffix in ('.pyc','.pyo'):
            continue
        if not path.resolve().is_relative_to(example.directory):
            raise ValueError('Example resource is outside its directory')
        if path.is_symlink() and path.is_dir():
            raise ValueError('Example resource directories cannot be symlinks')
        if path.is_file():
            yield path


def _workspace():
    settings = Path.home() / '.config/torque/settings.json'
    if settings.exists():
        data = json.loads(settings.read_text())
        if not isinstance(data, dict):
            raise ValueError('Invalid Torque workspace settings')
        workspace = data.get('workspace')
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            raise ValueError('Configured Torque workspace must be an absolute path')
        return Path(workspace).resolve()
    return Path.home() / 'torque'


def _requirements(mode, connection_factory):
    if not mode.requires:
        return None
    if connection_factory is None:
        from .protocol import Connection
        connection_factory = Connection
    with connection_factory() as connection:
        state = connection.request('status')
        if not state.get('device', {}).get('ready'):
            raise RuntimeError(state.get('device', {}).get('error') or 'Torque controller is not ready; run torque doctor')
        for capability in mode.requires:
            if capability == 'daemon':
                continue
            raw = connection.request('device', operation='rpc',
                                     arguments={'method':'system.capability', 'args':[capability]})
            try:
                available = json.loads(raw) if isinstance(raw, str) else None
            except ValueError:
                available = None
            if not isinstance(available, dict):
                raise RuntimeError('Example requires controller capability: ' + capability)
        return Path(state['workspace']).resolve()


def run(slug, arguments=(), *, mode='run', root=None, workspace=None, connection_factory=None):
    """Launch a registered example; additional args belong to its own parser."""
    catalog = discover(root)
    if slug not in catalog:
        raise ValueError('Unknown example: ' + str(slug) + '. Run torque example to list available slugs.')
    example = catalog[slug]
    if mode not in example.modes:
        raise ValueError('Example has no mode ' + str(mode) + '; available: ' + ', '.join(example.modes))
    if not isinstance(arguments, (list,tuple)) or any(not isinstance(a,str) or '\0' in a for a in arguments):
        raise ValueError('Example arguments must be strings')
    profile = example.modes[mode]
    help_only = any(arg in ('--help','-h') for arg in arguments)
    if help_only:
        # Registered entrypoints parse help before hardware access. No daemon,
        # workspace creation, or requirement checks are needed to display help.
        base, output, cwd = Path.cwd(), Path.cwd(), example.directory
    else:
        selected_workspace = _requirements(profile, connection_factory)
        base = Path(workspace).expanduser().resolve() if workspace is not None else (selected_workspace or _workspace())
        base = Path(base).expanduser().resolve()
        output = (base/'projects/examples'/example.slug).resolve()
        if not output.is_relative_to(base/'projects'):
            raise ValueError('Example output directory escapes the workspace projects directory')
        output.mkdir(parents=True, exist_ok=True)
        cwd = output
    defaults = [arg.format(workspace=str(base), output_dir=str(output)) for arg in profile.args]
    env = os.environ.copy()
    for name in list(env):
        if name.endswith(('_API_KEY','_TOKEN','_SECRET','_PASSWORD')):
            env.pop(name)
    from .runtime import pinned_python, process_lease
    # Forwarded options can turn a preview into playback. Every non-help child
    # shares admission, including offline scripts; no daemon call is added.
    with process_lease(live=not help_only) as descriptors:
        options = {'pass_fds': descriptors} if descriptors else {}
        return subprocess.call([pinned_python(), str(example.entrypoint), *defaults, *arguments],
                               cwd=cwd, env=env, **options)
