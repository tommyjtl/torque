"""Run bounded native CPU/Vulkan probes through Torque's project leases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from evidence import adreno_device, gpu_execution, parse_rows
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
    parser.add_argument('--profile', action='store_true', help='GPU correctness/offload evidence; timings are diagnostic')
    args = parser.parse_args()
    before = status()
    if before['active'] or before['pending'] or before['maintenance'] or before['device']['owner']:
        raise RuntimeError('Torque is busy; nothing was cancelled')
    executable = ROOT / 'build/torque-whisper-bench'
    model = ROOT.parent / 'whisper-tiny-benchmark/models/ggml-tiny.en.bin'
    expected = json.loads((ROOT / 'model-lock.json').read_text())
    if hashlib.sha256(model.read_bytes()).hexdigest() != expected['sha256']:
        raise ValueError('Baseline model changed')
    clips = json.loads((ROOT / 'fixtures.json').read_text())['clips']
    for clip in clips:
        if hashlib.sha256((ROOT / clip['path']).read_bytes()).hexdigest() != clip['sha256']:
            raise ValueError('Fixture changed')
    selected = clips[:1] if args.first_clip else clips
    used = sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file() and not p.is_symlink())
    if used > 2 * 1024**3:
        raise RuntimeError('Export build artifacts before exceeding the 2 GiB project budget')
    output = ROOT / 'results' / (time.strftime('%Y%m%dT%H%M%S') + '-' + args.mode + ('-profile' if args.profile else ''))
    output.mkdir(mode=0o700, parents=True)
    for name in ('benchmark.cpp', 'CMakeLists.txt', 'build.py', 'runner.py', 'evidence.py', 'source-lock.json', 'build-flags.json'):
        shutil.copyfile(ROOT / name, output / name)
    for name in ('compile_cxx.py', 'embed_spirv.py', 'apply_compat.py', 'vulkan-low-memory.patch'):
        if (ROOT / name).exists():
            shutil.copyfile(ROOT / name, output / name)
    env = os.environ.copy()
    for name in list(env):
        if name.endswith(('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD')) or name in ('LD_LIBRARY_PATH', 'VULKAN_SDK'):
            env.pop(name)
    env.update(VK_DRIVER_FILES='/usr/share/vulkan/icd.d/freedreno_icd.json',
               GGML_VK_VISIBLE_DEVICES='0', MESA_SHADER_CACHE_DIR=str(ROOT / 'scratch/mesa-cache'),
               MESA_SHADER_CACHE_MAX_SIZE='128M', OMP_NUM_THREADS='4')
    if args.profile:
        env['GGML_VK_PERF_LOGGER'] = '1'
    else:
        for name in list(env):
            if name.startswith('GGML_VK_PERF_LOGGER'):
                env.pop(name)
    command = [str(executable), args.mode]
    if args.mode != 'probe':
        command += [str(model), str(args.repeats), *[str(ROOT / clip['path']) for clip in selected]]
    manifest = {'arguments': vars(args), 'command': command, 'model_sha256': expected['sha256'],
                'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                'runtime': before['release_id'], 'daemon_epoch': before['epoch'],
                'firmware_boot_id': before['device']['snapshot']['boot_id'], 'fixtures': selected,
                'driver_icd': env['VK_DRIVER_FILES'], 'profiling': args.profile}
    manifest['backend_tuning'] = {key: env[key] for key in
        ('GGML_VK_DISABLE_F16', 'GGML_VK_DISABLE_FUSION') if key in env}
    manifest['embedding_receipts'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / 'scratch/embedded-spv').glob('*.receipt.json')}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    rows = []
    monitor_rows = []
    stopped = threading.Event()
    def monitor():
        from torque.protocol import Connection
        try:
            with Connection() as connection:
                while not stopped.is_set():
                    start = time.monotonic()
                    value = connection.request('status')
                    monitor_rows.append({'ms': (time.monotonic() - start) * 1000,
                                         'ready': value['device']['ready'], 'active': value['active']})
                    stopped.wait(.5)
        except Exception as error:
            monitor_rows.append({'error': str(error)})
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    process = None
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        from torque.runtime import process_lease
        with (output / 'stdout.jsonl').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
            with process_lease(live=True) as descriptors:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                           env=env, pass_fds=descriptors)
            # First-use GPU pipeline/shader initialization may be much slower.
            deadline = time.monotonic() + (180 if args.first_clip or args.mode == 'probe' else 900)
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise TimeoutError('Native benchmark deadline exceeded')
                if (output / 'stderr.log').stat().st_size > 16 * 1024**2:
                    raise RuntimeError('Diagnostic log budget exceeded')
                time.sleep(.1)
        text = (output / 'stdout.jsonl').read_text()
        rows, parse_errors = parse_rows(text)
        log = (output / 'stderr.log').read_text()
        report = {'exit_code': process.returncode, 'mode': args.mode, 'profiled': args.profile,
                  'native_output_errors': parse_errors,
                  'hardware_adreno_enumerated': adreno_device(rows)}
        if args.mode == 'gpu':
            report['evidence'] = gpu_execution(rows, log, require_profile=args.profile)
            report['gpu_execution_accepted'] = process.returncode == 0 and report['evidence']['accepted']
        report['passed'] = process.returncode == 0 and not parse_errors and (
            report.get('gpu_execution_accepted', True) if args.mode != 'probe' else adreno_device(rows))
        measured = []
        for row in rows:
            if row.get('kind') == 'file':
                clip = next(c for c in clips if Path(row['path']).stem == c['id'])
                measured.append({**row, 'clip': clip['id'], 'reference': clip['reference'],
                                 'score': score(clip['reference'], row['text'])})
        (output / 'measurements.json').write_text(json.dumps(measured, indent=2))
        if args.first_clip and args.mode != 'probe':
            report['calibration_transcript_matches'] = len(measured) == args.repeats and all(
                row['score']['exact'] for row in measured)
            report['passed'] = report['passed'] and report['calibration_transcript_matches']
        after = status()
        report.update(runtime_unchanged=after['release_id'] == before['release_id'] and after['epoch'] == before['epoch'],
                      firmware_boot_unchanged=after['device']['snapshot']['boot_id'] == before['device']['snapshot']['boot_id'])
        (output / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps({'directory': str(output), **report}, indent=2))
        if not report['passed']:
            raise SystemExit(1)
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(3)
        stopped.set()
        watcher.join(4)
        (output / 'status-ipc.json').write_text(json.dumps(monitor_rows))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
