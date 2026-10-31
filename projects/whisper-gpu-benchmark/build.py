"""Compile with the private native sysroot; no package installation or sudo."""
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent


def build_environment():
    env = os.environ.copy()
    env['PATH'] = str(ROOT / 'tools/bin') + ':' + str(ROOT / 'tools/usr/bin') + ':/usr/local/bin:/usr/bin:/bin'
    env['LD_LIBRARY_PATH'] = str(ROOT / 'tools/runtime-libs')
    env['CMAKE_BUILD_PARALLEL_LEVEL'] = '1'
    env['CMAKE_ROOT'] = str(next((ROOT / 'tools/usr/share').glob('cmake-[0-9]*')))
    return env


def main():
    env = build_environment()
    tools = ROOT / 'tools'
    # Debian's packages assume a merged-/usr filesystem layout.
    for name in ('lib', 'lib64'):
        path = tools / name
        if not path.exists() and not path.is_symlink():
            path.symlink_to('usr/' + name, target_is_directory=True)
    wrappers = tools / 'bin'
    wrappers.mkdir(exist_ok=True)
    for alias, binary in (('gcc', 'aarch64-linux-gnu-gcc-14'), ('cc', 'aarch64-linux-gnu-gcc-14'),
                          ('g++', 'aarch64-linux-gnu-g++-14'), ('c++', 'aarch64-linux-gnu-g++-14')):
        path = wrappers / alias
        if alias in ('g++', 'c++'):
            command = ['/usr/bin/python3', str(ROOT / 'compile_cxx.py'), str(tools / 'usr/bin' / binary)]
            path.write_text('#!/bin/sh\nexec ' + ' '.join(shlex.quote(x) for x in command) + ' "$@"\n')
        else:
            path.write_text('#!/bin/sh\nexec ' + shlex.quote(str(tools / 'usr/bin' / binary)) + ' ' +
                            shlex.quote('--sysroot=' + str(tools)) + ' "$@"\n')
        path.chmod(0o700)
        subprocess.run(['/bin/sh', '-n', str(path)], check=True)
    compiler = wrappers / 'gcc'
    cxx = wrappers / 'g++'
    # A native executable smoke check catches private-header/linker issues first.
    test = ROOT / 'scratch/compiler-test.cpp'
    test.write_text('#include <iostream>\nint main(){std::cout << "PRIVATE_COMPILER_OK\\n";}\n')
    subprocess.run([str(cxx), '--sysroot=' + str(tools), str(test), '-o', str(test.with_suffix(''))],
                   env=env, check=True)
    subprocess.run([str(test.with_suffix(''))], check=True)
    cmake = str(tools / 'usr/bin/cmake')
    arguments = [cmake, '-S', str(ROOT), '-B', str(ROOT / 'build'), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=' + str(compiler),
        '-DCMAKE_CXX_COMPILER=' + str(cxx), '-DCMAKE_SYSROOT=' + str(tools),
        '-DCMAKE_PREFIX_PATH=' + str(tools / 'usr'),
        '-DCMAKE_MAKE_PROGRAM=' + str(tools / 'usr/bin/ninja'),
        '-DVulkan_INCLUDE_DIR=' + str(tools / 'usr/include'),
        '-DVulkan_LIBRARY=/usr/lib/aarch64-linux-gnu/libvulkan.so.1',
        '-DVulkan_GLSLC_EXECUTABLE=' + str(tools / 'usr/bin/glslc'),
        '-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG -mcpu=cortex-a53',
        '-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG -mcpu=cortex-a53', '-DCMAKE_SKIP_RPATH=ON']
    (ROOT / 'build-flags.json').write_text(json.dumps({'configure': arguments,
        'parallel_jobs': 1, 'target': 'native Linux ARM64 / Cortex-A53',
        'private_sysroot': str(tools), 'runtime_vulkan': '/usr/lib/aarch64-linux-gnu/libvulkan.so.1'}, indent=2))
    subprocess.run(arguments, env=env, check=True)
    subprocess.run([cmake, '--build', str(ROOT / 'build'), '--target', 'torque-whisper-bench', '--parallel', '1'],
                   env=env, check=True)
    print('VULKAN_BUILD_READY', flush=True)


if __name__ == '__main__':
    main()
