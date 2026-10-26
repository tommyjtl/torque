"""Explicit binary/grayscale frames and transactional animation uploads."""
from dataclasses import dataclass
from itertools import islice
from .client import ControllerError, FirmwareError, integer


@dataclass(frozen=True)
class Frame:
    pixels: tuple
    bits: int = 1

    def __post_init__(self):
        pixels = tuple(islice(iter(self.pixels), 105))
        if type(self.bits) is not int or self.bits not in (1, 3):
            raise ValueError('Frame bits must be 1 (binary) or 3 (grayscale)')
        maximum = (1 << self.bits) - 1
        if len(pixels) != 104 or any(type(p) is not int or not 0 <= p <= maximum for p in pixels):
            raise ValueError(f'A frame needs exactly 104 integer pixels, each 0..{maximum}')
        object.__setattr__(self, 'pixels', pixels)

    @classmethod
    def from_hex(cls, value, *, bits=1):
        if type(bits) is not int or bits not in (1, 3):
            raise ValueError('Frame bits must be 1 or 3')
        if not isinstance(value, str) or len(value) != 26 * bits or set(value) - set('0123456789abcdefABCDEF'):
            raise ValueError(f'A packed frame needs exactly {26 * bits} hexadecimal characters')
        packed = int(value, 16)
        return cls(tuple((packed >> ((103 - i) * bits)) & ((1 << bits) - 1) for i in range(104)), bits=bits)

    @classmethod
    def from_rows(cls, rows, *, bits=1):
        if type(bits) is not int or bits not in (1, 3):
            raise ValueError('Frame bits must be 1 or 3')
        rows = list(islice(iter(rows), 9))
        allowed = '.#01' if bits == 1 else '.01234567'
        if len(rows) != 8 or any(not isinstance(row, str) or len(row) != 13 or set(row) - set(allowed) for row in rows):
            raise ValueError(f'Use 8 strings of 13 characters from {allowed}')
        return cls(tuple(int(c in '#1') if bits == 1 else int(c) if c != '.' else 0
                         for row in rows for c in row), bits=bits)

    def to_hex(self):
        packed = 0
        for value in self.pixels:
            packed = (packed << self.bits) | value
        return packed.to_bytes(13 * self.bits, 'big').hex()


class Matrix:
    def __init__(self, board):
        self._board = board

    def _limits(self, bits=1):
        limits = self._board.capability('matrix' if bits == 1 else 'matrix-grayscale')
        encoding = 'bitset-hex-msb' if bits == 1 else 'gray3-hex-msb'
        if (not isinstance(limits, dict) or
                (limits.get('rows'), limits.get('columns'), limits.get('encoding')) != (8, 13, encoding) or
                (bits == 3 and (limits.get('bits'), limits.get('max_value')) != (3, 7))):
            raise FirmwareError('Compatible matrix capability is unavailable' +
                                ('; grayscale requires controller 0.3.0 or newer.' if bits == 3 else '.'))
        try:
            integer(limits.get('max_frames'), 1, 32, 'max_frames')
            integer(limits.get('min_duration_ms'), 1, 60000, 'min_duration_ms')
            integer(limits.get('max_duration_ms'), limits['min_duration_ms'], 60000, 'max_duration_ms')
        except ValueError as error:
            raise FirmwareError('Invalid matrix limits.') from error
        return limits

    def draw(self, frame):
        frame = frame if isinstance(frame, Frame) else Frame(frame)
        self._limits(frame.bits)
        self._board._mutate('matrix.draw_gray' if frame.bits == 3 else 'matrix.draw', frame.to_hex())

    def clear(self):
        self._board._mutate('matrix.clear')

    def frame(self):
        state = self._board.snapshot()['matrix']
        return Frame.from_hex(state['frame_hex'], bits=state.get('bits', 1))

    def stop(self):
        self._board._mutate('matrix.stop')

    def status(self):
        with self._board._guard:
            value = self._board._json('matrix.status')
            if not isinstance(value, dict) or value.get('boot_id') != self._board._boot:
                self._board.info()
                raise FirmwareError('Invalid matrix status reply.')
            if (type(value.get('playing')) is not bool or
                any(type(value.get(k)) is not int or not 0 <= value[k] <= 2147483647
                    for k in ('frame', 'frames', 'upload_id', 'committed_id')) or
                not 0 <= value['frames'] <= 32 or
                not 0 <= value['frame'] < max(1, value['frames'])):
                raise FirmwareError('Invalid matrix status fields.')
            try:
                integer(value.get('preset', 0), 0, 9, 'selected preset')
            except ValueError as error:
                raise FirmwareError('Invalid matrix preset status.') from error
            return value

    def load(self, frames, durations=150):
        frames = [f if isinstance(f, Frame) else Frame(f) for f in islice(iter(frames), 33)]
        if not 1 <= len(frames) <= 32:
            raise ValueError('An animation needs 1..32 frames')
        bits = frames[0].bits
        if any(frame.bits != bits for frame in frames):
            raise ValueError('An animation must use one frame format throughout')
        if type(durations) is int:
            durations = [durations] * len(frames)
        else:
            durations = list(islice(iter(durations), 33))
        if len(durations) != len(frames):
            raise ValueError('Each frame needs one duration')
        for duration in durations:
            integer(duration, 20, 60000, 'frame duration in milliseconds')
        with self._board._guard:
            limits = self._limits(bits)
            if len(frames) > limits['max_frames'] or any(not limits['min_duration_ms'] <= d <= limits['max_duration_ms'] for d in durations):
                raise ValueError('Animation exceeds the connected firmware limits')
            upload = self._board._mutate('matrix.begin_gray' if bits == 3 else 'matrix.begin', len(frames))
            if not 1 <= upload <= 2147483647:
                raise FirmwareError('Invalid upload identifier.')
            try:
                for index, (frame, duration) in enumerate(zip(frames, durations)):
                    self._board._mutate('matrix.write_gray' if bits == 3 else 'matrix.write_frame',
                                        upload, index, frame.to_hex(), duration)
                self._board._mutate('matrix.commit', upload)
            except BaseException as error:
                if isinstance(error, ControllerError):
                    error.upload_id = upload
                try:
                    self._board._mutate('matrix.abort', upload)
                except ControllerError:
                    pass
                raise
            return upload

    def play(self, repeat=1):
        integer(repeat, 0, 65535, 'repeat count (0 explicitly loops)')
        self._board._mutate('matrix.play', repeat)

    def _preset_limits(self, slot):
        integer(slot, 1, 9, 'preset slot')
        limits = self._board.capability('matrix-presets')
        if not isinstance(limits, dict):
            raise FirmwareError('Resident presets require controller 0.4.0 or newer.')
        try:
            integer(limits.get('max_presets'), 1, 9, 'preset capacity')
            integer(limits.get('max_frames'), 1, 32, 'preset frame capacity')
        except ValueError as error:
            raise FirmwareError('Invalid resident preset capability.') from error
        if slot > limits['max_presets']:
            raise ValueError('Preset slot exceeds the connected controller capacity')

    def cache(self, slot):
        """Store the complete committed clip; this does not start playback."""
        self._preset_limits(slot)
        self._board._mutate('matrix.cache', slot)

    def play_cached(self, slot, repeat=1):
        """Select a resident clip without uploading its frames again."""
        integer(repeat, 0, 65535, 'repeat count (0 explicitly loops)')
        self._preset_limits(slot)
        self._board._mutate('matrix.play_cached', slot, repeat)
