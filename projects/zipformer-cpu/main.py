"""Finite recorded-clip CPU validation; live microphone support is a next step."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from common import score
from evidence import parse_rows, cpu_completed

ROOT = Path(__file__).resolve().parent


def command(executable, model, repeats, bulk, clips):
    return [str(executable), 'cpu', str(model), str(repeats), 'bulk' if bulk else 'paced',
            *[str(ROOT / clip['path']) for clip in clips]]


def status():
    from torque.protocol import Connection
    with Connection() as client:
        return client.request('status')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, choices=(1, 3), default=1)
    parser.add_argument('--first-clip', action='store_true')
    parser.add_argument('--bulk', action='store_true', help='Unpaced correctness check; no speech-end timing claim')
    args = parser.parse_args()
    before = status()
    if before['active'] or before['pending'] or before['maintenance'] or before['device']['owner']:
        raise RuntimeError('Torque is busy; nothing was cancelled')
    if sum(p.stat().st_size for p in (ROOT / 'results').rglob('*') if p.is_file() and not p.is_symlink()) > 10 * 1024**2:
        raise RuntimeError('Export/archive results before another run; the 10 MiB result budget is full')
    runtime = json.loads((ROOT / 'runtime-manifest.json').read_text())
    executable = ROOT / 'runtime/torque-zipformer'
    if hashlib.sha256(executable.read_bytes()).hexdigest() != runtime['executable_sha256']:
        raise ValueError('Retained executable changed')
    model = json.loads((ROOT / 'model-lock.json').read_text())
    for name, value in model['files'].items():
        if hashlib.sha256((ROOT / 'models' / name).read_bytes()).hexdigest() != value['sha256']:
            raise ValueError('Pinned model asset changed: ' + name)
    clips = json.loads((ROOT / 'fixtures.json').read_text())['clips']
    selected = clips[:1] if args.first_clip else clips
    for clip in selected:
        if hashlib.sha256((ROOT / clip['path']).read_bytes()).hexdigest() != clip['sha256']:
            raise ValueError('Pinned fixture changed')
    output = ROOT / 'results' / (time.strftime('%Y%m%dT%H%M%S') + '-cpu')
    output.mkdir(parents=True, mode=0o700)
    for name in ('main.py', 'evidence.py', 'common.py', 'runtime-manifest.json', 'model-lock.json', 'fixtures.json'):
        shutil.copyfile(ROOT / name, output / name)
    invocation = command(executable, ROOT / 'models', args.repeats, args.bulk, selected)
    (output / 'manifest.json').write_text(json.dumps({'device': 'cpu', 'arguments': vars(args),
        'command': invocation, 'runtime': before['release_id'], 'firmware_boot_id': before['device']['snapshot']['boot_id']}, indent=2))
    env = {k: v for k, v in os.environ.items() if not k.endswith(('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD'))
           and k not in ('LD_LIBRARY_PATH', 'VULKAN_SDK')}
    env.update(TORQUE_NCNN_PROFILE='0', OMP_NUM_THREADS='4')
    process = None
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        from torque.runtime import process_lease
        with (output / 'stdout.jsonl').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
            with process_lease(live=True) as descriptors:
                process = subprocess.Popen(invocation, env=env, stdout=stdout, stderr=stderr, pass_fds=descriptors)
            deadline = time.monotonic() + (180 if args.first_clip else 1200)
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise TimeoutError('Finite CPU validation deadline exceeded')
                if (output / 'stderr.log').stat().st_size > 4 * 1024**2:
                    raise RuntimeError('Native log budget exceeded')
                time.sleep(.2)
        rows = parse_rows((output / 'stdout.jsonl').read_text())
        measured = []
        for row in rows:
            if row.get('kind') == 'file':
                clip = next(c for c in selected if str(ROOT / c['path']) == row['path'])
                measured.append({**row, 'clip': clip['id'], 'reference': clip['reference'],
                                 'score': score(clip['reference'], row['text'])})
        (output / 'measurements.json').write_text(json.dumps(measured, indent=2))
        after = status()
        preserved = (all(before[k] == after[k] for k in ('release_id', 'epoch', 'pid'))
                     and before['device']['snapshot']['boot_id'] == after['device']['snapshot']['boot_id'])
        result = {'passed': process.returncode == 0 and cpu_completed(rows, len(selected)*args.repeats) and preserved,
                  'exit_code': process.returncode, 'device': 'cpu', 'runtime_and_firmware_preserved': preserved,
                  'microphone_opened': False}
        (output / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        print('RESULT_DIRECTORY: ' + str(output), flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(3)


if __name__ == '__main__':
    main()
