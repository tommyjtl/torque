"""Compile only the CPU IPC worker against the retained, pinned static libraries."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent
EXPERIMENT = ROOT.parent / 'ncnn-speech-benchmark'


def main():
    native = EXPERIMENT / 'tools/usr/bin/ninja'
    lines = subprocess.check_output([str(native), '-C', str(EXPERIMENT/'build'), '-t', 'commands',
                                     'torque-ncnn-speech'], text=True).splitlines()
    source = str(EXPERIMENT / 'speech.cpp')
    compile_line = next(line for line in lines if ' -c ' in line and source in line)
    args = shlex.split(compile_line)
    output = ROOT / 'runtime';output.mkdir(exist_ok=True)
    object_file = output / 'live_worker.o'
    compiled = [];i=0
    while i<len(args):
        value=args[i]
        if value in ('-MT','-MF','-MQ','-o'):
            i+=2;continue
        if value in ('-MD','-MMD','-MP'):
            i+=1;continue
        compiled.append(str(ROOT/'live_worker.cpp') if value==source else '-O2' if value=='-O3' else value)
        i+=1
    compiled += ['-o',str(object_file)]
    link_line = next(line for line in reversed(lines) if ' -o bin/torque-ncnn-speech ' in line)
    assert link_line.startswith(': && ') and link_line.endswith(' && :')
    linked=shlex.split(link_line[len(': && '):-len(' && :')])
    linked=[str(object_file) if value.endswith('/speech.cpp.o') else value for value in linked
            if not value.startswith('-Wl,--dependency-file=')]
    linked[linked.index('-o')+1]=str(output/'zipformer-live-worker')
    env=os.environ.copy();env['LD_LIBRARY_PATH']=str(EXPERIMENT/'tools/runtime-libs')
    env['PATH']=str(EXPERIMENT/'tools/bin')+':'+str(EXPERIMENT/'tools/usr/bin')+':/usr/bin:/bin'
    # No CMake reconfiguration: preserve original benchmark binaries and date-based headers.
    subprocess.run(compiled,cwd=EXPERIMENT/'build',env=env,check=True,timeout=180)
    subprocess.run(linked,cwd=EXPERIMENT/'build',env=env,check=True,timeout=120)
    manifest={'device':'cpu','source_sha256':hashlib.sha256((ROOT/'live_worker.cpp').read_bytes()).hexdigest(),
              'executable_sha256':hashlib.sha256((output/'zipformer-live-worker').read_bytes()).hexdigest(),
              'compile':compiled,'link':linked,'model_assets':str(EXPERIMENT/'models'),
              'note':'Same pinned inference libraries; only new IPC wrapper compiled, no benchmark rebuild'}
    (ROOT/'live-build.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('CPU_LIVE_WORKER_READY',flush=True)


if __name__=='__main__':
    main()
