"""Small state source for observer lifecycle tests, without Arduino or socket access."""
import copy
import json
import threading
from unoq_control import ControllerError, ResetError
from unoq_control.telemetry import decode_snapshot


class Device:
    def __init__(self):
        self.lock = threading.RLock()
        self.routes = {}
        self.owner = None
        self.token = 0
        self.fail_renew = False
        self.fail_connect = False
        self.callback_thread = None
        self.mutations = 0
        self.reset(boot=7)

    def reset(self, boot=None):
        with self.lock:
            self.data = {'v': 1, 'b': boot or self.data['b'] + 1, 's': 0, 'r': 0, 't': 0, 'c': 0,
                         'rgb': [[0, 7], [0, 7]], 'f': '0' * 26, 'p': False, 'i': 0,
                         'n': 0, 'a': 0, 'u': 0}
            self.owner = None

    def factory(self):
        return Connection(self)

    def send(self, **overrides):
        with self.lock:
            if self.owner is None:
                return
            self.data['s'] = (self.data['s'] + 1) & 0xffffffff
            data = self.data
            event = {k: data[k] for k in ('v', 'b', 's', 'r', 't', 'c')}
            event.update(h=self.owner[1], k='r3', o=0, q=data['rgb'][0][0], g=data['rgb'][0][1])
            event.update(overrides)
            callback = self.routes.get(self.owner[0])
        if callback:
            self.callback_thread = threading.get_ident()
            try:
                callback(json.dumps(event, separators=(',', ':')))
            finally:
                self.callback_thread = None

    def rgb(self, requested, pins):
        with self.lock:
            self.data['rgb'][0] = [requested, pins]
            self.data['r'] = (self.data['r'] + 1) & 0xffffffff
            self.data['c'] += 1
            self.mutations += 1
        self.send()


class Transport:
    def __init__(self, connection):
        self.connection = connection
        self.endpoint = None

    def provide(self, endpoint, handler):
        self.endpoint = endpoint
        self.connection.device.routes[endpoint] = handler

    def disconnect(self):
        self.connection.close()


class Connection:
    def __init__(self, device):
        self.device = device
        self._transport = Transport(self)
        self.boot = None

    def connect(self):
        if self.device.fail_connect:
            raise ControllerError('simulated connection failure')
        self.boot = self.device.data['b']

    def info(self):
        if self.boot != self.device.data['b']:
            raise ResetError('simulated MCU restart')
        return {'boot_id': self.boot}

    def _require_telemetry(self):
        return {'schema': 1, 'lease_ms': 1000}

    def snapshot(self):
        assert threading.get_ident() != self.device.callback_thread, 'Nested RPC in callback'
        self.info()
        with self.device.lock:
            return decode_snapshot(copy.deepcopy(self.device.data))

    def _observe(self, method, argument):
        assert threading.get_ident() != self.device.callback_thread, 'Nested RPC in callback'
        self.info()
        with self.device.lock:
            device = self.device
            if method == 'system.subscribe':
                if device.owner is not None and device.owner[0] != argument:
                    raise ControllerError('another upload is in progress')
                if device.owner is None:
                    device.token += 1
                    device.owner = (argument, device.token)
                return device.owner[1]
            if method == 'system.renew' and device.fail_renew:
                device.fail_renew = False
                raise ControllerError('simulated transport drop')
            if device.owner is None or device.owner[1] != argument:
                raise ControllerError('stale observer token')
            if method == 'system.unsubscribe':
                device.owner = None
            return 0

    def close(self):
        self.device.routes.pop(self._transport.endpoint, None)
