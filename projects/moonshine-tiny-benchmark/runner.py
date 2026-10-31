"""Finite Moonshine streaming comparison; installed Torque Python owns capture."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import time
from common import guide_rows, score

ROOT = Path(__file__).resolve().parent


def status():
    from torque.protocol import Connection
    with Connection() as connection:
        return connection.request('status')


class Worker:
    def __init__(self, output, interval, window, final_only=False):
        from torque.runtime import process_lease
        self.responses = queue.Queue(maxsize=4)
        self.log = (output / f'worker-{interval}-{window}.stderr.log').open('a')
        self.started = time.monotonic()
        with process_lease(live=True) as descriptors:
            self.process = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-u', str(ROOT / 'worker.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                text=True, bufsize=1, pass_fds=descriptors)
        def read():
            try:
                while line := self.process.stdout.readline(65537):
                    if len(line) > 65536:
                        raise ValueError('Oversized response')
                    self.responses.put(json.loads(line), timeout=2)
                self.responses.put({'error': 'Worker exited; inspect its stderr log'}, timeout=2)
            except Exception as error:
                self.responses.put({'error': str(error)}, timeout=2)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            model = json.loads((ROOT / 'model-lock.json').read_text())
            self.ready = self.call('load', model=model['model_path'], interval=interval, vad_window=window,
                                   final_only=final_only)
            self.ready['process_to_ready_seconds'] = time.monotonic() - self.started
        except BaseException:
            self.close()
            raise

    def call(self, op, timeout=60, **values):
        self.process.stdin.write(json.dumps({'op': op, **values}) + '\n')
        self.process.stdin.flush()
        try:
            result = self.responses.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError('Worker deadline exceeded') from None
        if 'error' in result:
            raise RuntimeError(result['error'])
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
            stream.close()


class Monitor:
    def __init__(self):
        self.stop = threading.Event()
        self.samples = []
        def run():
            from torque.protocol import Connection
            try:
                with Connection() as connection:
                    while not self.stop.is_set():
                        start = time.monotonic()
                        value = connection.request('status')
                        self.samples.append({'ms': (time.monotonic() - start) * 1000,
                            'ready': value['device']['ready'], 'active': value['active']})
                        self.stop.wait(.2)
            except Exception as error:
                self.samples.append({'error': str(error)})
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
    def close(self):
        self.stop.set()
        self.thread.join(4)
        return self.samples


def capture_trial(worker, emit, prompt_index):
    from torque import Board, Frame
    from torque.audio import Microphone, audio_capabilities
    from torque._audio_worker import Alsa, ROUTE
    capability = audio_capabilities(card='ArduinoImolaHPH')
    if not capability['available']:
        raise RuntimeError(capability['reason'])
    source = next(s for s in capability['sources'] if s['accessible'])
    alsa = Alsa(source['card'], source['card_index'])
    alsa.idle()
    before = {name: alsa.get(name) for name, _ in ROUTE}
    prompts = ['Show the heart animation', 'Stop the current animation', 'Turn on the blue light']
    prompt = prompts[prompt_index]
    worker.call('begin', rate=48000)
    print(f'PREPARING_MICROPHONE: "{prompt}"', flush=True)
    packets = queue.Queue(maxsize=50)  # One second, ordered; abort instead of dropping.
    stop = threading.Event()
    reader = None
    state = {}
    with Board() as display:
        def show(name):
            display.matrix.draw(Frame.from_rows(guide_rows(name)))
        try:
            with Microphone(seconds=40) as mic:
                for _ in range(25):
                    mic.read(frames=960, latest=False)
                for digit in ('3', '2', '1'):
                    show(digit)
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline:
                        mic.read(frames=960, latest=False)
                show('speak')
                ready = time.monotonic()
                print(f'MICROPHONE_READY: say "{prompt}", then pause.', flush=True)
                def drain():
                    try:
                        while not stop.is_set():
                            chunk = mic.read(frames=960, latest=False)
                            if chunk is None:
                                break
                            packets.put((time.monotonic(), chunk.pcm), timeout=.2)
                    except Exception as error:
                        try:
                            packets.put(error, timeout=.2)
                        except queue.Full:
                            pass
                        stop.set()
                reader = threading.Thread(target=drain, daemon=True)
                reader.start()
                first_arrival = None
                last_audio_text = ''
                while time.monotonic() - ready < 30:
                    packet = packets.get(timeout=3)
                    if isinstance(packet, Exception):
                        raise packet
                    arrived, raw = packet
                    if time.monotonic() - arrived > 1:
                        raise RuntimeError('Inference fell behind capture by more than one second')
                    if first_arrival is None:
                        first_arrival = arrived
                    state = worker.call('chunk', pcm=base64.b64encode(raw).decode(), timeout=5)
                    if state['text'] and state['text'] != last_audio_text:
                        print('PARTIAL: ' + state['text'], flush=True)
                        last_audio_text = state['text']
                    if state['natural_final_proven']:
                        break
                stop.set()
                reader.join(3)
                if reader.is_alive():
                    raise RuntimeError('Capture reader did not stop')
            cleaned = time.monotonic()
            assert {name: alsa.get(name) for name, _ in ROUTE} == before, 'Mixer restoration mismatch'
            show('working')
            result = worker.call('finish')
            text = result.pop('text')
            for event in result['events']:
                event.pop('text', None)
            print('FINAL: ' + (text or '[no speech]'), flush=True)
            show('done')
            time.sleep(2)
        finally:
            stop.set()
            if reader:
                reader.join(3)
            display.close()
    emit({'kind': 'microphone', 'prompt_id': prompt_index, 'score': score(prompt, text), **result,
          'ready_monotonic': ready, 'first_pcm_arrival_monotonic': first_arrival,
          'capture_cleanup_monotonic': cleaned, 'mixer_restored': True,
          'timing_note': 'Native natural-final timestamp recorded; human/ADC speech end is not independently known'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('files', 'mic'))
    parser.add_argument('--interval', type=float, choices=(.1, .5), default=.5)
    parser.add_argument('--vad-window', type=float, choices=(.15, .5), default=.5)
    parser.add_argument('--repeats', type=int, choices=(1, 3), default=1)
    parser.add_argument('--run', help='Reuse one result bundle for all phases')
    parser.add_argument('--prompt-index', type=int, choices=range(3), default=0)
    parser.add_argument('--final-only', action='store_true', help='Skip incomplete-line decodes; measure natural final text')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    before = status()
    if before['active'] or before['pending'] or before['maintenance'] or before['device']['owner']:
        raise RuntimeError('Torque is busy')
    lock = (ROOT / '.run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    model = json.loads((ROOT / 'model-lock.json').read_text())
    if not Path(model['model_path']).resolve().is_relative_to(ROOT / 'models'):
        raise ValueError('Model path must stay inside this project')
    for name, expected in model['files'].items():
        path = ROOT / 'models' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('Model file hash mismatch')
    name = args.run or time.strftime('%Y%m%dT%H%M%S')
    if not name.replace('T', '').isdigit() or len(name) != 15:
        raise ValueError('Use a timestamped run identity')
    output = ROOT / 'results' / name
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sum(p.stat().st_size for p in (ROOT / 'results').rglob('*') if p.is_file()) > 20 * 1024**2:
        raise RuntimeError('Export results before exceeding 20 MiB')
    phase = f'{args.mode}-{args.interval}-{args.vad_window}-{time.strftime("%H%M%S")}'
    snapshot = output / 'source' / phase
    snapshot.mkdir(parents=True, exist_ok=True)
    for path in ROOT.glob('*.py'):
        if not (snapshot / path.name).exists():
            shutil.copyfile(path, snapshot / path.name)
    fixtures = json.loads((ROOT / 'fixtures.json').read_text())
    manifest = {'arguments': vars(args), 'model': model, 'fixtures': fixtures,
                'harness_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')},
                'release': before['release_id'], 'boot': before['device']['snapshot']['boot_id']}
    (output / (phase + '-manifest.json')).write_text(json.dumps(manifest, indent=2))
    metrics = (output / (phase + '.jsonl')).open('w')
    def emit(row):
        metrics.write(json.dumps(row) + '\n')
        metrics.flush()
    worker = None
    monitor = Monitor()
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('Experiment deadline')))
    signal.alarm(1200)
    try:
        worker = Worker(output, args.interval, args.vad_window, args.final_only)
        emit({'kind': 'initialization', **worker.ready})
        if args.mode == 'files':
            warmup = worker.call('file', path=str(ROOT / fixtures['clips'][0]['path']), sha256=fixtures['clips'][0]['sha256'])
            emit({'kind': 'warmup', **warmup})
            for repetition in range(args.repeats):
                for clip in fixtures['clips']:
                    result = worker.call('file', path=str(ROOT / clip['path']), sha256=clip['sha256'])
                    result['score'] = score(clip['reference'], result['text'])
                    emit({'kind': 'file', 'repeat': repetition, 'clip': clip['id'], **result})
                    latency = result['file_end_to_final_seconds']
                    print(json.dumps({'clip': clip['id'], 'natural_final': result['natural_final_proven'],
                        'file_end_to_final_seconds': latency, 'first_partial_seconds': result['first_partial_from_start_seconds'],
                        'wer': result['score']['wer'], 'rtf': result['compute_rtf_with_trailing_silence']}), flush=True)
        else:
            capture_trial(worker, emit, args.prompt_index)
        after = status()
        assert after['device']['ready'] and after['device']['snapshot']['boot_id'] == before['device']['snapshot']['boot_id']
        assert after['release_id'] == before['release_id'] and after['epoch'] == before['epoch']
        (output / (phase + '-completed.json')).write_text(json.dumps({'passed': True, 'runtime_unchanged': True,
            'firmware_boot_unchanged': True, 'model_arch': 2}))
        print('RESULT_BUNDLE: ' + name, flush=True)
    finally:
        signal.alarm(0)
        if worker:
            worker.close()
        emit({'kind': 'ipc_under_load', 'samples': monitor.close()})
        metrics.close()
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
