"""Download/extract build tools privately. Never install a Debian package."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import apt

ROOT = Path(__file__).resolve().parent


def main():
    cache = apt.Cache()
    seeds = ['gcc-14', 'g++-14', 'binutils', 'libgcc-14-dev', 'libstdc++-14-dev',
             'libc6-dev', 'cmake', 'ninja-build', 'glslc', 'libvulkan-dev', 'spirv-headers']
    selected, pending = {}, list(seeds)
    while pending:
        name = pending.pop().split(':')[0]
        if name in selected:
            continue
        package = cache[name]
        version = package.candidate
        if version is None:
            raise RuntimeError('No candidate: ' + name)
        selected[name] = {'version': version.version, 'bytes': version.size,
                          'sha256': version.record['SHA256']}
        for dependency in version.dependencies:
            if dependency.rawtype not in ('Depends', 'PreDepends'):
                continue
            candidates = [d.name.split(':')[0] for d in dependency.or_dependencies
                          if d.name.split(':')[0] in cache and cache[d.name.split(':')[0]].candidate]
            if not candidates:
                raise RuntimeError('Unresolved dependency: ' + str(dependency))
            pending.append(candidates[0])
    size = sum(v['bytes'] for v in selected.values())
    assert size < 250 * 1024**2, 'Download budget exceeded'
    (ROOT / 'tools-lock.json').write_text(json.dumps({'download_bytes': size, 'packages': selected}, indent=2) + '\n')
    print(json.dumps({'packages': len(selected), 'download_bytes': size}), flush=True)
    archive = ROOT / 'downloads'
    for name, value in sorted(selected.items()):
        subprocess.run(['apt-get', 'download', name + '=' + value['version']], cwd=archive, check=True)
        matches = []
        for path in archive.glob('*.deb'):
            if path.stat().st_size == value['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest() == value['sha256']:
                matches.append(path)
        if len(matches) != 1:
            raise RuntimeError('Downloaded package hash did not match: ' + name)
        subprocess.run(['dpkg-deb', '--extract', str(matches[0]), str(ROOT / 'tools')], check=True)
    binaries = ROOT / 'tools/usr/bin'
    for name in ('lib', 'lib64'):
        path = ROOT / 'tools' / name
        if not path.exists() and not path.is_symlink():
            path.symlink_to('usr/' + name, target_is_directory=True)
    aliases = {'gcc': 'aarch64-linux-gnu-gcc-14', 'cc': 'aarch64-linux-gnu-gcc-14',
               'g++': 'aarch64-linux-gnu-g++-14', 'c++': 'aarch64-linux-gnu-g++-14'}
    for name in ('as', 'ld', 'ar', 'nm', 'ranlib', 'strip', 'objcopy', 'objdump'):
        aliases[name] = 'aarch64-linux-gnu-' + name
    for name, target in aliases.items():
        path = binaries / name
        if not path.exists():
            path.symlink_to(target)
    # Build-tool runtime dependencies may be absent on the host. Keep its libc
    # and loader; expose only private non-libc dependencies to build processes.
    runtime = ROOT / 'tools/runtime-libs'
    runtime.mkdir(exist_ok=True)
    excluded = ('libc.so', 'libm.so', 'libpthread', 'libdl.so', 'librt.so', 'ld-linux', 'libresolv', 'libnss')
    for directory in (ROOT / 'tools/usr/lib/aarch64-linux-gnu', ROOT / 'tools/lib/aarch64-linux-gnu'):
        for path in directory.glob('*.so*'):
            if path.is_file() and not path.name.startswith(excluded):
                target = runtime / path.name
                if not target.exists():
                    target.symlink_to(path.resolve())
    print('PRIVATE_TOOLS_READY', flush=True)


if __name__ == '__main__':
    main()
