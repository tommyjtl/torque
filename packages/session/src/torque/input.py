"""Passive, project-scoped Keychron input. No capture files or OS input grabs."""
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import select
import stat
import struct
import sys

EVENT = struct.Struct('@llHHi')
NAME = 'Keychron K0 Max Keyboard'
IDENTITY = (5, 0x3434, 0x0a06)
DIGITS = {82: 'KP0', 79: 'KP1', 80: 'KP2', 81: 'KP3', 75: 'KP4',
          76: 'KP5', 77: 'KP6', 71: 'KP7', 72: 'KP8', 73: 'KP9'}
NUMBER_ROW = {index + 1: str(index) for index in range(1, 10)}
KEYS = {**DIGITS, **NUMBER_ROW, 1: 'ESC', 69: 'NUMLOCK', 96: 'KPENTER', 83: 'KPDOT',
        98: 'KPSLASH', 55: 'KPASTERISK', 74: 'KPMINUS', 78: 'KPPLUS',
        103: 'UP', 108: 'DOWN', 105: 'LEFT', 106: 'RIGHT', 102: 'HOME',
        107: 'END', 104: 'PAGEUP', 109: 'PAGEDOWN', 110: 'INSERT',
        111: 'DELETE', 15: 'TAB', 14: 'BACKSPACE',
        115: 'KNOB_UP', 114: 'KNOB_DOWN', 113: 'KNOB_PRESS'}


class KeypadUnavailable(RuntimeError):
    """No unique readable matching keypad; inspect input_capabilities()."""


class KeypadBusy(KeypadUnavailable):
    """Another cooperating project holds this keypad's advisory lease."""


class KeypadDisconnected(KeypadUnavailable):
    """The current reader is no longer usable; open a new one to reconnect."""


def _query(fd, number, size):
    import fcntl
    data = bytearray(size)
    fcntl.ioctl(fd, (2 << 30) | (size << 16) | (ord('E') << 8) | number, data, True)
    return bytes(data)


def _text(fd, number):
    return _query(fd, number, 256).split(b'\0', 1)[0].decode('utf8', errors='replace')


def _bits(data):
    return {index for index in range(len(data) * 8) if data[index // 8] & (1 << (index % 8))}


def _discover(address, sysfs, dev):
    if address is not None and (not isinstance(address, str) or not address or len(address) > 128):
        raise ValueError('Choose a nonempty discovered Bluetooth address')
    if sys.platform != 'linux':
        return []
    devices = []
    for event in sorted(Path(sysfs).glob('event*')):
        root = event / 'device'
        try:
            read = lambda name: (root / name).read_text().strip()
            identity = tuple(int(read('id/' + name), 16) for name in ('bustype', 'vendor', 'product'))
            uniq = read('uniq').lower()
            if read('name') != NAME or identity != IDENTITY or not uniq:
                continue
            if address is not None and uniq != address.lower():
                continue
            devices.append({'node': str(Path(dev) / event.name), 'name': NAME, 'address': uniq})
        except (OSError, ValueError):
            continue
    return devices[:16]


def _open(info):
    fd = os.open(info['node'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise OSError('Input node is not a character device')
        identity = struct.unpack('@HHHH', _query(fd, 0x02, 8))[:3]
        if identity != IDENTITY or _text(fd, 0x06) != NAME or _text(fd, 0x08).lower() != info['address']:
            raise OSError('Input identity changed while opening')
        keys = _bits(_query(fd, 0x21, 128))
        if not set(DIGITS) <= keys:
            raise OSError('Keyboard does not advertise the expected numpad')
        return fd, keys
    except BaseException:
        os.close(fd)
        raise


def input_capabilities(*, address=None, sysfs=Path('/sys/class/input'), dev=Path('/dev/input')):
    """Inspect identity/readability only. Never read events or held-key state."""
    devices = []
    for info in _discover(address, sysfs, dev):
        record = {**info, 'readable': False}
        try:
            fd, keys = _open(info)
            try:
                record.update(readable=True, advertised_keys=[KEYS[code] for code in sorted(keys & KEYS.keys())])
            finally:
                os.close(fd)
        except PermissionError:
            record['reason'] = 'Input read access denied; no permissions were changed'
        except OSError:
            record['reason'] = 'Input unavailable or identity verification failed'
        devices.append(record)
    count = sum(device['readable'] for device in devices)
    return {'available': count == 1, 'selection_required': count > 1, 'devices': devices,
            'reason': 'Linux evdev required' if sys.platform != 'linux' else
                      'Choose a Bluetooth address' if count > 1 else
                      'No readable matching keypad' if not count else None,
            'records_keystrokes': False, 'exclusive_os_grab': False}


@dataclass(frozen=True)
class KeyEvent:
    key: str | None
    action: str
    code: int | None = None


class _Decoder:
    def __init__(self, held=()):
        self.buffer = b''
        self.held = set(held) & KEYS.keys()
        self.blocked = set(self.held)
        self.suppressed = False

    def feed(self, data, resync):
        self.buffer += data
        events = []
        while len(self.buffer) >= EVENT.size:
            _, _, kind, code, value = EVENT.unpack(self.buffer[:EVENT.size])
            self.buffer = self.buffer[EVENT.size:]
            if (kind, code) == (0, 3):
                self.suppressed = True
                self.held.clear()
                self.blocked.clear()
                events.clear()
            elif self.suppressed:
                if (kind, code) == (0, 0):
                    self.held = set(resync()) & KEYS.keys()
                    self.blocked = set(self.held)
                    self.suppressed = False
                    events.append(KeyEvent(None, 'resync'))
            elif kind == 1 and code in KEYS:
                if value == 0:
                    if code in self.held and code not in self.blocked:
                        events.append(KeyEvent(KEYS[code], 'release', code))
                    self.held.discard(code)
                    self.blocked.discard(code)
                elif value == 1 and code not in self.held:
                    self.held.add(code)
                    events.append(KeyEvent(KEYS[code], 'press', code))
                elif value == 2 and code in self.held and code not in self.blocked:
                    events.append(KeyEvent(KEYS[code], 'repeat', code))
        return events


class Keypad:
    """Read one verified keypad with a per-account project lease; no OS grab.

    poll() exposes press/release/repeat and resync events. is_down() excludes
    keys held before opening or resynchronizing until they are released.
    """
    def __init__(self, address=None, *, sysfs=Path('/sys/class/input'),
                 dev=Path('/dev/input'), lock_dir=None):
        self.fd = self.lease = None
        self.decoder = _Decoder()
        opened = []
        try:
            for info in _discover(address, sysfs, dev):
                try:
                    fd, _ = _open(info)
                    opened.append((fd, info))
                except OSError:
                    continue
            if len(opened) != 1:
                raise KeypadUnavailable('Choose a Bluetooth address' if len(opened) > 1 else
                                        'No readable Keychron keypad; wake it and check input_capabilities()')
            self.fd, self.identity = opened.pop()
            self._claim(Path(lock_dir) if lock_dir is not None else Path.home() / '.cache/torque/input')
            self.decoder = _Decoder(_bits(_query(self.fd, 0x18, 128)))
        except OSError:
            self.close()
            raise KeypadUnavailable('Keypad or private input lease unavailable; no access settings were changed') from None
        except BaseException:
            self.close()
            raise
        finally:
            for fd, _ in opened:
                os.close(fd)

    def _claim(self, directory):
        import fcntl
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise KeypadUnavailable('Input lease directory must be owner-only')
        name = hashlib.sha256(self.identity['address'].encode()).hexdigest()[:24] + '.lock'
        fd = os.open(directory / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise KeypadUnavailable('Input lease file must be owner-only')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise KeypadBusy('Another Torque project owns this keypad') from None
            self.lease = fd
        except BaseException:
            os.close(fd)
            raise

    @property
    def held(self):
        return frozenset(KEYS[code] for code in self.decoder.held - self.decoder.blocked)

    def is_down(self, key):
        return key in self.held

    def poll(self, timeout=0.02):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 1:
            raise ValueError('Input timeout must be 0..1 seconds')
        if self.fd is None:
            raise KeypadDisconnected('Keypad is closed; open a new reader to reconnect')
        try:
            if not select.select([self.fd], [], [], timeout)[0]:
                return []
            data = os.read(self.fd, 4096)
            if not data:
                raise OSError('Input disconnected')
            return self.decoder.feed(data, lambda: _bits(_query(self.fd, 0x18, 128)))
        except BlockingIOError:
            return []
        except OSError:
            self.close()
            raise KeypadDisconnected('Keypad disconnected; held state cleared') from None

    def close(self):
        for name in ('fd', 'lease'):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)
        self.decoder = _Decoder()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
