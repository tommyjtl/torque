"""Bounded Bridge calls, firmware identity checks, and cooperative writer locking."""
import json
import copy
import math
import os
from pathlib import Path
import stat
import threading

PREFIX = 'unoq.control.v1.'
ERRORS = {-1: 'invalid arguments', -2: 'controller resource is busy',
          -3: 'stale boot or upload identifier', -4: 'incomplete animation',
          -5: 'unsupported capability', -6: 'controller capacity exhausted'}


class ControllerError(RuntimeError):
    """A controlled failure; device operations are never retried automatically."""


class FirmwareError(ControllerError):
    pass


class ResetError(ControllerError):
    pass


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer in {low}..{high}')
    return value


class Board:
    def __init__(self, *, timeout=3.0, transport=None, lock_dir=None):
        if not isinstance(timeout, (float, int)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError('timeout must be in (0, 60] seconds')
        self.timeout = timeout
        self._transport = transport
        self._connected = False
        self._boot = None
        self._guard = threading.RLock()
        self._lock_file = None
        self._capabilities = {}
        self._observers = []
        self._lock_dir = Path(lock_dir) if lock_dir else Path.home() / '.cache/unoq-control'
        from .matrix import Matrix
        self.matrix = Matrix(self)

    def connect(self):
        with self._guard:
            if self._connected:
                return self
            if self._transport is None:
                socket_path = Path('/var/run/arduino-router.sock')
                if not socket_path.exists():
                    raise ControllerError('Local Arduino Router socket is missing. Check the existing router service.')
                if not os.access(socket_path, os.W_OK):
                    raise ControllerError('Access denied to /var/run/arduino-router.sock. Ask the board administrator for intended router access; no permissions were changed.')
                try:
                    from arduino.router_bridge import Bridge
                except ImportError as error:
                    raise ControllerError('Native Bridge is missing. Run scripts/prepare-controller.py --client on the board.') from error
                self._transport = Bridge(max_message_size=1024, max_pending_handlers=8)
            try:
                if not self._transport.connect(timeout=self.timeout):
                    raise ControllerError('Timed out connecting to the local Arduino Router.')
                self._connected = True
                self._boot = self.info()['boot_id']
                return self
            except BaseException:
                self.close()
                raise

    def _call(self, suffix, *args):
        if not self._connected:
            raise ControllerError('Connect to the controller first (use with Board() as board).')
        try:
            return self._transport.call(PREFIX + suffix, *args, timeout=self.timeout)
        except TimeoutError as error:
            raise ControllerError('Controller call timed out; its effect is unknown. No retry was sent.') from error
        except (ConnectionError, OSError) as error:
            raise ControllerError('Arduino Router connection failed; reconnect and recheck firmware identity.') from error
        except RuntimeError as error:
            raise ControllerError('Bridge could not send the request; check the router connection. No retry was sent.') from error
        except ValueError as error:
            code = getattr(error, 'code', None)
            if code in (2, 254):
                raise FirmwareError('Base controller RPC is unavailable. Check installed firmware; no upload was attempted.') from error
            raise ControllerError(f'Bridge rejected the RPC (code {code if isinstance(code, int) else "unknown"}).') from error

    def _json(self, suffix, *args):
        value = self._call(suffix, *args)
        if not isinstance(value, str) or len(value) > 512:
            raise FirmwareError('Invalid controller reply.')
        try:
            return json.loads(value)
        except ValueError as error:
            raise FirmwareError('Invalid controller JSON reply.') from error

    def info(self):
        with self._guard:
            value = self._json('system.info')
            if (not isinstance(value, dict) or value.get('name') != 'base-controller' or
                not isinstance(value.get('protocol'), list) or len(value['protocol']) != 2 or
                type(value['protocol'][0]) is not int or value['protocol'][0] != 1 or
                type(value['protocol'][1]) is not int or value['protocol'][1] < 0 or
                not isinstance(value.get('version'), str) or
                value.get('ready') is not True or
                type(value.get('boot_id')) is not int or not 1 <= value['boot_id'] <= 2147483647):
                raise FirmwareError('Unexpected firmware or protocol version; no control command was sent.')
            if self._boot is not None and self._boot != value['boot_id']:
                raise ResetError('MCU restarted. Close and reconnect; upload animation data again.')
            return value

    def capability(self, name):
        if name not in ('matrix', 'matrix-grayscale', 'matrix-presets', 'rgb', 'display-lease', 'telemetry'):
            raise ValueError('Unknown capability name')
        with self._guard:
            if name in self._capabilities:
                return copy.deepcopy(self._capabilities[name])
            value = self._json('system.capability', name)
            if value is not None and not isinstance(value, dict):
                raise FirmwareError('Invalid capability reply.')
            self._capabilities[name] = value
            return copy.deepcopy(value)

    def _require_telemetry(self):
        capability = self.capability('telemetry')
        if not isinstance(capability, dict) or type(capability.get('schema')) is not int or capability['schema'] != 1:
            raise FirmwareError('Telemetry is unavailable. Firmware 0.2.0 or newer is required; no upload was attempted.')
        try:
            integer(capability.get('lease_ms'), 1000, 60000, 'observer lease')
        except ValueError as error:
            raise FirmwareError('Invalid telemetry lease capability.') from error
        return capability

    def snapshot(self):
        from .telemetry import decode_snapshot
        with self._guard:
            self._require_telemetry()
            value = decode_snapshot(self._json('system.snapshot'))
            if value['boot_id'] != self._boot:
                self.info()
                raise FirmwareError('Snapshot boot identity mismatch.')
            return value

    def health(self):
        from .telemetry import decode_health
        with self._guard:
            self._require_telemetry()
            value = decode_health(self._json('system.health'))
            if value['boot_id'] != self._boot:
                self.info()
                raise FirmwareError('Health boot identity mismatch.')
            return value

    def watch(self, **options):
        from .telemetry import Watcher
        watcher = Watcher(self, **options)
        with self._guard:
            self._observers.append(watcher)
        return watcher

    def _writer(self):
        if self._lock_file is not None:
            return
        import fcntl
        self._lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self._lock_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ControllerError('Controller lock directory must be an owner-only directory.')
        fd = os.open(self._lock_dir / 'controller.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ControllerError('Controller lock must be an owner-only regular file.')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ControllerError('Another cooperating program owns the MCU. Close it before controlling LEDs.') from error
            self._lock_file = os.fdopen(fd, 'a')
        except BaseException:
            os.close(fd)
            raise

    def _mutate(self, suffix, *args):
        return self._control(suffix, args, writer=True)

    def _observe(self, suffix, *args):
        return self._control(suffix, args, writer=False)

    def _control(self, suffix, args, writer):
        with self._guard:
            if not self._connected:
                raise ControllerError('Connect to the controller first.')
            if writer:
                self._writer()
            result = self._call(suffix, self._boot, *args)
            if type(result) is not int:
                raise FirmwareError('Invalid control acknowledgment.')
            if result < 0:
                if result == -3:
                    self.info()  # distinguishes a boot change from an expired upload
                if not writer and result == -2:
                    raise ControllerError('Another telemetry observer is active.')
                if not writer and result == -3:
                    raise ControllerError('Telemetry subscription expired or its token is stale.')
                raise ControllerError(ERRORS.get(result, 'unknown controller error'))
            if suffix not in ('matrix.begin', 'matrix.begin_gray', 'system.subscribe') and result != 0:
                raise FirmwareError('Unexpected control acknowledgment.')
            if suffix == 'system.subscribe' and not 1 <= result <= 2147483647:
                raise FirmwareError('Invalid observer identifier.')
            return result

    def rgb(self, led):
        if led == 'linux-user':
            from .leds import UserLed
            return UserLed()
        integer(led, 3, 4, 'MCU LED identifier')
        return Rgb(self, led)

    def close(self):
        with self._guard:
            observers, self._observers = self._observers, []
        for watcher in observers:
            watcher.close()
        with self._guard:
            try:
                if self._transport is not None:
                    self._transport.disconnect()
            finally:
                self._connected = False
                self._boot = None
                self._capabilities.clear()
                if self._lock_file is not None:
                    self._lock_file.close()
                    self._lock_file = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()


class Rgb:
    def __init__(self, board, led):
        self._board, self._led = board, led

    def set(self, r, g, b):
        if any(type(value) is not bool for value in (r, g, b)):
            raise ValueError('RGB channels must be booleans; PWM dimming is not supported')
        capability = self._board.capability('rgb')
        if not isinstance(capability, dict) or self._led not in capability.get('ids', []) or capability.get('binary') is not True:
            raise FirmwareError('MCU RGB capability is unavailable.')
        self._board._mutate('rgb.set', self._led, r, g, b)

    def status(self):
        return self._board.snapshot()['rgb'][str(self._led)]
