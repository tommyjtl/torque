#!/usr/bin/env python3
"""Bounded, passive Linux input capture for one Bluetooth Keychron K0 Max."""
import argparse
from collections import Counter
import ctypes
import ctypes.util
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import struct
import sys
import time

EVENT = struct.Struct('@llHHi')
INPUT_ID = struct.Struct('@HHHH')
EV_SYN, EV_KEY, EV_REL, EV_ABS, EV_MSC = 0, 1, 2, 3, 4
SYN_REPORT, SYN_DROPPED, MSC_SCAN = 0, 3, 4


def utc():
    return datetime.now(timezone.utc).isoformat()


def request(number, size):
    # Linux generic/ARM64 input.h _IOR('E', number, size).
    return (2 << 30) | (size << 16) | (ord('E') << 8) | number


def query(fd, number, size=512):
    data = bytearray(size)
    fcntl.ioctl(fd, request(number, size), data, True)
    return data


def text_query(fd, number):
    return bytes(query(fd, number)).split(b'\0', 1)[0].decode('utf8', errors='replace')


def set_bits(data):
    return [i for i in range(len(data) * 8) if data[i // 8] & (1 << (i % 8))]


class Names:
    """Use evtest's installed libevdev names; numeric codes always remain present."""
    TYPES = {0: 'EV_SYN', 1: 'EV_KEY', 2: 'EV_REL', 3: 'EV_ABS', 4: 'EV_MSC',
             5: 'EV_SW', 17: 'EV_LED', 20: 'EV_REP'}
    def __init__(self):
        self.library = None
        try:
            name = ctypes.util.find_library('evdev')
            if name:
                self.library = ctypes.CDLL(name)
                self.library.libevdev_event_type_get_name.argtypes = [ctypes.c_uint]
                self.library.libevdev_event_type_get_name.restype = ctypes.c_char_p
                self.library.libevdev_event_code_get_name.argtypes = [ctypes.c_uint, ctypes.c_uint]
                self.library.libevdev_event_code_get_name.restype = ctypes.c_char_p
        except (OSError, AttributeError):
            self.library = None

    def type(self, value):
        result = self.library.libevdev_event_type_get_name(value) if self.library else None
        return result.decode() if result else self.TYPES.get(value, 'EV_' + str(value))

    def code(self, kind, value):
        result = self.library.libevdev_event_code_get_name(kind, value) if self.library else None
        return result.decode() if result else self.type(kind) + '_CODE_' + str(value)


def matches(info, address):
    return (info.get('name', '').startswith('Keychron K0 Max') and
            info.get('uniq', '').lower() == address.lower() and
            info.get('bus') == 5 and info.get('vendor') == 0x3434 and info.get('product') == 0x0a06)


def discover(address, sysfs=Path('/sys/class/input'), dev=Path('/dev/input')):
    devices = []
    for path in sorted(Path(sysfs).glob('event*')):
        root = path / 'device'
        try:
            read = lambda name: (root / name).read_text().strip()
            info = {'node': str(Path(dev) / path.name), 'name': read('name'),
                    'uniq': read('uniq'), 'phys': read('phys'),
                    **{key: int(read('id/' + attribute), 16) for key, attribute in
                       [('bus', 'bustype'), ('vendor', 'vendor'), ('product', 'product'), ('version', 'version')]}}
            if matches(info, address):
                devices.append(info)
        except (OSError, ValueError):
            continue
    return devices


def open_device(info, address, names):
    fd = os.open(info['node'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        bus, vendor, product, version = INPUT_ID.unpack(query(fd, 0x02, INPUT_ID.size))
        actual = {'node': info['node'], 'name': text_query(fd, 0x06),
                  'phys': text_query(fd, 0x07), 'uniq': text_query(fd, 0x08),
                  'bus': bus, 'vendor': vendor, 'product': product, 'version': version}
        if not matches(actual, address):
            raise RuntimeError('Input identity changed while opening the device')
        kinds = set_bits(query(fd, 0x20, 8))
        actual['capabilities'], actual['capability_queries_unavailable'] = {}, []
        for kind in kinds:
            if kind == EV_SYN:
                continue
            if kind == 20:  # EV_REP uses EVIOCGREP, not EVIOCGBIT(EV_REP).
                delay, period = struct.unpack('@II', query(fd, 0x03, 8))
                actual['repeat_settings_ms'] = {'delay': delay, 'period': period}
                actual['capabilities'][names.type(kind)] = [{'code': c, 'name': names.code(kind, c)} for c in (0, 1)]
                continue
            try:
                codes = set_bits(query(fd, 0x20 + kind, 128))
            except OSError as error:
                if error.errno != errno.EINVAL:
                    raise
                actual['capability_queries_unavailable'].append(names.type(kind))
                continue
            actual['capabilities'][names.type(kind)] = [{'code': code, 'name': names.code(kind, code)} for code in codes]
        identity = {key: actual[key] for key in ('name', 'uniq', 'phys', 'bus', 'vendor', 'product', 'version')}
        actual['interface_identity'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        held = set_bits(query(fd, 0x18, 128))  # EVIOCGKEY, no device write/grab.
        actual['initial_led_codes'] = set_bits(query(fd, 0x19, 16))
        return fd, actual, held
    except BaseException:
        os.close(fd)
        raise


class Decoder:
    def __init__(self):
        self.buffer = b''

    def feed(self, data):
        self.buffer += data
        while len(self.buffer) >= EVENT.size:
            yield EVENT.unpack(self.buffer[:EVENT.size])
            self.buffer = self.buffer[EVENT.size:]


class Recorder:
    def __init__(self, names):
        self.names = names
        self.held = {}
        self.down_at = {}
        self.keys = {}
        self.axes = {}
        self.absolute_axes = {}
        self.labels = []
        self.label = None
        self.chords = Counter()
        self.scans = {}
        self.suppressed = set()
        self.gaps = []
        self.event_count = 0

    def mark(self, label, elapsed):
        if self.label:
            self.label['end_ms'] = elapsed
        self.label = None
        if label is not None:
            self.label = {'label': label, 'start_ms': elapsed, 'end_ms': None,
                          'observed': [], 'sequence': [], 'events': 0, 'incomplete': False}
            self.labels.append(self.label)

    def gap(self, device, reason):
        self.gaps.append({'device_id': device, 'reason': reason})
        self.held[device] = set()
        self.scans.pop(device, None)
        for key in list(self.down_at):
            if key[0] == device:
                self.down_at.pop(key)
        if self.label:
            self.label['incomplete'] = True

    def sync(self, device, held):
        self.held[device] = set(held)
        self.suppressed.discard(device)

    def event(self, device, raw, elapsed):
        seconds, micros, kind, code, value = raw
        self.event_count += 1
        row = {'record': 'event', 'device_id': device, 'elapsed_ms': elapsed,
               'kernel_time': {'seconds': seconds, 'microseconds': micros},
               'type': kind, 'type_name': self.names.type(kind), 'code': code,
               'code_name': self.names.code(kind, code), 'value': value,
               'label': self.label['label'] if self.label else None,
               'trusted_state': device not in self.suppressed}
        if kind == EV_SYN and code == SYN_DROPPED:
            self.gap(device, 'SYN_DROPPED')
            self.suppressed.add(device)
            row['trusted_state'] = False
        if device in self.suppressed:
            return row
        if kind == EV_MSC and code == MSC_SCAN:
            self.scans[device] = value
            row['scan_hex'] = hex(value & 0xffffffff)
        if kind == EV_SYN and code == SYN_REPORT:
            self.scans.pop(device, None)
        if kind == EV_KEY and value in (0, 1, 2):
            key = (device, code)
            stats = self.keys.setdefault(key, {'device_id': device, 'code': code,
                'name': self.names.code(kind, code), 'presses': 0, 'releases': 0,
                'repeats': 0, 'cycles': 0, 'max_hold_ms': 0, 'scan_codes': []})
            stats[{0: 'releases', 1: 'presses', 2: 'repeats'}[value]] += 1
            row['action'] = {0: 'release', 1: 'press', 2: 'repeat'}[value]
            scan = self.scans.pop(device, None)
            if scan is not None:
                row['scan_hex'] = hex(scan & 0xffffffff)
                if row['scan_hex'] not in stats['scan_codes']:
                    stats['scan_codes'].append(row['scan_hex'])
            held = self.held.setdefault(device, set())
            if value == 1:
                held.add(code)
                self.down_at[key] = elapsed
            elif value == 0:
                held.discard(code)
                start = self.down_at.pop(key, None)
                if start is not None:
                    stats['cycles'] += 1
                    stats['max_hold_ms'] = max(stats['max_hold_ms'], max(0, elapsed - start))
            chord = sorted({self.names.code(EV_KEY, c) for codes in self.held.values() for c in codes})
            row['held_keys'] = chord
            if value == 1 and len(chord) > 1:
                self.chords[tuple(chord)] += 1
        elif kind == EV_REL and value:
            key = (device, code)
            stats = self.axes.setdefault(key, {'device_id': device, 'code': code,
                'name': self.names.code(kind, code), 'events': 0, 'positive': 0, 'negative': 0, 'sum': 0})
            stats['events'] += 1
            stats['positive' if value > 0 else 'negative'] += 1
            stats['sum'] += value
        elif kind == EV_ABS:
            stats = self.absolute_axes.setdefault((device, code), {'device_id': device, 'code': code,
                'name': self.names.code(kind, code), 'events': 0, 'minimum': value, 'maximum': value, 'last': value})
            stats.update(events=stats['events'] + 1, minimum=min(stats['minimum'], value),
                         maximum=max(stats['maximum'], value), last=value)
        if self.label and (kind == EV_KEY and value == 1 or kind == EV_REL and value or kind == EV_ABS):
            signature = {'type': kind, 'code': code, 'name': row['code_name']}
            if kind == EV_REL:
                signature['direction'] = 1 if value > 0 else -1
            if signature not in self.label['observed']:
                self.label['observed'].append(signature)
            self.label['events'] += 1
        if self.label and kind in (EV_KEY, EV_REL, EV_ABS):
            self.label['sequence'].append({'device_id': device, 'type': kind, 'code': code,
                                           'name': row['code_name'], 'value': value})
        return row

    def summary(self):
        labels = []
        for item in self.labels:
            result = dict(item)
            result['status'] = ('incomplete' if item['incomplete'] else
                                'observed' if item['observed'] else 'no_linux_event_observed')
            labels.append(result)
        return {'raw_event_count': self.event_count, 'keys': list(self.keys.values()),
                'relative_axes': list(self.axes.values()), 'absolute_axes': list(self.absolute_axes.values()), 'labels': labels,
                'chords': [{'keys': list(keys), 'presses': count} for keys, count in self.chords.items()],
                'gaps': self.gaps,
                'held_at_end': {device: [self.names.code(EV_KEY, code) for code in sorted(codes)]
                                for device, codes in self.held.items() if codes}}


def private_json(path, data):
    with Path(path).open('x') as stream:
        os.chmod(path, 0o600)
        json.dump(data, stream, indent=2)


def report_text(summary):
    lines = ['# Keychron K0 Max observed Linux input', '',
             f"Profile: {summary['profile']}; stop: {summary['stop_reason']}", '',
             'These are observed Linux events. Advertised capabilities are not a physical-key checklist.', '',
             '| Interface | Linux key | Code | Press | Release | Repeat | Full cycles |',
             '|---|---|---:|---:|---:|---:|---:|']
    for key in summary['keys']:
        lines.append('| {device_id} | {name} | {code} | {presses} | {releases} | {repeats} | {cycles} |'.format(**key))
    lines += ['', '## Relative controls', '']
    lines.extend(f"- {axis['device_id']} {axis['name']} ({axis['code']}): positive {axis['positive']}, negative {axis['negative']}" for axis in summary['relative_axes'])
    lines += ['', '## Absolute controls', '']
    lines.extend(f"- {axis['device_id']} {axis['name']} ({axis['code']}): {axis['minimum']}..{axis['maximum']}; last {axis['last']}" for axis in summary['absolute_axes'])
    lines += ['', '## Labelled controls', '', '| Label | Observed press/axis codes | Result |', '|---|---|---|']
    for label in summary['labels']:
        name = label['label'].replace('|', '\\|').replace('\n', ' ')
        codes = ', '.join(item['name'] + (' +' if item.get('direction') == 1 else ' -' if item.get('direction') == -1 else '') for item in label['observed'])
        lines.append(f"| {name} | {codes} | {label['status']} |")
    lines += ['', 'A quiet label does not prove a key is unusable: Fn/layer functions may stay inside the keypad,',
              'or no physical input may have happened in that window. Disconnections and SYN_DROPPED invalidate state.',
              'Use labelled trials to distinguish physical macro buttons which send the same codes.', '']
    return '\n'.join(lines)


def capture(args, names):
    if args.guided and not sys.stdin.isatty():
        raise RuntimeError('--guided requires an interactive SSH/local terminal')
    output = args.output.expanduser()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw = (output / 'events.jsonl').open('x', buffering=1)
    os.chmod(output / 'events.jsonl', 0o600)
    selector = selectors.DefaultSelector()
    recorder, clients, devices = Recorder(names), {}, []
    start = time.monotonic()
    elapsed = lambda: round((time.monotonic() - start) * 1000, 3)
    emit = lambda value: raw.write(json.dumps(value, ensure_ascii=True) + '\n')
    reason, first_connected, scanned_at = 'duration', None, 0
    started = utc()
    stop = False
    def interrupted(_signal, _frame):
        nonlocal stop, reason
        stop, reason = True, 'interrupted'
    original = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    if args.guided:
        selector.register(sys.stdin, selectors.EVENT_READ, 'label')
        print('Type a physical control label on this terminal, press Enter, then operate it on the K0 Max.\n'
              'Examples: M1, numpad 7, knob clockwise, Fn + 1. A blank line finishes.\nlabel> ', end='', flush=True)
    try:
        while not stop:
            now = time.monotonic()
            if first_connected is None and now - start >= args.wait:
                reason = 'device_wait_timeout'
                break
            if first_connected is not None and now - first_connected >= args.duration:
                break
            if now - scanned_at >= 1:
                scanned_at = now
                for info in discover(args.address):
                    if info['node'] in clients:
                        continue
                    fd, actual, held = open_device(info, args.address, names)
                    identifier = 'd' + str(len(devices) + 1).zfill(3)
                    actual.update(device_id=identifier, connected_at=utc(), initial_held=held)
                    devices.append(actual)
                    clients[info['node']] = {'fd': fd, 'id': identifier, 'decoder': Decoder()}
                    selector.register(fd, selectors.EVENT_READ, info['node'])
                    recorder.sync(identifier, held)
                    emit({'record': 'device.connected', 'elapsed_ms': elapsed(), 'device': actual})
                    first_connected = first_connected or now
                    print('\nConnected: ' + actual['name'] + ' (' + actual['node'] + ')', flush=True)
            for ready, _ in selector.select(.2):
                node = ready.data
                if node == 'label':
                    label = sys.stdin.readline()
                    if not label or not label.strip():
                        reason, stop = 'guided_finished', True
                        break
                    label = label.strip()
                    if len(label) > 100 or any(ord(c) < 32 for c in label):
                        print('Use a label of 1..100 printable characters.\nlabel> ', end='', flush=True)
                        continue
                    recorder.mark(label, elapsed())
                    emit({'record': 'label', 'elapsed_ms': elapsed(), 'label': label})
                    print('Recording: ' + label + '\nlabel> ', end='', flush=True)
                    continue
                client = clients[node]
                try:
                    data = os.read(client['fd'], EVENT.size * 256)
                    if not data:
                        raise OSError(errno.ENODEV, 'Input disconnected')
                except BlockingIOError:
                    continue
                except OSError as error:
                    if error.errno not in (errno.ENODEV, errno.EIO, errno.ENXIO):
                        raise
                    recorder.gap(client['id'], 'device_disconnected')
                    emit({'record': 'device.disconnected', 'elapsed_ms': elapsed(), 'device_id': client['id']})
                    selector.unregister(client['fd'])
                    os.close(client['fd'])
                    del clients[node]
                    print('\nDisconnected: ' + node + '; waiting for the same Bluetooth identity.', flush=True)
                    continue
                for event in client['decoder'].feed(data):
                    row = recorder.event(client['id'], event, elapsed())
                    emit(row)
                    if client['id'] in recorder.suppressed and event[2:4] == (EV_SYN, SYN_REPORT):
                        held = set_bits(query(client['fd'], 0x18, 128))
                        recorder.sync(client['id'], held)
                        emit({'record': 'state.resync', 'elapsed_ms': elapsed(), 'device_id': client['id'], 'held_codes': held})
                    if row['trusted_state'] and row['type'] in (EV_KEY, EV_REL):
                        print(f"{row['elapsed_ms']:9.1f} ms {client['id']} {row['code_name']} {row.get('action', 'delta')} {row['value']}", flush=True)
                    if recorder.event_count >= args.max_events:
                        reason, stop = 'event_limit', True
                        break
                if stop:
                    break
    except BaseException:
        reason = 'error'
        raise
    finally:
        recorder.mark(None, elapsed())
        for client in clients.values():
            selector.unregister(client['fd'])
            os.close(client['fd'])
        selector.close()
        for sig, handler in original.items():
            signal.signal(sig, handler)
        emit({'record': 'capture.stopped', 'reason': reason, 'elapsed_ms': elapsed()})
        raw.close()
        summary = {'schema': 1, 'profile': args.profile, 'address': args.address.lower(),
                   'started_at': started, 'ended_at': utc(), 'stop_reason': reason,
                   'passive': True, 'exclusive_grab': False, 'devices': devices, **recorder.summary()}
        private_json(output / 'summary.json', summary)
        with (output / 'report.md').open('x') as stream:
            os.chmod(output / 'report.md', 0o600)
            stream.write(report_text(summary))
        print('\nSaved capture: ' + str(output), flush=True)
    return 2 if reason == 'device_wait_timeout' else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True, help='Paired Bluetooth address; explicitly select one keypad')
    parser.add_argument('--list', action='store_true', help='List matching interfaces without capturing')
    parser.add_argument('--guided', action='store_true', help='Label each physical control using the SSH/local terminal')
    parser.add_argument('--profile', default='current Bluetooth mapping')
    parser.add_argument('--duration', type=float, default=180, help='Seconds after first interface attaches (default 180)')
    parser.add_argument('--wait', type=float, default=60, help='Maximum seconds to wait for the keypad (default 60)')
    parser.add_argument('--max-events', type=int, default=100000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        parser.error('Run capture on the UNO Q Linux host')
    if not all(0 < value <= 3600 for value in (args.duration, args.wait)) or not 1 <= args.max_events <= 1000000:
        parser.error('Use durations in (0, 3600] and an event limit in 1..1000000')
    if len(args.address.split(':')) != 6 or any(len(part) != 2 or set(part.lower()) - set('0123456789abcdef') for part in args.address.split(':')):
        parser.error('Invalid Bluetooth address')
    if len(args.profile) > 100:
        parser.error('Profile must contain at most 100 characters')
    if args.list:
        print(json.dumps(discover(args.address), indent=2))
        return 0
    args.output = args.output or Path.home() / 'torque/projects/keychron-keymap' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    try:
        return capture(args, Names())
    except PermissionError:
        print('Input access denied. No permissions, groups, or services were changed.', file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print('Capture stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
