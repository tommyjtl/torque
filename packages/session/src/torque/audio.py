"""Local Media Carrier microphone input; discovery never starts capture."""
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import time

RATE = 48000
FORMAT = 'S32_LE'
CARD_ID = 'ArduinoImolaHPH'
ROUTE = (
    ('MultiMedia3 Mixer TX_CODEC_DMA_TX_3', 1),
    ('TX DEC0 MUX', 'SWR_MIC'),
    ('TX SMIC MUX0', 'SWR_MIC1'),
    ('TX_AIF1_CAP Mixer DEC0', 1),
    ('ADC2 Switch', 1),
    ('ADC2 MUX', 'INP2'),
    ('ADC2_MIXER Switch', 1),
    ('ADC2 Volume', 5),
    ('TX_DEC0 Volume', 84),  # 0 dB digital gain; retain headroom for voice.
)


class AudioError(RuntimeError):
    """Capture or cleanup could not be completed."""


class MicrophoneUnavailable(AudioError):
    """The supported local source or its access is unavailable."""


class MicrophoneBusy(AudioError):
    """Another reader owns the card or an existing capture is active."""


def audio_capabilities(*, card=None, proc=Path('/proc/asound'), dev=Path('/dev/snd')):
    """Report endpoints/access only, without opening PCM or changing controls.

    available means a supported endpoint is accessible, not that an analog
    microphone is plugged in, producing a signal, or free of other consumers.
    """
    if card is not None and (not isinstance(card, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', card)):
        raise ValueError('Choose a discovered ALSA card identifier')
    commands = {name: shutil.which(name) for name in ('arecord', 'amixer')}
    sources = []
    if sys.platform == 'linux':
        try:
            lines = (Path(proc) / 'cards').read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            match = re.match(r'\s*(\d+) \[([^]]+)\]:', line)
            if not match:
                continue
            index, identity = int(match[1]), match[2].strip()
            if identity != CARD_ID or (card is not None and identity != card):
                continue
            nodes = [Path(dev) / f'controlC{index}', Path(dev) / f'pcmC{index}D2c']
            accessible = all(p.is_char_device() and os.access(p, os.R_OK | os.W_OK) for p in nodes)
            sources.append({'source': 'media-carrier', 'card': identity, 'card_index': index,
                            'device': 2, 'alsa_device': f'plughw:CARD={identity},DEV=2',
                            'accessible': accessible, 'sample_rate': RATE, 'channels': 1,
                            'format': FORMAT, 'signal_verified': False})
    readable = [source for source in sources if source['accessible']]
    ready = len(readable) == 1 and all(commands.values())
    reason = ('Linux ALSA required' if sys.platform != 'linux' else
              'arecord and amixer must already be installed' if not all(commands.values()) else
              'Select one supported card' if len(readable) > 1 else
              'No accessible UNO Q Media Carrier capture endpoint' if not readable else None)
    return {'available': ready, 'selection_required': len(readable) > 1, 'sources': sources,
            'reason': reason, 'capture_started': False, 'signal_verified': False,
            'supported_source': 'media-carrier', 'max_seconds': 300}


@dataclass(frozen=True)
class AudioChunk:
    """Mono 48 kHz signed 32-bit little-endian PCM; levels are digital, not SPL."""
    pcm: bytes = field(repr=False)
    sample_rate: int = RATE
    channels: int = 1
    format: str = FORMAT

    def __post_init__(self):
        if not isinstance(self.pcm, bytes) or not self.pcm or len(self.pcm) % 4 or len(self.pcm) > RATE * 4:
            raise ValueError('PCM chunk must contain 1..48000 complete S32_LE samples')
        if (self.sample_rate, self.channels, self.format) != (RATE, 1, FORMAT):
            raise ValueError('This source uses mono 48000 Hz S32_LE')

    @property
    def frames(self):
        return len(self.pcm) // 4

    @property
    def rms(self):
        total = sum(value * value for value, in struct.iter_unpack('<i', self.pcm))
        return math.sqrt(total / self.frames) / 2147483648

    @property
    def peak(self):
        return max(abs(value) for value, in struct.iter_unpack('<i', self.pcm)) / 2147483648

    @property
    def dbfs(self):
        level = self.rms
        return 20 * math.log10(level) if level else -math.inf


class Microphone:
    """Explicit finite capture. Construction does not record; with/start does.

    A separate helper owns the ALSA route. Closing its control pipe, including
    after parent death, ends capture and restores controls. Killing the helper
    itself or losing power cannot guarantee mixer restoration.
    """
    def __init__(self, *, card=None, seconds=60):
        if type(seconds) is not int or not 1 <= seconds <= 300:
            raise ValueError('Capture seconds must be an integer in 1..300')
        if card is not None and (not isinstance(card, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', card)):
            raise ValueError('Choose a discovered ALSA card identifier')
        self.card, self.seconds = card, seconds
        self.process = None
        self.buffer = bytearray()
        self.identity = None
        self.ended = False

    def start(self):
        if self.process is not None:
            return self
        capabilities = audio_capabilities(card=self.card)
        if not capabilities['available']:
            raise MicrophoneUnavailable(capabilities['reason'])
        source = next(s for s in capabilities['sources'] if s['accessible'])
        from .runtime import pinned_python, process_lease
        # Pin the worker to this package, even if current moves during a release.
        bootstrap = ('import sys;sys.path.insert(0,sys.argv.pop(1));'
                     'from torque._audio_worker import main;raise SystemExit(main())')
        command = [pinned_python(), '-c', bootstrap, str(Path(__file__).resolve().parent.parent),
                   '--card', source['card'], '--seconds', str(self.seconds)]
        self.buffer.clear()
        self.ended = False
        # Keep update admission and this release alive until helper cleanup ends,
        # including after its client dies and releases the client's own leases.
        with process_lease(live=True) as descriptors:
            options = {'pass_fds': descriptors} if descriptors else {}
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, bufsize=0, start_new_session=True, **options)
        try:
            header = bytearray()
            deadline = time.monotonic() + 10
            while not header.endswith(b'\n'):
                if len(header) >= 4096:
                    raise AudioError('Invalid capture helper reply')
                data = self._receive(1, deadline)
                if not data:
                    self.close()
                    raise AudioError('Capture helper ended before readiness')
                header.extend(data)
            try:
                message = json.loads(header)
            except ValueError:
                raise AudioError('Invalid capture helper reply') from None
            if message != {'ready': True, 'sample_rate': RATE, 'channels': 1, 'format': FORMAT}:
                raise AudioError('Unexpected capture format')
            self.identity = source
            return self
        except BaseException:
            self.close()
            raise

    def _receive(self, size, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([self.process.stdout], [], [], max(0, remaining))[0]:
            raise TimeoutError('Microphone did not provide audio before the deadline')
        return os.read(self.process.stdout.fileno(), size)

    def read(self, *, frames=2400, timeout=2, latest=False):
        """Read PCM in order; latest=True discards queued older complete samples."""
        if type(frames) is not int or not 1 <= frames <= RATE:
            raise ValueError('Choose 1..48000 frames per read')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 5:
            raise ValueError('Audio timeout must be in (0, 5] seconds')
        if type(latest) is not bool:
            raise ValueError('latest must be boolean')
        if self.process is None:
            if self.ended:
                return None
            raise AudioError('Microphone is closed; call start or use its context manager')
        deadline = time.monotonic() + timeout
        needed = frames * 4
        while len(self.buffer) < needed:
            data = self._receive(needed - len(self.buffer), deadline)
            if not data:
                self.close()
                self.ended = True
                if not self.buffer:
                    return None
                if len(self.buffer) % 4:
                    raise AudioError('Capture ended with an incomplete sample')
                break
            self.buffer.extend(data)
        if latest and self.process is not None:
            budget = RATE * 4  # Bounded drain: at most one second of queued PCM.
            while budget and select.select([self.process.stdout], [], [], 0)[0]:
                data = os.read(self.process.stdout.fileno(), min(65536, budget))
                if not data:
                    self.close()
                    self.ended = True
                    if len(self.buffer) % 4:
                        raise AudioError('Capture ended with an incomplete sample')
                    break
                self.buffer.extend(data)
                budget -= len(data)
            complete = len(self.buffer) - len(self.buffer) % 4
            skip = max(0, complete - needed)
            del self.buffer[:skip]
        data = bytes(self.buffer[:needed])
        del self.buffer[:needed]
        return AudioChunk(data)

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        process.stdin.close()  # EOF asks the helper to stop and restore.
        deadline = time.monotonic() + 20
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([process.stdout], [], [], 0.05)[0]:
                os.read(process.stdout.fileno(), 65536)  # Discard, never persist audio.
        forced = False
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forced = True
                os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        diagnostic = process.stderr.read(8192).decode(errors='replace').strip()
        process.stdout.close()
        process.stderr.close()
        if forced:
            raise AudioError('Capture helper was killed; mixer restoration could not be verified')
        if process.returncode:
            kind = MicrophoneBusy if process.returncode == 3 else AudioError
            raise kind(diagnostic or 'Microphone capture or routing cleanup failed')

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
