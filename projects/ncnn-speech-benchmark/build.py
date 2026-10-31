"""Private ARM64 native build; never install an OS package or change a service."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else 'torque-ncnn-probe'
    if target not in ('torque-ncnn-probe', 'torque-ncnn-speech'):
        raise ValueError('Unknown experiment build target')
    jobs = 2 if target == 'torque-ncnn-speech' else 1
    tools = ROOT / 'tools'
    wrappers = tools / 'bin'
    wrappers.mkdir(exist_ok=True)
    for alias, binary in (('gcc', 'aarch64-linux-gnu-gcc-14'), ('g++', 'aarch64-linux-gnu-g++-14')):
        path = wrappers / alias
        path.write_text('#!/bin/sh\nexec ' + shlex.quote(str(tools / 'usr/bin' / binary)) + ' ' +
                        shlex.quote('--sysroot=' + str(tools)) + ' "$@"\n')
        path.chmod(0o700)
    env = os.environ.copy()
    env.update(PATH=str(wrappers) + ':' + str(tools / 'usr/bin') + ':/usr/local/bin:/usr/bin:/bin',
               LD_LIBRARY_PATH=str(tools / 'runtime-libs'), CMAKE_BUILD_PARALLEL_LEVEL=str(jobs),
               CMAKE_ROOT=str(next((tools / 'usr/share').glob('cmake-[0-9]*'))))
    cmake = str(tools / 'usr/bin/cmake')
    arguments = [cmake, '-S', str(ROOT / 'vendor/sherpa-ncnn'), '-B', str(ROOT / 'build'), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_STANDARD=17',
        '-DCMAKE_C_COMPILER=' + str(wrappers / 'gcc'), '-DCMAKE_CXX_COMPILER=' + str(wrappers / 'g++'),
        '-DCMAKE_SYSROOT=' + str(tools), '-DCMAKE_PREFIX_PATH=' + str(tools / 'usr'),
        '-DCMAKE_MAKE_PROGRAM=' + str(tools / 'usr/bin/ninja'),
        '-DCMAKE_PROJECT_sherpa-ncnn_INCLUDE=' + str(ROOT / 'inject.cmake'),
        '-DFETCHCONTENT_SOURCE_DIR_NCNN=' + str(ROOT / 'vendor/ncnn'),
        '-DBUILD_SHARED_LIBS=OFF', '-DSHERPA_NCNN_ENABLE_PORTAUDIO=OFF',
        '-DSHERPA_NCNN_ENABLE_BINARY=OFF', '-DSHERPA_NCNN_ENABLE_C_API=OFF',
        '-DSHERPA_NCNN_ENABLE_GENERATE_INT8_SCALE_TABLE=OFF',
        '-DNCNN_VULKAN=ON', '-DNCNN_SYSTEM_GLSLANG=ON', '-DNCNN_RUNTIME_CPU=OFF',
        '-DNCNN_ARM82=OFF', '-DNCNN_ARM82DOT=OFF', '-DNCNN_ARM82FP16FML=OFF',
        '-DNCNN_ARM84BF16=OFF', '-DNCNN_ARM84I8MM=OFF', '-DNCNN_ARM86SVE=OFF',
        '-DNCNN_BENCHMARK=ON', '-DNCNN_C_API=OFF', '-DNCNN_PIXEL=OFF',
        '-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG -mcpu=cortex-a53',
        '-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG -mcpu=cortex-a53', '-DCMAKE_SKIP_RPATH=ON']
    (ROOT / 'build-flags.json').write_text(json.dumps({'configure': arguments,
        'parallel_jobs': jobs, 'target': 'Linux ARM64 / Cortex-A53',
        'profiling': 'Compiled instrumentation is opt-in via TORQUE_NCNN_PROFILE; disabled for main timings'}, indent=2))
    subprocess.run(arguments, env=env, check=True, timeout=600)
    subprocess.run([cmake, '--build', str(ROOT / 'build'), '--target', target, '--parallel', str(jobs)],
                   env=env, check=True, timeout=3600)
    print('NATIVE_BUILD_READY: ' + target, flush=True)


if __name__ == '__main__':
    main()
