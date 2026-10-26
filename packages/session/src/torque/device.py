"""The daemon's single native device coordinator and low-priority renderer."""
import copy
import json
import os
import queue
import threading
import time
import tempfile
from pathlib import Path
from unoq_control import Board, Frame
from .status_display import StatusDisplay

READS = {'system.info', 'system.capability', 'matrix.status'}
WRITES = {'rgb.set', 'matrix.draw', 'matrix.clear', 'matrix.stop', 'matrix.begin',
          'matrix.write_frame', 'matrix.commit', 'matrix.abort', 'matrix.play',
          'matrix.draw_gray', 'matrix.begin_gray', 'matrix.write_gray', 'matrix.cache', 'matrix.play_cached'}


class Device:
    def __init__(self, assets, publish, intent_path=None, factory=Board):
        self.frames = json.loads(Path(assets).read_text())
        for rows in self.frames.values():
            Frame.from_rows(rows)
        self.publish, self.factory = publish, factory
        self.lock = threading.RLock()
        self.board = self.watcher = None
        self.display = None
        self.owner = None
        self.maintenance = False
        self.reset_fault = False
        self.staging_upload = None
        self.intent_path = Path(intent_path) if intent_path else None
        self.intent = None
        self.intent_note = None
        if self.intent_path and self.intent_path.exists():
            value = json.loads(self.intent_path.read_text())
            Frame.from_hex(value['frame_hex'])
            if type(value.get('boot_id')) is not int or not 1 <= value['boot_id'] <= 2147483647:
                raise ValueError('Invalid saved display intent')
            self.intent = value
        self.state = 'standby'
        self.rendered = None
        self.snapshot = None
        self.error = 'Waiting for controller'
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                with self.lock:
                    if self.board is None:
                        board = self.factory(timeout=2)
                        try:
                            board.connect()
                            identity = board.info()
                            # Session cues use grayscale resident presets from this bundle.
                            if (identity['version'], tuple(identity['protocol'])) != ('0.4.0', (1, 3)):
                                raise RuntimeError('Controller bundle mismatch; deliberate maintenance is required')
                            watcher = board.watch(reconnect_attempts=0).start()
                        except BaseException:
                            board.close()
                            raise
                        self.board, self.watcher = board, watcher
                        self.display = None
                        self.rendered = None
                        self.reconcile_intent(self.watcher.latest)
                    self.snapshot = self.watcher.latest
                    if not self.snapshot or self.snapshot.get('stale'):
                        raise RuntimeError('Controller telemetry is stale')
                    self.error = None
                    self.render()
                try:
                    event = self.watcher.get(timeout=0.2)
                    self.publish({'type': 'device.event', 'event': event})
                except queue.Empty:
                    pass
            except Exception as error:
                with self.lock:
                    self.error = str(error)
                    if self.snapshot:
                        self.snapshot['stale'] = True
                    if self.board:
                        self.board.close()
                    self.board = self.watcher = None
                    self.display = None
                    self.owner = None
                    self.rendered = None
                self.stop.wait(2)

    def render(self):
        if not self.maintenance and not self.reset_fault and self.owner is None and self.intent is None and self.rendered != self.state:
            if self.display is None or self.display.board is not self.board:
                self.display = StatusDisplay(self.board, self.frames)
            self.display.show(self.state)
            self.rendered = self.state

    def set_state(self, state):
        with self.lock:
            self.state = state if state in self.frames else 'standby'

    def status(self):
        with self.lock:
            return {'ready': self.board is not None and self.error is None,
                    'error': self.error, 'owner': self.owner,
                    'display_state': self.state, 'snapshot': copy.deepcopy(self.snapshot),
                    'display_mode': 'program' if self.owner else 'user' if self.intent else 'status',
                    'retained_matrix': copy.deepcopy(self.intent), 'intent_note': self.intent_note,
                    'evidence': 'firmware framebuffer and GPIO readback; no optical measurement',
                    'reset_fault': self.reset_fault,
                    'output_watchdog': False}

    def set_maintenance(self, enabled):
        # Gate new writers before waiting for any in-flight RPC to settle.
        self.maintenance = enabled

    def fence_update(self):
        with self.lock:
            if self.maintenance or self.owner is not None or self.board is None or self.error or self.reset_fault:
                raise RuntimeError('Device work is active; runtime update refused')
            self.maintenance = True

    def save_intent(self):
        if not self.intent_path:
            return
        if self.intent is None:
            self.intent_path.unlink(missing_ok=True)
            return
        fd, name = tempfile.mkstemp(prefix='.display-', dir=self.intent_path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.intent, stream)
            os.replace(name, self.intent_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def reconcile_intent(self, snapshot):
        # Adopt unchanged MCU state after a daemon restart; never replay a write
        # to a new boot or over an independently changed framebuffer.
        if self.intent and (snapshot['boot_id'] != self.intent['boot_id'] or
                            snapshot['matrix']['frame_hex'] != self.intent['frame_hex'] or snapshot['matrix']['playing']):
            self.intent_note = 'Saved output invalidated by a different MCU boot or framebuffer; no write was replayed'
            self.intent = None
            self.save_intent()

    def action(self, name, arguments):
        from .policy import validate
        validate(name, arguments)
        with self.lock:
            if self.board is None or self.error:
                raise RuntimeError(self.error or 'Controller unavailable')
            if name == 'device_capabilities':
                return {'board': 'Arduino UNO Q', 'firmware': self.board.info(),
                        'matrix': self.board.capability('matrix'), 'rgb': self.board.capability('rgb'),
                        'display': self.status(),
                        'direct_matrix_commands': 'Retained until changed, a program takes ownership, or matrix_release restores status. No Python file needed.'}
            if self.maintenance:
                raise RuntimeError('Device reset is in progress')
            if self.owner is not None:
                raise RuntimeError('Another program owns the device; direct action was not executed')
            self.reset_fault = False
            if name == 'matrix_release':
                self.intent = None
                self.save_intent()
                self.rendered = None
                self.render()
            elif name in ('matrix_fill', 'matrix_draw', 'matrix_clear'):
                frame = (Frame.from_rows(arguments['rows']) if name == 'matrix_draw' else
                         Frame((int(arguments.get('on', False)),) * 104))
                self.board.matrix.draw(frame)
                snapshot = self.board.snapshot()
                if snapshot['matrix']['frame_hex'] != frame.to_hex() or snapshot['matrix']['playing']:
                    raise RuntimeError('Matrix command returned but readback did not match; no retry was sent')
                self.intent = {'schema': 1, 'boot_id': snapshot['boot_id'], 'frame_hex': frame.to_hex(),
                               'retained': True, 'until': 'changed, program ownership or explicit status release'}
                self.intent_note = None
                self.save_intent()
            elif name == 'rgb_set':
                values = [arguments[key] for key in ('red', 'green', 'blue')]
                self.board.rgb(arguments['led']).set(*values)
            else:
                raise ValueError('Unknown device action')
            self.snapshot = self.board.snapshot()
            if name == 'rgb_set':
                state = self.snapshot['rgb'][str(arguments['led'])]
                expected = {key: arguments[key] for key in ('red', 'green', 'blue')}
                if not state['readback_valid'] or state['readback'] != expected:
                    raise RuntimeError('RGB command returned but GPIO readback was unavailable or did not match; no retry was sent')
            return {'operation': name, 'matrix': self.snapshot['matrix'], 'rgb': self.snapshot['rgb'],
                    'display_mode': self.status()['display_mode'], 'retained': self.intent is not None,
                    'lit_pixels': sum(p > 0 for p in Frame.from_hex(self.snapshot['matrix']['frame_hex'],
                                      bits=self.snapshot['matrix'].get('bits', 1)).pixels),
                    'source': 'firmware framebuffer and GPIO readback', 'optical_measurement': False}

    def request(self, client, operation, arguments):
        with self.lock:
            if self.board is None or self.error:
                raise RuntimeError(self.error or 'Controller unavailable')
            if operation == 'acquire':
                if self.maintenance:
                    raise RuntimeError('Device reset is in progress')
                if self.owner not in (None, client):
                    raise RuntimeError('Another program owns the device')
                if self.owner is None and self.display is not None:
                    self.display.invalidate()
                self.owner = client
                self.reset_fault = False
                self.intent = None
                self.save_intent()
                return True
            if operation == 'release':
                if self.owner == client:
                    self.owner = None
                    self.rendered = None
                    self.render()
                return True
            if operation == 'snapshot':
                return self.board.snapshot()
            if operation == 'health':
                return self.board.health()
            if operation == 'rpc':
                suffix, values = arguments['method'], arguments.get('args', [])
                if not isinstance(values, list) or len(values) > 8:
                    raise ValueError('Invalid device arguments')
                if suffix in WRITES:
                    if self.maintenance:
                        raise RuntimeError('Device reset is in progress')
                    if self.owner != client:
                        raise RuntimeError('Acquire device ownership before writing')
                    self.board._writer()
                elif suffix not in READS:
                    raise ValueError('Unsupported public device operation')
                result = self.board._call(suffix, *values)
                if suffix in ('matrix.begin', 'matrix.begin_gray') and type(result) is int and result > 0:
                    self.staging_upload = {'client': client, 'id': result}
                elif suffix in ('matrix.commit', 'matrix.abort') and result == 0:
                    self.staging_upload = None
                return result
            raise ValueError('Unknown device operation')

    def release(self, client):
        with self.lock:
            if self.owner == client:
                self.owner = None
                self.rendered = None

    def reset(self, *, blank=False):
        """Explicit output reset, with no reconnect/retry or unrelated cleanup."""
        if type(blank) is not bool:
            raise ValueError('Blank must be boolean')
        with self.lock:
            components = {'matrix': {'status': 'skipped'}, 'rgb_3': {'status': 'skipped'},
                          'rgb_4': {'status': 'skipped'},
                          'linux_user_rgb': {'status': 'skipped', 'reason': 'Not managed by the coordinator'}}
            result = {'passed': False, 'target': 'blank' if blank else 'standby', 'components': components,
                      'optical_measurement': False}
            if self.owner is not None:
                return {**result, 'error': 'Another program owns the device; stop it before resetting', 'busy': True}
            if self.board is None or self.error:
                return {**result, 'error': self.error or 'Controller unavailable'}
            component = 'matrix'
            try:
                before = self.board.snapshot()
                boot = before['boot_id']
                self.intent = None
                self.save_intent()
                if self.staging_upload:
                    self.board._mutate('matrix.abort', self.staging_upload['id'])
                    self.staging_upload = None
                target = Frame((0,) * 104) if blank else Frame.from_rows(self.frames['standby'])
                self.board.matrix.draw(target)  # Stops playback; preserves resident clips.
                components['matrix'] = {'status': 'applied_unverified'}
                for led in (3, 4):
                    component = f'rgb_{led}'
                    self.board.rgb(led).set(False, False, False)
                    components[component] = {'status': 'applied_unverified'}
                component = 'verification'
                after = self.board.snapshot()
                if after['boot_id'] != boot:
                    raise RuntimeError('MCU boot changed; no writes were replayed')
                matrix_ok = (not after['matrix']['playing'] and after['matrix'].get('bits', 1) == 1 and
                             after['matrix']['frame_hex'] == target.to_hex())
                components['matrix'] = {'status': 'completed' if matrix_ok else 'failed', 'verified': matrix_ok}
                for led in (3, 4):
                    state = after['rgb'][str(led)]
                    valid = state['readback_valid'] and state['readback'] == {'red': False, 'green': False, 'blue': False}
                    components[f'rgb_{led}'] = {'status': 'completed' if valid else 'failed', 'verified': valid}
                self.snapshot = after
                result['passed'] = all(components[name]['status'] == 'completed' for name in ('matrix', 'rgb_3', 'rgb_4'))
                self.state = 'standby'
                self.rendered = 'standby'
                if blank and matrix_ok:
                    self.intent = {'schema': 1, 'boot_id': boot, 'frame_hex': target.to_hex(), 'retained': True,
                                   'until': 'changed, program ownership or explicit status release'}
                    self.save_intent()
                self.reset_fault = not result['passed']
                if not result['passed']:
                    result['error'] = 'One or more outputs failed independent readback'
                return {**result, 'boot_id': boot, 'frame_hex': after['matrix']['frame_hex']}
            except (RuntimeError, OSError, ValueError, KeyError) as error:
                components[component] = {'status': 'failed', 'reason': str(error)}
                self.reset_fault = True  # Do not repaint over uncertain output as recovery.
                return {**result, 'passed': False, 'error': str(error)}

    def close(self):
        self.stop.set()
        self.thread.join(timeout=12)
        with self.lock:
            if self.board:
                self.board.close()
