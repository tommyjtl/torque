"""Reuse frame/upload validation over a private daemon connection, not Router."""
import copy
import queue
import time
from unoq_control.client import Board as NativeBoard, ControllerError
from .protocol import Connection


class Transport:
    def __init__(self, path):
        self.path = path
        self.connection = None

    def connect(self, timeout):
        self.connection = Connection(self.path)
        return True

    def call(self, method, *args, timeout):
        from unoq_control.client import PREFIX
        try:
            return self.connection.request('device', operation='rpc',
                                           arguments={'method': method.removeprefix(PREFIX), 'args': list(args)})
        except RuntimeError as error:
            raise ControllerError(str(error)) from None

    def disconnect(self):
        if self.connection:
            self.connection.close()
            self.connection = None


class Board(NativeBoard):
    def __init__(self, *, socket_path=None, timeout=3):
        super().__init__(timeout=timeout, transport=Transport(socket_path))

    def _request(self, operation):
        if not self._connected:
            raise ControllerError('Connect to Torque first (use with Board() as board)')
        try:
            return self._transport.connection.request('device', operation=operation, arguments={})
        except RuntimeError as error:
            raise ControllerError(str(error)) from None

    def _writer(self):
        self._request('acquire')

    def snapshot(self):
        return self._request('snapshot')

    def health(self):
        return self._request('health')

    def watch(self, **options):
        watcher = Watcher(self, **options)
        self._observers.append(watcher)
        return watcher


class Watcher:
    """Multiple Linux readers share the daemon's one native subscription."""
    def __init__(self, board, **options):
        if options:
            raise ValueError('Torque watch currently accepts no options')
        self.board = board
        self.cursor = 0
        self.events = queue.Queue()
        self._latest = None
        self.closed = False

    @property
    def latest(self):
        return copy.deepcopy(self._latest)

    def start(self):
        self._latest = self.board.snapshot()
        self.cursor = self.board._transport.connection.request('status')['cursor']
        return self

    def get(self, timeout=None):
        end = time.monotonic() + timeout if timeout is not None else None
        while not self.closed:
            if not self.events.empty():
                return self.events.get_nowait()
            batch = self.board._transport.connection.request('events', after=self.cursor)
            self.cursor = batch['cursor']
            self._latest = batch['device']['snapshot']
            for event in batch['events']:
                if event['type'] == 'device.event':
                    self.events.put(event['event'])
            if end is not None and time.monotonic() >= end and self.events.empty():
                raise queue.Empty
            if self.events.empty():
                time.sleep(0.05)
        raise StopIteration

    def close(self):
        self.closed = True

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()

    def __iter__(self):
        while not self.closed:
            yield self.get()
