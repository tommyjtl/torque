"""Finite ALSA owner; control-pipe EOF restores routing after client death."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

from .audio import AudioError, CARD_ID, FORMAT, RATE, ROUTE, MicrophoneBusy, audio_capabilities


class Alsa:
    def __init__(self, card, index):
        self.card, self.index = card, index

    def command(self, *arguments):
        result = subprocess.run(['amixer', '-c', self.card, *arguments],
                                capture_output=True, text=True, timeout=2)
        if result.returncode:
            raise AudioError('ALSA mixer command failed: ' + result.stderr.strip()[:500])
        return result.stdout

    def get(self, name):
        text = self.command('cget', "iface=MIXER,name='" + name + "'")
        kind = re.search(r'type=(BOOLEAN|INTEGER|ENUMERATED),[^\n]*values=1(?:,|\s)', text)
        value = re.search(r'^\s*: values=([^\n]+)$', text, re.M)
        if not kind or not value:
            raise AudioError('Unsupported mixer control: ' + name)
        items = dict((label, number) for number, label in re.findall(r"Item #(\d+) '([^']+)'", text))
        return {'kind': kind[1], 'value': value[1].strip(), 'items': items}

    def set(self, name, value):
        self.command('cset', "iface=MIXER,name='" + name + "'", str(value))

    def idle(self):
        paths = list((Path('/proc/asound') / f'card{self.index}').glob('pcm*c/sub*/status'))
        if not paths:
            raise AudioError('Cannot establish capture-device ownership')
        if any(path.read_text().strip() != 'closed' for path in paths):
            raise MicrophoneBusy('An existing ALSA capture is active; it was not stopped')

    def capture(self, seconds, diagnostic):
        return subprocess.Popen(['arecord', '-q', '--fatal-errors', '-D',
                                 f'plughw:CARD={self.card},DEV=2', '-t', 'raw',
                                 '-f', FORMAT, '-c', '1', '-r', str(RATE),
                                 '--period-size=1200', '--buffer-size=4800', '-d', str(seconds)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=diagnostic, bufsize=0)


def claim(card, directory=None):
    directory = Path(directory) if directory is not None else Path.home() / '.cache/torque/audio'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise AudioError('Audio lease directory must be owner-only')
    fd = os.open(directory / (card + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise AudioError('Audio lease must be an owner-only regular file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MicrophoneBusy('Another Torque project owns this audio card') from None
        return fd
    except BaseException:
        os.close(fd)
        raise


def desired(control, value):
    if control['kind'] == 'BOOLEAN':
        return 'on' if value else 'off'
    if control['kind'] == 'ENUMERATED':
        if value not in control['items']:
            raise AudioError('Required microphone routing choice is unavailable')
        return control['items'][value]
    return str(value)


class Routing:
    def __init__(self, alsa):
        self.alsa, self.changed = alsa, []

    def setup(self, stop):
        # Verify the entire profile and save its exact values before any write.
        controls = [(name, self.alsa.get(name), value) for name, value in ROUTE]
        prepared = [(name, control['value'], desired(control, value)) for name, control, value in controls]
        for name, before, target in prepared:
            if stop.is_set():
                return
            if self.alsa.get(name)['value'] != before:
                raise AudioError('Mixer changed during microphone setup: ' + name)
            if before == target:
                continue
            # Save before mutation: a failed acknowledgement may still have acted.
            self.changed.append((name, before, target))
            self.alsa.set(name, target)
            if self.alsa.get(name)['value'] != target:
                raise AudioError('Microphone routing readback failed: ' + name)

    def restore(self):
        failures = []
        for name, before, installed in reversed(self.changed):
            try:
                current = self.alsa.get(name)['value']
                if current == before:
                    continue
                if current != installed:
                    failures.append(name + ' changed by another consumer')
                    continue
                self.alsa.set(name, before)
                if self.alsa.get(name)['value'] != before:
                    failures.append(name + ' restore readback failed')
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                failures.append(name + ': ' + type(error).__name__)
        if failures:
            raise AudioError('Mixer restoration incomplete: ' + '; '.join(failures))


def stream(alsa, seconds, stop, *, output=1):
    with tempfile.TemporaryFile() as diagnostic:
        process = alsa.capture(seconds, diagnostic)
        pending = bytearray()
        ready, ended, stalled = False, False, None
        deadline = time.monotonic() + seconds + 3
        os.set_blocking(output, False)
        try:
            while not stop.is_set() and time.monotonic() < deadline:
                readers = [] if ended or len(pending) >= 65536 else [process.stdout]
                readable, writable, _ = select.select(readers, [output] if pending else [], [], 0.01)
                if readable:
                    data = os.read(process.stdout.fileno(), 16384)
                    if data:
                        if not ready:
                            pending.extend((json.dumps({'ready': True, 'sample_rate': RATE,
                                                        'channels': 1, 'format': FORMAT}) + '\n').encode())
                            ready = True
                        pending.extend(data)
                    else:
                        ended = True
                if writable:
                    try:
                        sent = os.write(output, pending)
                        del pending[:sent]
                    except BlockingIOError:
                        pass
                    except BrokenPipeError:
                        stop.set()
                if len(pending) >= 65536:
                    stalled = time.monotonic() if stalled is None else stalled
                    if time.monotonic() - stalled > 2:
                        raise AudioError('Audio consumer stopped reading; capture stopped')
                else:
                    stalled = None
                if ended and not pending:
                    break
            if not ready and not stop.is_set():
                raise AudioError('Capture produced no PCM samples')
        finally:
            if ended and process.poll() is None:
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()
            process.stdout.close()
        if not stop.is_set() and process.returncode:
            diagnostic.seek(0)
            detail = diagnostic.read(2048).decode(errors='replace').strip()
            raise AudioError('ALSA capture failed: ' + (detail or str(process.returncode)))


def run(alsa, seconds, stop, *, output=1):
    routing = Routing(alsa)
    try:
        alsa.idle()
        routing.setup(stop)
        if not stop.is_set():
            stream(alsa, seconds, stop, output=output)
    finally:
        routing.restore()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', required=True, choices=[CARD_ID])
    parser.add_argument('--seconds', required=True, type=int, choices=range(1, 301))
    args = parser.parse_args(argv)
    stop = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: stop.set())
    def parent_watch():
        try:
            while os.read(0, 1):
                pass
        finally:
            stop.set()
    threading.Thread(target=parent_watch, daemon=True).start()
    lease = None
    try:
        capabilities = audio_capabilities(card=args.card)
        if not capabilities['available']:
            raise AudioError(capabilities['reason'])
        source = next(s for s in capabilities['sources'] if s['accessible'])
        lease = claim(args.card)
        run(Alsa(args.card, source['card_index']), args.seconds, stop)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 3 if isinstance(error, MicrophoneBusy) else 1
    finally:
        if lease is not None:
            os.close(lease)


if __name__ == '__main__':
    raise SystemExit(main())
