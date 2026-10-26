"""Versioned telemetry decoding and a bounded asynchronous observation connection."""
import copy
import base64
import binascii
import json
import queue
import secrets
import threading
import time
from .client import ControllerError, FirmwareError, integer
from .matrix import Frame

UINT32 = 0xffffffff
OPERATIONS = {1: 'rgb.set', 2: 'matrix.draw', 3: 'matrix.clear', 4: 'matrix.stop',
              5: 'matrix.begin', 6: 'matrix.write_frame', 7: 'matrix.commit',
              8: 'matrix.abort', 9: 'matrix.play', 10: 'matrix.draw_gray',
              11: 'matrix.begin_gray', 12: 'matrix.write_gray',
              13: 'matrix.cache', 14: 'matrix.play_cached'}
CAUSES = {0: 'command', 1: 'playback', 2: 'readback'}


def number(data, key, maximum=UINT32, minimum=0):
    try:
        return integer(data.get(key), minimum, maximum, key)
    except (AttributeError, ValueError) as error:
        raise FirmwareError('Invalid telemetry numeric field: ' + key) from error


def boolean(data, key):
    if type(data.get(key)) is not bool:
        raise FirmwareError('Invalid telemetry boolean field: ' + key)
    return data[key]


def common(data):
    if not isinstance(data, dict) or type(data.get('v')) is not int or data['v'] not in (1, 2):
        raise FirmwareError('Unsupported telemetry schema.')
    return {'schema_version': data['v'], 'boot_id': number(data, 'b', 2147483647, 1),
            'sequence': number(data, 's'), 'revision': number(data, 'r'),
            'timestamp_ms': number(data, 't'), 'command_id': number(data, 'c')}


def rgb_state(led, requested, pins):
    try:
        integer(requested, 0, 7, 'requested RGB mask')
        integer(pins, -1, 7, 'GPIO mask')
    except ValueError as error:
        raise FirmwareError('Invalid RGB telemetry masks.') from error
    names = ('red', 'green', 'blue')
    return {'id': led, 'requested': {name: bool(requested & (1 << i)) for i, name in enumerate(names)},
            'readback': {name: not bool(pins & (1 << i)) for i, name in enumerate(names)} if pins >= 0 else None,
            'raw_gpio': {name: int(bool(pins & (1 << i))) for i, name in enumerate(names)} if pins >= 0 else None,
            'readback_valid': pins >= 0,
            'requested_source': 'last_accepted_command', 'readback_source': 'gpio_readback',
            'binary': True}


def matrix_state(data):
    bits = 1
    preset = number(data, 'j', 9) if 'j' in data else 0
    if data.get('v') == 2:
        fields = data.get('m')
        if not isinstance(fields, list) or len(fields) != 6 or not isinstance(fields[0], str) or len(fields[0]) != 52:
            raise FirmwareError('Invalid grayscale telemetry fields.')
        try:
            packed = base64.b64decode(fields[0], validate=True)
        except (ValueError, binascii.Error) as error:
            raise FirmwareError('Invalid grayscale telemetry encoding.') from error
        if len(packed) != 39:
            raise FirmwareError('Invalid grayscale telemetry frame length.')
        data = dict(zip(('f', 'p', 'i', 'n', 'a', 'u'), [packed.hex(), *fields[1:]]))
        bits = 3
    try:
        frame = Frame.from_hex(data.get('f'), bits=bits)
    except (ValueError, TypeError) as error:
        raise FirmwareError('Invalid telemetry framebuffer.') from error
    count = number(data, 'n', 32)
    index = number(data, 'i', max(0, count - 1))
    rows = [''.join((str(p) if p else '.') if bits == 3 else ('#' if p else '.')
                    for p in frame.pixels[r * 13:(r + 1) * 13]) for r in range(8)]
    return {'frame_hex': frame.to_hex(), 'bits': bits, 'rows': rows, 'source': 'firmware_framebuffer', 'preset': preset,
            'playing': boolean(data, 'p'), 'frame_index': index, 'frame_count': count,
            'committed_id': number(data, 'a', 2147483647), 'upload_id': number(data, 'u', 2147483647)}


def decode_snapshot(data):
    out = common(data)
    colors = data.get('rgb')
    if not isinstance(colors, list) or len(colors) != 2 or any(not isinstance(c, list) or len(c) != 2 for c in colors):
        raise FirmwareError('Invalid RGB snapshot.')
    out['rgb'] = {str(led): rgb_state(led, *colors[led - 3]) for led in (3, 4)}
    out['matrix'] = matrix_state(data)
    out['stale'] = False
    return out


def decode_event(raw):
    if not isinstance(raw, str) or len(raw) > 215:
        raise FirmwareError('Invalid telemetry event payload.')
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise FirmwareError('Invalid telemetry event JSON.') from error
    out = common(data)
    out['subscription_id'] = number(data, 'h', 2147483647, 1)
    cause = number(data, 'o', 2)
    out['cause'] = CAUSES[cause]
    kind = data.get('k')
    if kind in ('r3', 'r4'):
        led = 3 if kind == 'r3' else 4
        out.update(kind='rgb', component='rgb.' + str(led), state=rgb_state(led, data.get('q'), data.get('g')))
    elif kind == 'm':
        out.update(kind='matrix', component='matrix', state=matrix_state(data))
    elif kind == 'e':
        code = number(data, 'e', -1, -6)
        op = number(data, 'z', 14, 1)
        out.update(kind='error', component='controller', code=code, operation=OPERATIONS[op])
    else:
        raise FirmwareError('Unknown telemetry event kind.')
    return out


def decode_health(data):
    if not isinstance(data, dict) or type(data.get('v')) is not int or data['v'] != 1:
        raise FirmwareError('Unsupported health schema.')
    return {'schema_version': 1, 'boot_id': number(data, 'b', 2147483647, 1),
            'uptime_ms': number(data, 'up', (1 << 64) - 1), 'revision': number(data, 'r'),
            'event_sequence': number(data, 's'), 'command_id': number(data, 'c'),
            'last_result': number(data, 'e', 0, -6),
            'last_operation': OPERATIONS.get(number(data, 'op', 14), 'none'),
            'observer_active': boolean(data, 'active'), 'queue_depth': number(data, 'q', 8),
            'queue_capacity': 8, 'events_dropped': number(data, 'd'),
            'notifications_sent': number(data, 'sent')}


def newer(value, previous):
    delta = (value - previous) & UINT32
    return 0 < delta < 0x80000000


class Watcher:
    """One passive observer; callbacks enqueue and the worker owns all RPC work."""
    def __init__(self, parent, *, queue_size=64, reconnect_attempts=3, board_factory=None):
        integer(queue_size, 4, 4096, 'queue_size')
        integer(reconnect_attempts, 0, 100, 'reconnect_attempts')
        self._parent = parent
        if board_factory is None:
            from .client import Board
            board_factory = lambda: Board(timeout=parent.timeout)
        self._factory = board_factory
        self._raw = queue.Queue(queue_size)
        self._output = queue.Queue(queue_size)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._done = threading.Event()
        self._resync = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._connection = None
        self._thread = None
        self._failure = None
        self._endpoint = 'unoq.telemetry.v1.' + secrets.token_hex(8)
        self._token = None
        self._boot = None
        self._sequence = None
        self._reconnect_attempts = reconnect_attempts
        self.local_drops = 0
        self._renew_seconds = 3.0

    @property
    def latest(self):
        with self._lock:
            return copy.deepcopy(self._latest)

    def _on_raw(self, payload):
        # Native Bridge forbids nested calls in provided handlers. Never call it here.
        try:
            self._raw.put_nowait(payload)
        except queue.Full:
            try:
                self._raw.get_nowait()
            except queue.Empty:
                pass
            self.local_drops += 1
            self._resync.set()
            try:
                self._raw.put_nowait(payload)
            except queue.Full:
                pass

    def _emit(self, event):
        event['received_at_monotonic'] = time.monotonic()
        try:
            self._output.put_nowait(event)
        except queue.Full:
            while True:
                try:
                    self._output.get_nowait()
                    self.local_drops += 1
                except queue.Empty:
                    break
            self._output.put_nowait({'kind': 'gap', 'reason': 'consumer_overflow', 'local_drops': self.local_drops})
            self._output.put_nowait(event)
            self._resync.set()

    def _snapshot(self, reason):
        snapshot = self._connection.snapshot()
        with self._lock:
            self._latest = snapshot
        # Heartbeats reconcile state without discarding queued non-state events.
        if reason != 'heartbeat' or self._sequence is None:
            self._sequence = snapshot['sequence']
        self._boot = snapshot['boot_id']
        self._emit({'kind': 'snapshot', 'reason': reason, 'state': copy.deepcopy(snapshot)})

    def _attach(self):
        previous_boot, previous_token = self._boot, self._token
        connection = self._factory()
        self._connection = connection
        connection.connect()
        capability = connection._require_telemetry()
        self._renew_seconds = capability['lease_ms'] / 1000 * 0.3
        connection._transport.provide(self._endpoint, self._on_raw)
        boot = connection.info()['boot_id']
        self._token = None
        if previous_boot == boot and previous_token is not None:
            try:
                connection._observe('system.renew', previous_token)
                self._token = previous_token
            except ControllerError:
                pass
        if self._token is None:
            self._token = connection._observe('system.subscribe', self._endpoint)
        self._snapshot('initial' if previous_boot is None else 'reconnect')
        if previous_boot is not None:
            self._emit({'kind': 'reconnected', 'boot_id': boot, 'previous_boot_id': previous_boot})

    def _detach(self, unsubscribe):
        connection = self._connection
        if connection is None:
            return
        try:
            if unsubscribe and self._token is not None:
                try:
                    connection._observe('system.unsubscribe', self._token)
                except ControllerError:
                    pass
        finally:
            connection.close()  # releases the callback route even on older routers
            self._connection = None

    def _accept(self, raw):
        event = decode_event(raw)
        if event['boot_id'] != self._boot or event['subscription_id'] != self._token:
            return
        sequence = event['sequence']
        if not newer(sequence, self._sequence):
            return
        if ((sequence - self._sequence) & UINT32) != 1:
            self._emit({'kind': 'gap', 'reason': 'sequence_gap', 'previous_sequence': self._sequence, 'sequence': sequence})
            self._snapshot('sequence_gap')
            return
        self._sequence = sequence
        with self._lock:
            latest = self._latest
            old_revision = event['revision'] != latest['revision'] and not newer(event['revision'], latest['revision'])
            if old_revision and event['kind'] != 'error':
                return
            for field in ('sequence', 'revision', 'timestamp_ms', 'command_id'):
                if newer(event[field], latest[field]):
                    latest[field] = event[field]
            if event['kind'] == 'rgb':
                latest['rgb'][str(event['state']['id'])] = copy.deepcopy(event['state'])
            elif event['kind'] == 'matrix':
                latest['matrix'] = copy.deepcopy(event['state'])
            else:
                latest['last_error'] = {'code': event['code'], 'operation': event['operation'],
                                        'command_id': event['command_id']}
        self._emit(event)

    def _run(self):
        try:
            self._attach()
            self._ready.set()
            renew_at = time.monotonic() + self._renew_seconds
            while not self._stop.is_set():
                try:
                    if self._resync.is_set():
                        self._resync.clear()
                        self._emit({'kind': 'gap', 'reason': 'local_overflow_or_invalid_event', 'local_drops': self.local_drops})
                        self._snapshot('local_resync')
                    try:
                        raw = self._raw.get(timeout=0.1)
                    except queue.Empty:
                        raw = None
                    if raw is not None:
                        try:
                            self._accept(raw)
                        except FirmwareError:
                            self._resync.set()
                    if time.monotonic() >= renew_at:
                        self._connection._observe('system.renew', self._token)
                        self._snapshot('heartbeat')
                        renew_at = time.monotonic() + self._renew_seconds
                except ControllerError:
                    with self._lock:
                        if self._latest is not None:
                            self._latest['stale'] = True
                    self._emit({'kind': 'disconnected', 'boot_id': self._boot})
                    self._detach(False)
                    for attempt in range(self._reconnect_attempts):
                        if self._stop.wait(min(0.25 * 2 ** attempt, 2)):
                            return
                        try:
                            self._attach()
                            renew_at = time.monotonic() + self._renew_seconds
                            break
                        except ControllerError:
                            self._detach(False)
                    else:
                        raise ControllerError('Telemetry reconnect attempts exhausted; cached state is stale.')
        except Exception as error:
            self._failure = error if isinstance(error, ControllerError) else ControllerError('Telemetry worker failed: ' + type(error).__name__)
            self._emit({'kind': 'disconnected', 'fatal': True, 'error': str(self._failure)})
        finally:
            try:
                self._detach(True)
            finally:
                self._ready.set()
                self._done.set()

    def start(self):
        if self._stop.is_set():
            raise ControllerError('Observer has been closed.')
        if self._thread is not None:
            raise ControllerError('Observer has already been started.')
        self._thread = threading.Thread(target=self._run, name='unoq-telemetry', daemon=True)
        self._thread.start()
        if not self._ready.wait(self._parent.timeout * 3 + 1):
            self.close()
            raise ControllerError('Telemetry startup timed out.')
        if self._failure is not None:
            self.close()
            raise self._failure
        return self

    def get(self, timeout=None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            if self._done.is_set() and self._output.empty():
                if self._failure is not None:
                    raise self._failure
                raise StopIteration
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return self._output.get_nowait()
            try:
                return self._output.get(timeout=0.2 if remaining is None else min(0.2, remaining))
            except queue.Empty:
                if deadline is not None and time.monotonic() >= deadline:
                    raise

    def __iter__(self):
        while True:
            try:
                yield self.get(timeout=0.2)
            except queue.Empty:
                continue
            except StopIteration:
                return

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._parent.timeout + 1)
            if self._thread.is_alive() and self._connection is not None:
                self._connection._transport.disconnect()  # abort blocked registration/RPC
                self._thread.join(timeout=self._parent.timeout + 3)

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
