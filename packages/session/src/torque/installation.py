"""Read-only parity check for the Python code in a managed runtime bundle."""
from pathlib import Path


def verify_python_sources(release, *, installed=None):
    source = Path(release) / 'packages/session/src/torque'
    target = Path(installed) if installed else Path(__file__).parent
    if not source.is_dir():
        raise RuntimeError('Managed Python source tree is missing')
    expected = {p.relative_to(source) for p in source.rglob('*.py') if '__pycache__' not in p.parts}
    actual = {p.relative_to(target) for p in target.rglob('*.py')
              if '__pycache__' not in p.parts and '_examples' not in p.relative_to(target).parts}
    bad = sorted(str(name) for name in expected | actual if name not in expected or name not in actual or
                 (source / name).read_bytes() != (target / name).read_bytes())
    if bad:
        raise RuntimeError('Installed Python modules differ from source: ' + ', '.join(bad[:20]))
    return {'matched': True, 'modules': len(expected)}
