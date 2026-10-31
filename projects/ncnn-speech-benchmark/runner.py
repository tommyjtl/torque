"""Finite leased native experiment, independent of firmware and audio devices."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from evidence import parse_rows, probe_passed
from common import score

ROOT = Path(__file__).resolve().parent


def status():
    from torque.protocol import Connection
    with Connection() as client:
        return client.request('status')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('probe', 'cpu', 'gpu'))
    parser.add_argument('--repeats', type=int, choices=(1, 3), default=1)
    parser.add_argument('--first-clip', action='store_true')
    parser.add_argument('--bulk', action='store_true', help='Unpaced correctness/throughput; no speech-end latency claim')
    parser.add_argument('--profile', action='store_true', help='Diagnostic per-operation evidence, excluded from main timing')
    args = parser.parse_args()
    before = status()
    if before['active'] or before['pending'] or before['maintenance'] or before['device']['owner']:
        raise RuntimeError('Torque is busy; nothing was cancelled')
    if sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file() and not p.is_symlink()) > 2 * 1024**3:
        raise RuntimeError('Project exceeded its 2 GiB budget')
    executable = ROOT / 'build/bin' / ('torque-ncnn-probe' if args.mode == 'probe' else 'torque-ncnn-speech')
    selected = []
    if args.mode != 'probe':
        lock = json.loads((ROOT / 'model-lock.json').read_text())
        for name, value in lock['files'].items():
            if hashlib.sha256((ROOT / 'models' / name).read_bytes()).hexdigest() != value['sha256']:
                raise RuntimeError('Pinned model asset changed')
        clips = json.loads((ROOT / 'fixtures.json').read_text())['clips']
        selected = clips[:1] if args.first_clip else clips
        for clip in selected:
            if hashlib.sha256((ROOT / clip['path']).read_bytes()).hexdigest() != clip['sha256']:
                raise RuntimeError('Pinned fixture changed')
    suffix = args.mode + ('-bulk' if args.bulk else '') + ('-profile' if args.profile else '')
    output = ROOT / 'results' / (time.strftime('%Y%m%dT%H%M%S') + '-' + suffix)
    output.mkdir(parents=True, mode=0o700)
    for name in ('probe.cpp', 'speech.cpp', 'runner.py', 'evidence.py', 'source-lock.json', 'build-flags.json', 'model-lock.json', 'runtime-profile.patch'):
        if not (ROOT / name).exists():
            continue
        shutil.copyfile(ROOT / name, output / name)
    env = {k: v for k, v in os.environ.items() if not k.endswith(('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD'))
           and k not in ('LD_LIBRARY_PATH', 'VULKAN_SDK')}
    env.update(VK_DRIVER_FILES='/usr/share/vulkan/icd.d/freedreno_icd.json',
               MESA_SHADER_CACHE_DIR=str(ROOT / 'scratch/mesa-cache'), MESA_SHADER_CACHE_MAX_SIZE='128M',
               OMP_NUM_THREADS='4')
    env['TORQUE_NCNN_PROFILE'] = '1' if args.profile else '0'
    manifest = {'mode': args.mode, 'arguments': vars(args), 'fixtures': selected,
        'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'driver_icd': env['VK_DRIVER_FILES'], 'runtime': before['release_id'],
        'daemon_epoch': before['epoch'], 'firmware_boot_id': before['device']['snapshot']['boot_id']}
    if args.mode == 'gpu' and not args.profile:
        accepted = []
        for path in (ROOT / 'results').glob('*-gpu-bulk-profile/result.json'):
            result = json.loads(path.read_text())
            earlier = json.loads((path.parent / 'manifest.json').read_text())
            if (result.get('passed') is True and result.get('gpu_timed_operations', 0) > 0
                    and earlier['executable_sha256'] == manifest['executable_sha256']):
                accepted.append(path.parent.name)
        if not accepted:
            raise RuntimeError('Run a successful profiled GPU calibration before unprofiled GPU timings')
        manifest['gpu_evidence_run'] = sorted(accepted)[-1]
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    stop = threading.Event()
    samples = []
    def monitor():
        from torque.protocol import Connection
        try:
            with Connection() as connection:
                while not stop.is_set():
                    start = time.monotonic()
                    value = connection.request('status')
                    samples.append({'ms': (time.monotonic()-start)*1000, 'ready': value['device']['ready']})
                    stop.wait(.5)
        except Exception as error:
            samples.append({'error': str(error)})
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    process = None
    try:
        from torque.runtime import process_lease
        with (output / 'stdout.jsonl').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
            with process_lease(live=True) as descriptors:
                command = [str(executable)]
                if args.mode != 'probe':
                    command += [args.mode, str(ROOT / 'models'), str(args.repeats),
                                'bulk' if args.bulk else 'paced', *[str(ROOT / clip['path']) for clip in selected]]
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                           env=env, pass_fds=descriptors)
            deadline = time.monotonic() + (180 if args.mode == 'probe' or (args.bulk and args.first_clip) else 1200)
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError('GPU probe deadline exceeded')
                if (output / 'stderr.log').stat().st_size > 64 * 1024**2:
                    raise RuntimeError('Native log budget exceeded')
                time.sleep(.2)
        after = status()
        errors = []
        try:
            rows = parse_rows((output / 'stdout.jsonl').read_text())
        except ValueError as error:
            rows = []; errors.append(str(error))
        measured = []
        for row in rows:
            if row.get('kind') == 'file':
                clip = next(c for c in selected if str(ROOT / c['path']) == row['path'])
                measured.append({**row, 'clip': clip['id'], 'reference': clip['reference'],
                                 'score': score(clip['reference'], row['text'])})
        (output / 'measurements.json').write_text(json.dumps(measured, indent=2))
        stderr_text = (output / 'stderr.log').read_text(errors='replace')
        gpu_times = [float(x) for x in re.findall(r'\s([0-9.]+)us\s+\|', stderr_text)]
        cpu_times = [float(x) for x in re.findall(r'\s([0-9.]+)ms\s+\|', stderr_text)]
        passed = probe_passed(rows) if args.mode == 'probe' else (
            any(r.get('kind') == 'speech_complete' and r.get('passed') is True for r in rows)
            and len(measured) == len(selected) * args.repeats
            and all(r['text'] and r['natural_final_proven'] for r in measured))
        if args.mode == 'gpu' and args.profile:
            passed = passed and any(x > 0 for x in gpu_times)
        result = {'passed': process.returncode == 0 and passed and not errors, 'exit_code': process.returncode,
                  'profiled': args.profile, 'mode': args.mode, 'bulk': args.bulk, 'native_output_errors': errors,
                  'gpu_timed_operations': sum(x > 0 for x in gpu_times), 'gpu_operation_us_sum': sum(gpu_times),
                  'cpu_profiled_operations': len(cpu_times),
                  'runtime_unchanged': all(before[k] == after[k] for k in ('release_id', 'epoch', 'pid')),
                  'firmware_boot_unchanged': before['device']['snapshot']['boot_id'] == after['device']['snapshot']['boot_id']}
        (output / 'result.json').write_text(json.dumps(result, indent=2))
        for row in measured:
            print(json.dumps({'clip': row['clip'], 'repeat': row['repeat'], 'text': row['text'],
                              'final_delay': row['file_end_to_final_seconds'], 'wer': row['score']['wer']}), flush=True)
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
        stop.set()
        watcher.join(3)
        (output / 'ipc.json').write_text(json.dumps(samples))


if __name__ == '__main__':
    main()
