"""Private, bounded local protocol. No TCP listener or credentials in messages."""
import json
import os
from pathlib import Path
import socket

VERSION = 1
LIMIT = 256 * 1024


def address():
    return os.environ.get('TORQUE_SOCKET', '/run/torque/control.sock')


def encode(value):
    data = json.dumps(value, separators=(',', ':')).encode() + b'\n'
    if len(data) > LIMIT:
        raise ValueError('Torque message exceeds its size limit')
    return data


class Connection:
    def __init__(self, path=None):
        self.path = str(path or address())
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(10)
        try:
            self.socket.connect(self.path)
        except OSError:
            self.socket.close()
            raise RuntimeError('Torque is unavailable. Run torque doctor.') from None
        self.stream = self.socket.makefile('rb')
        self.counter = 0

    def send(self, value):
        self.socket.sendall(encode(value))

    def receive(self):
        raw = self.stream.readline(LIMIT + 1)
        if not raw or len(raw) > LIMIT or not raw.endswith(b'\n'):
            raise RuntimeError('Torque connection closed or sent an oversized message')
        return json.loads(raw)

    def request(self, op, **arguments):
        self.counter += 1
        self.send({'v': VERSION, 'id': self.counter, 'op': op, **arguments})
        while True:
            reply = self.receive()
            if reply.get('id') == self.counter:
                if 'error' in reply:
                    raise RuntimeError(reply['error'])
                return reply.get('result')

    def close(self):
        self.stream.close()
        self.socket.close()

    def reconnect(self):
        path = self.path
        self.close()
        self.__init__(path)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
