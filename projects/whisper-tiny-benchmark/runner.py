"""Finite, isolated Whisper experiment; run with the installed Torque Python."""
import argparse
from contextlib import nullcontext
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from common import guide_rows, read_wav, score, words

ROOT = Path(__file__).resolve().parent


def status():
    from torque.protocol import Connection
    with Connection() as client:
        return client.request('status')


def sensors():
    temperatures = {}
    for path in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
        try:
            temperatures[path.parent.name] = int(path.read_text()) / 1000
        except (OSError, ValueError):
            pass
    try:
        frequency = int(Path('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq').read_text())
    except (OSError, ValueError):
        frequency = None
    return {'load': os.getloadavg(), 'cpu0_khz': frequency, 'temperatures_c': temperatures,
            'throttling': 'No verified throttling counter; temperatures/frequencies only'}


class Monitor:
    def __init__(self):
        self.stop = threading.Event()
        self.values = []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        from torque.protocol import Connection
        try:
            with Connection() as client:
                while not self.stop.is_set():
                    start = time.monotonic()
                    value = client.request('status')
                    self.values.append({'ms': (time.monotonic() - start) * 1000,
                        'ready': value['device']['ready'], 'active': value['active'],
                        'owner': value['device']['owner']})
                    self.stop.wait(.2)
        except Exception as error:
            self.values.append({'error': str(error)})

    def close(self):
        self.stop.set()
        self.thread.join(4)
        return self.values


class Worker:
    def __init__(self, threads, log):
        from torque.runtime import process_lease
        self.log = log.open('w')
        self.responses = queue.Queue(maxsize=4)
        self.started = time.monotonic()
        with process_lease(live=True) as descriptors:
            self.process = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-u', str(ROOT / 'worker.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                text=True, bufsize=1, pass_fds=descriptors)
        def read():
            while line := self.process.stdout.readline(65537):
                try:
                    if len(line) > 65536:
                        raise ValueError('Oversized worker output')
                    self.responses.put(json.loads(line), timeout=2)
                except Exception as error:
                    self.responses.put({'worker_error': str(error)}, timeout=2)
                    return
            self.responses.put({'worker_error': 'Worker exited; inspect its private stderr log'}, timeout=2)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.loaded = self.call('load', timeout=60, model=str(ROOT / 'models/ggml-tiny.en.bin'), threads=threads)
            self.loaded['process_start_to_ready_seconds'] = time.monotonic() - self.started
        except BaseException:
            self.close()
            raise

    def call(self, op, timeout=65, **arguments):
        self.process.stdin.write(json.dumps({'op': op, **arguments}) + '\n')
        self.process.stdin.flush()
        try:
            result = self.responses.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError('Worker deadline exceeded') from None
        if 'worker_error' in result:
            raise RuntimeError(result['worker_error'])
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(3)
        for stream in (self.process.stdin, self.process.stdout, self.log):
            if stream:
                stream.close()


def retained_results(current):
    completed = [p for p in (ROOT / 'results').iterdir() if p.is_dir() and not p.is_symlink()
                 and p != current and (p / 'completed.json').is_file()]
    candidates = sorted((p for p in completed if not (p / '.keep').exists()), key=lambda p: p.name)
    def size():
        return sum(p.stat().st_size for p in (ROOT / 'results').rglob('*') if p.is_file() and not p.is_symlink())
    while candidates and (len(completed) >= 3 or size() > 20 * 1024**2):
        oldest = candidates.pop(0)
        completed.remove(oldest)
        shutil.rmtree(oldest)
    if len(completed) >= 3 or size() > 20 * 1024**2:
        raise RuntimeError('Pinned or unfinished results fill the budget; export them before another run')


def file_trials(output, clips, emit, repeats):
    for threads in (2, 4):
        worker = Worker(threads, output / f'threads-{threads}.stderr.log')
        monitor = Monitor()
        try:
            emit({'kind': 'initialization', 'threads': threads, **worker.loaded, 'sensors': sensors()})
            first = worker.call('file', path=str(ROOT / clips[0]['path']), sha256=clips[0]['sha256'])
            emit({'kind': 'first_inference', 'threads': threads, **first,
                  'process_start_to_final_seconds': time.monotonic() - worker.started})
            # The first inference is also the excluded warm-up.
            for repetition in range(repeats):
                for clip in clips:
                    result = worker.call('file', path=str(ROOT / clip['path']), sha256=clip['sha256'])
                    row = {'kind': 'file', 'threads': threads, 'repeat': repetition, 'clip': clip['id'],
                           **result, 'reference': clip['reference'], 'score': score(clip['reference'], result['text']),
                           'normalized_text': words(result['text']), 'sensors': sensors()}
                    emit(row)
                    print(f"{threads} threads · {clip['id']} · {result['decode_seconds']:.2f}s · RTF {result['rtf']:.2f} · WER {row['score']['wer']:.1%}", flush=True)
            emit({'kind': 'silence', 'threads': threads, **worker.call('silence')})
        finally:
            emit({'kind': 'ipc_under_load', 'threads': threads, 'samples': monitor.close()})
            worker.close()


def paced_trial(worker, clip):
    pcm = read_wav(ROOT / clip['path'], clip['sha256'])
    worker.call('begin', rate=16000)
    start, endpoint, maximum_lag = time.monotonic(), None, 0.
    full = pcm + b'\0' * 32000  # One second of actual paced trailing silence.
    for pos in range(0, len(full), 640):
        target = start + (pos // 2) / 16000
        time.sleep(max(0, target - time.monotonic()))
        maximum_lag = max(maximum_lag, time.monotonic() - target)
        state = worker.call('chunk', pcm=base64.b64encode(full[pos:pos + 640]).decode(), timeout=3)
        if state['endpoint']:
            endpoint = time.monotonic()
            break
    finish = worker.call('finish')
    final = finish.get('final_monotonic', time.monotonic())
    return {**finish, 'endpoint_to_final_seconds': final - endpoint if endpoint else None,
            'vad_estimated_end_to_final_seconds': final - (start + state['last_speech_sample'] / 16000) if state['last_speech_sample'] else None,
            'file_end_to_final_seconds': final - (start + len(pcm) / 2 / 16000),
            'reference_speech_end_latency': None, 'reference_speech_end_note': 'No independent human speech-end annotation',
            'replay_max_lag_seconds': maximum_lag, 'endpoint_before_file_end': endpoint is not None and pos < len(pcm) - 640}


def mic_trials(worker, emit, trials, *, guided=False, prompt_index=0):
    from torque.audio import Microphone, audio_capabilities
    from torque import Board, Frame
    from torque._audio_worker import Alsa, ROUTE
    capability = audio_capabilities(card='ArduinoImolaHPH')
    if not capability['available']:
        raise RuntimeError(capability['reason'])
    source = next(s for s in capability['sources'] if s['accessible'])
    alsa = Alsa(source['card'], source['card_index'])
    alsa.idle()
    before = {name: alsa.get(name) for name, _ in ROUTE}
    prompts = ['Show the heart animation', 'Stop the current animation', 'Turn on the blue light']
    for number in range(trials):
        selected = (number + prompt_index) % len(prompts)
        prompt = prompts[selected]
        worker.call('begin', rate=48000, max_seconds=32 if guided else 16)
        print(f'PREPARING_MICROPHONE: next phrase is "{prompt}"', flush=True)
        started, anchor, endpoint, state = time.monotonic(), None, None, {}
        with Board() if guided else nullcontext() as display:
            def show(name):
                if display:
                    display.matrix.draw(Frame.from_rows(guide_rows(name)))
            try:
                with Microphone(seconds=40 if guided else 16) as mic:
                    # Discard only the announced pre-READY settling/countdown.
                    for _ in range(25):
                        mic.read(frames=960, latest=False)
                    if guided:
                        for digit in ('3', '2', '1'):
                            show(digit)
                            until = time.monotonic() + 1
                            while time.monotonic() < until:
                                mic.read(frames=960, latest=False)
                    show('speak')
                    print(f'MICROPHONE_READY {number + 1}/{trials}: say "{prompt}", then pause.', flush=True)
                    ready = time.monotonic()
                    while time.monotonic() - ready < (30 if guided else 15):
                        chunk = mic.read(frames=960, latest=False)
                        if chunk is None:
                            break
                        if anchor is None:
                            anchor = time.monotonic() - chunk.frames / chunk.sample_rate
                        state = worker.call('chunk', pcm=base64.b64encode(chunk.pcm).decode(), timeout=3)
                        if state['endpoint']:
                            endpoint = time.monotonic()
                            break
                cleaned = time.monotonic()
                assert {name: alsa.get(name) for name, _ in ROUTE} == before, 'Mixer restoration mismatch'
                show('working')
                result = worker.call('finish')
                text = result.pop('text')
                print(f'RECOGNIZED: {text or "[no speech]"}', flush=True)
                show('done')
                if guided:
                    time.sleep(2)
            finally:
                if display:
                    display.close()  # Release temporary ownership; status restores itself.
        final = result.get('final_monotonic', time.monotonic())
        last = result.get('last_speech_sample')
        emit({'kind': 'microphone', 'prompt_id': selected, 'matrix_guided': guided, 'score': score(prompt, text),
              **result, 'capture_start_monotonic': started, 'ready_monotonic': ready,
              'capture_cleanup_monotonic': cleaned, 'endpoint_monotonic': endpoint,
              'truncated': bool(result.get('has_speech') and not endpoint),
              'endpoint_to_final_seconds': final - endpoint if endpoint else None,
              'vad_estimated_end_to_final_seconds': final - (anchor + last / 16000) if anchor and last else None,
              'audio_clock_note': 'Anchor is first PCM arrival minus chunk duration; ADC/ALSA buffering is not independently timestamped',
              'mixer_restored': True})
        print('MICROPHONE_CLOSED', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('files', 'replay', 'mic'))
    parser.add_argument('--threads', type=int, choices=(2, 4), default=4)
    parser.add_argument('--repeats', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--mic-trials', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--guide-matrix', action='store_true', help='3-2-1, speak circle, working dots, completion check; 30s listening')
    parser.add_argument('--prompt-index', type=int, choices=range(3), default=0)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    state = status()
    if state['active'] or state['pending'] or state['device']['owner'] or state['maintenance']:
        raise RuntimeError('Torque is busy; experiment did not cancel it')
    model = json.loads((ROOT / 'model.json').read_text())
    if hashlib.sha256((ROOT / 'models/ggml-tiny.en.bin').read_bytes()).hexdigest() != model['sha256']:
        raise ValueError('Model hash mismatch')
    lock = (ROOT / '.run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    output = ROOT / 'results' / (time.strftime('%Y%m%dT%H%M%S') + '-' + args.mode)
    output.mkdir(mode=0o700, parents=True)
    retained_results(output)
    if args.mode in ('files', 'replay'):
        (output / '.keep').touch()  # Preserve comparative baselines during microphone retries.
    manifest = json.loads((ROOT / 'fixtures.json').read_text())
    (output / 'manifest.json').write_text(json.dumps({'arguments': vars(args), 'model': model,
        'harness_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')},
        'fixtures': manifest, 'release': state['release_id'], 'firmware_boot': state['device']['snapshot']['boot_id'],
        'sensors': sensors(), 'decoder': {'language': 'en', 'greedy_best_of': 1, 'temperature': 0,
        'temperature_inc': 0, 'no_context': True, 'use_gpu': False}}, indent=2))
    rows = []
    metrics = (output / 'metrics.jsonl').open('w')
    def emit(row):
        rows.append(row)
        metrics.write(json.dumps(row) + '\n')
        metrics.flush()
    worker = None
    started = time.monotonic()
    def expired(*_):
        raise TimeoutError('20-minute sweep deadline exceeded')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(1200)
    try:
        baseline = Monitor()
        time.sleep(1)
        emit({'kind': 'ipc_baseline', 'samples': baseline.close()})
        if args.mode == 'files':
            file_trials(output, manifest['clips'], emit, args.repeats)
        else:
            worker = Worker(args.threads, output / 'worker.stderr.log')
            emit({'kind': 'initialization', **worker.loaded})
            if args.mode == 'mic':
                mic_trials(worker, emit, args.mic_trials, guided=args.guide_matrix, prompt_index=args.prompt_index)
            else:
                for clip in manifest['clips']:
                    result = paced_trial(worker, clip)
                    emit({'kind': 'replay', 'clip': clip['id'], **result,
                          'reference': clip['reference'], 'score': score(clip['reference'], result.get('text', ''))})
                    print(json.dumps(rows[-1]), flush=True)
        after = status()
        assert after['device']['ready'] and after['device']['snapshot']['boot_id'] == state['device']['snapshot']['boot_id']
        (output / 'completed.json').write_text(json.dumps({'passed': True, 'wall_seconds': time.monotonic() - started,
                  'firmware_boot_unchanged': True, 'no_audio_saved': True}))
        print('RESULT_DIRECTORY: ' + str(output), flush=True)
    finally:
        signal.alarm(0)
        if worker:
            worker.close()
        metrics.close()
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Benchmark interrupted; capture cleanup completed.', file=sys.stderr)
        raise SystemExit(130)
