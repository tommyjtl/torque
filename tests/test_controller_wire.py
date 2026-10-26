"""Optional integration: real native Bridge package over a private simulated router socket."""
import importlib.util
import json
import base64
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages/device/src'))
from unoq_control import Board, Frame

try:
    import msgpack
    from arduino.router_bridge import Bridge
    HAS_NATIVE_BRIDGE = True
except ImportError:
    HAS_NATIVE_BRIDGE = False


@unittest.skipUnless(HAS_NATIVE_BRIDGE, 'Install python/ to run native Bridge wire integration')
class NativeWireTests(unittest.TestCase):
    def test_native_bridge_transfers_versioned_calls_and_bounded_frames(self):
        with tempfile.TemporaryDirectory(prefix='unoq-wire-') as tmp:
            address = str(Path(tmp) / 'router.sock')
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(address)
            server.listen(1)
            server.settimeout(5)
            calls, errors = [], []
            def peer():
                try:
                    connection, _ = server.accept()
                    with connection:
                        connection.settimeout(5)
                        unpacker = msgpack.Unpacker(raw=False)
                        while True:
                            data = connection.recv(4096)
                            if not data:
                                break
                            unpacker.feed(data)
                            for message in unpacker:
                                if message[0] != 0:
                                    continue
                                _, sequence, method, args = message
                                calls.append((method, args, len(msgpack.packb(message))))
                                if method.endswith('system.info'):
                                    result = json.dumps({'name': 'base-controller', 'version': '0.4.0', 'protocol': [1, 3], 'boot_id': 2147483647, 'ready': True})
                                elif method.endswith('system.capability'):
                                    cap = dict(rows=8, columns=13, max_frames=32, min_duration_ms=20,
                                               max_duration_ms=60000, encoding='bitset-hex-msb')
                                    if args == ['matrix-grayscale']:
                                        cap.update(encoding='gray3-hex-msb', bits=3, max_value=7)
                                    elif args == ['matrix-presets']:
                                        cap = dict(max_presets=9,max_frames=32)
                                    result = json.dumps(cap, separators=(',', ':'))
                                elif method.endswith(('matrix.begin', 'matrix.begin_gray')):
                                    result = 2147483647
                                else:
                                    result = 0
                                response = msgpack.packb([1, sequence, None, result])
                                assert len(response) <= 256
                                connection.sendall(response)
                except BaseException as error:
                    errors.append(error)
            thread = threading.Thread(target=peer, daemon=True)
            thread.start()
            try:
                with Board(transport=Bridge(address='unix://' + address), lock_dir=Path(tmp) / 'lock') as board:
                    board.matrix.draw(Frame([1] * 104))
                    board.matrix.load([Frame([0] * 104)] * 31 + [Frame([1] * 104)], 60000)
                    board.matrix.play()
                    gray = Frame(tuple(i % 8 for i in range(104)), bits=3)
                    board.matrix.draw(gray)
                    board.matrix.load([gray] * 32, 60000)
                    board.matrix.play(repeat=3)
                    board.matrix.cache(9)
                    board.matrix.play_cached(9,repeat=0)
            finally:
                server.close()
                thread.join(timeout=6)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(all(size <= 256 for _, _, size in calls))
            self.assertTrue(all(method.startswith('unoq.control.v1.') for method, _, _ in calls))
            draw = next(args for method, args, _ in calls if method.endswith('matrix.draw'))
            self.assertEqual(draw, [2147483647, 'f' * 26])
            writes = [args for method, args, _ in calls if method.endswith('matrix.write_frame')]
            self.assertEqual(writes[-1], [2147483647, 2147483647, 31, 'f' * 26, 60000])
            gray_writes = [args for method, args, _ in calls if method.endswith('matrix.write_gray')]
            self.assertEqual(len(gray_writes), 32)
            self.assertEqual(gray_writes[-1], [2147483647, 2147483647, 31, '053977' * 13, 60000])
            self.assertEqual([(m,a) for m,a,_ in calls if m.endswith('matrix.play_cached')],
                             [('unoq.control.v1.matrix.play_cached',[2147483647,9,0])])


    def test_native_bridge_receives_async_events_while_another_connection_controls(self):
        with tempfile.TemporaryDirectory(prefix='unoq-events-') as tmp:
            address = str(Path(tmp) / 'router.sock')
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(address);server.listen(4);server.settimeout(0.2)
            stop = threading.Event()
            lock = threading.RLock()
            routes, send_locks, sockets, workers, errors = {}, {}, [], [], []
            active = {'endpoint': None}
            state = dict(v=1, b=7, s=0, r=0, t=0, c=0, rgb=[[0, 7], [0, 7]],
                         f='0' * 26, p=False, i=0, n=0, a=0, u=0)

            def send(connection, message):
                encoded = msgpack.packb(message)
                self.assertLessEqual(len(encoded), 256)
                with send_locks[connection]:connection.sendall(encoded)

            def peer(connection):
                try:
                    connection.settimeout(0.2)
                    unpacker = msgpack.Unpacker(raw=False)
                    while not stop.is_set():
                        try:data = connection.recv(4096)
                        except socket.timeout:continue
                        if not data:break
                        unpacker.feed(data)
                        for message in unpacker:
                            if message[0] != 0:continue
                            _, sequence, method, args = message
                            event = None
                            with lock:
                                if method == '$/register':
                                    routes[args[0]] = connection;result = True
                                elif method.endswith('system.info'):
                                    result = json.dumps(dict(name='base-controller', version='0.2.0', protocol=[1, 1], boot_id=7, ready=True))
                                elif method.endswith('system.capability'):
                                    cap = (dict(schema=1, lease_ms=10000) if args[0]=='telemetry' else
                                           dict(ids=[3, 4], binary=True) if args[0]=='rgb' else
                                           dict(rows=8, columns=13, max_frames=32, min_duration_ms=20, max_duration_ms=60000, encoding='bitset-hex-msb'))
                                    result = json.dumps(cap)
                                elif method.endswith('system.subscribe'):
                                    active['endpoint'] = args[1];result = 31
                                elif method.endswith('system.renew'):
                                    result = 0
                                elif method.endswith('system.unsubscribe'):
                                    active['endpoint'] = None;result = 0
                                elif method.endswith('system.snapshot'):
                                    result = json.dumps(state, separators=(',', ':'))
                                elif method.endswith('rgb.set'):
                                    requested = sum(int(v) << i for i,v in enumerate(args[2:]))
                                    state['rgb'][args[1]-3] = [requested, 7-requested]
                                    state['s'] += 1;state['r'] += 1;state['c'] += 1
                                    event = {k:state[k] for k in ('v','b','s','r','t','c')}
                                    event.update(h=31, k='r3' if args[1]==3 else 'r4', o=0, q=requested, g=7-requested)
                                    result = 0
                                elif method.endswith('matrix.draw'):
                                    state['f'] = args[1];state['s'] += 1;state['r'] += 1;state['c'] += 1
                                    event = {k:state[k] for k in ('v','b','s','r','t','c','f','p','i','n','a','u')}
                                    event.update(h=31, k='m', o=0)
                                    result = 0
                                elif method.endswith('matrix.draw_gray'):
                                    state['v'] = 2
                                    state['m'] = [base64.b64encode(bytes.fromhex(args[1])).decode(), False, 0, 0, 0, 0]
                                    state['s'] += 1;state['r'] += 1;state['c'] += 1
                                    event = {k:state[k] for k in ('v','b','s','r','t','c','m')}
                                    event.update(h=31, k='m', o=0)
                                    result = 0
                                else:raise AssertionError('Unexpected native RPC: '+method)
                                endpoint = active['endpoint']
                                receiver = routes.get(endpoint)
                            send(connection, [1, sequence, None, result])
                            if event is not None and receiver is not None:
                                send(receiver, [2, endpoint, [json.dumps(event,separators=(',',':'))]])
                except BaseException as error:
                    if not stop.is_set():errors.append(error)
                finally:
                    with lock:
                        for name in [name for name,owner in routes.items() if owner is connection]:routes.pop(name)
                    connection.close()

            def accept():
                while not stop.is_set():
                    try:connection,_ = server.accept()
                    except socket.timeout:continue
                    except OSError:break
                    sockets.append(connection);send_locks[connection] = threading.Lock()
                    worker = threading.Thread(target=peer,args=(connection,),daemon=True)
                    workers.append(worker);worker.start()

            acceptor = threading.Thread(target=accept,daemon=True);acceptor.start()
            factory = lambda: Board(transport=Bridge(address='unix://'+address),lock_dir=Path(tmp)/'lock')
            try:
                with factory() as board:
                    with board.watch(board_factory=factory) as watcher:
                        self.assertEqual(watcher.get(timeout=2)['kind'],'snapshot')
                        board.rgb(3).set(True,False,False)
                        event = watcher.get(timeout=2)
                        self.assertEqual(event['kind'],'rgb')
                        self.assertTrue(event['state']['readback']['red'])
                        frame = Frame.from_hex('80040000000000000000000001')
                        board.matrix.draw(frame)
                        event = watcher.get(timeout=2)
                        self.assertEqual(event['kind'],'matrix')
                        self.assertEqual(watcher.latest['matrix']['frame_hex'],frame.to_hex())
                        # Exercise a schema transition on a real native notification
                        # connection without polling frames from inside callbacks.
                        gray = Frame(tuple(i % 8 for i in range(104)), bits=3)
                        board._mutate('matrix.draw_gray', gray.to_hex())
                        event = watcher.get(timeout=2)
                        self.assertEqual(event['state']['bits'], 3)
                        self.assertEqual(watcher.latest['matrix']['frame_hex'], gray.to_hex())
                    self.assertIsNone(active['endpoint'])
                    self.assertEqual(board.snapshot()['rgb']['3']['requested']['red'],True)
            finally:
                stop.set();server.close()
                for connection in sockets:
                    try:connection.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                acceptor.join(timeout=2)
                for worker in workers:worker.join(timeout=2)
            self.assertEqual(errors,[])


if __name__ == '__main__':
    unittest.main()
