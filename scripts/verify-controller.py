#!/usr/bin/env python3
"""Read-only telemetry checks by default. --exercise-outputs opts into LED/matrix tests."""
import argparse
import json
from pathlib import Path
import queue
import secrets
import signal
import select
import statistics
import subprocess
import sys
import threading
import time
from controller_common import CACHE, ROOT, clean_env, require_board
from fx_common import atomic_write


def event_where(observer, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = observer.get(timeout=min(0.2, max(0.001, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if predicate(event):
            return event
    raise AssertionError('Expected telemetry event was not received')


def latency(board):
    samples = []
    for _ in range(10):
        started = time.perf_counter();board.info()
        samples.append((time.perf_counter() - started) * 1000)
    return {'samples': len(samples), 'median_ms': round(statistics.median(samples), 2),
            'maximum_ms': round(max(samples), 2), 'scope': 'info RPC round trip'}


def exercise(board, record):
    from arduino.router_bridge import Bridge
    from unoq_control import Board, ControllerError, Frame
    record('latency_without_observer', latency(board))
    boot = board.info()['boot_id']
    frame = Frame.from_hex('80040000000000000000000001')
    with board.watch() as observer:
        event_where(observer, lambda e: e['kind'] == 'snapshot')
        for led in (3, 4):
            for color in ((True, False, False), (False, True, False), (False, False, True), (False, False, False)):
                board.rgb(led).set(*color)
                expected = dict(zip(('red', 'green', 'blue'), color))
                state = board.rgb(led).status()
                assert state['readback_valid'] and state['requested'] == expected and state['readback'] == expected
                event_where(observer, lambda e: e['kind'] == 'rgb' and e['state']['id'] == led and e['state']['readback'] == expected)
        record('rgb_readback_and_async_events', True)
        assert board._observe('system.subscribe', observer._endpoint) == observer._token
        try:
            board._observe('system.renew', observer._token + 1)
        except ControllerError:
            pass
        else:
            raise AssertionError('Stale observer token was accepted')
        with Board() as reader:
            assert reader.snapshot()['boot_id'] == boot
            second = reader.watch()
            try:
                second.start()
            except ControllerError:
                pass
            else:
                raise AssertionError('Second observer was accepted')
            finally:
                second.close()
        record('passive_readers_observer_exclusion_and_idempotence', True)
        board.matrix.draw(frame)
        assert board.matrix.frame() == frame
        event_where(observer, lambda e: e['kind'] == 'matrix' and e['state']['frame_hex'] == frame.to_hex())
        record('framebuffer_snapshot_and_event', True)
        board.matrix.load([Frame([0] * 104), frame, Frame([1] * 104)], 100)
        board.matrix.play(repeat=2)
        event_where(observer, lambda e: e['kind'] == 'matrix' and e['state']['playing'])
        indices = set();deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                event = observer.get(timeout=0.15)
            except queue.Empty:
                event = None
            if event and event['kind'] == 'matrix':indices.add(event['state']['frame_index'])
            if not board.matrix.status()['playing']:break
        assert not board.matrix.status()['playing'] and len(indices) >= 2
        record('sampled_playback_events', {'frame_indices': sorted(indices)})
        # Repeated RGB commands must not turn sampled matrix progress into per-command traffic.
        board.matrix.load([Frame([0] * 104), frame, Frame([1] * 104), frame], 20)
        board.matrix.play(repeat=0)
        event_where(observer, lambda e: e['kind'] == 'matrix' and e['state']['playing'])
        commands, failures = [], []
        started = time.monotonic()
        def rgb_traffic():
            try:
                while time.monotonic() - started < 1.2:
                    board.rgb(3).set(False, False, False)
                    commands.append(1)
                    time.sleep(0.005)
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=rgb_traffic, daemon=True);worker.start()
        progress = []
        while worker.is_alive():
            try:
                event = observer.get(timeout=0.1)
            except queue.Empty:
                continue
            if event['kind'] == 'matrix':progress.append(event)
        worker.join(timeout=3)
        assert not failures and len(commands) >= 10
        assert 2 <= len(progress) <= 9 and all(e['cause'] == 'playback' for e in progress)
        board.matrix.stop()
        record('matrix_sampling_during_rgb_traffic', {'rgb_commands': len(commands), 'matrix_events': len(progress),
                                                     'duration_seconds': round(time.monotonic() - started, 2)})
        before = board.matrix.frame()
        try:
            board._mutate('matrix.draw', 'bad')
        except ControllerError:
            pass
        else:
            raise AssertionError('Malformed frame was accepted')
        event_where(observer, lambda e: e['kind'] == 'error' and e['operation'] == 'matrix.draw' and e['code'] == -1)
        assert board.matrix.frame() == before and board.health()['last_result'] == -1
        record('rejected_command_error_event', True)
        board.matrix.play(repeat=0)
        record('latency_with_observer', latency(board))
        board.matrix.clear()
        board.matrix.draw(frame)
        board.rgb(3).set(True, False, False)
        before_close = board.snapshot()
    after_close = board.snapshot()
    assert after_close['rgb'] == before_close['rgb'] and after_close['matrix'] == before_close['matrix']
    assert board.health()['observer_active'] is False
    record('observer_close_preserves_outputs', True)

    # An abandoned subscriber must expire without changing output state.
    connection = Bridge(max_message_size=1024, max_pending_handlers=8)
    endpoint = 'unoq.telemetry.v1.' + secrets.token_hex(8)
    try:
        assert connection.connect(timeout=3)
        connection.provide(endpoint, lambda payload: None)
        token = connection.call('unoq.control.v1.system.subscribe', boot, endpoint, timeout=3)
        assert type(token) is int and token > 0
    finally:
        connection.disconnect()
    assert board.health()['observer_active'] is True
    started = time.monotonic();deadline = started + 13
    while board.health()['observer_active']:
        if time.monotonic() >= deadline:raise AssertionError('Observer lease did not expire')
        time.sleep(0.2)
    assert board.matrix.frame() == frame and board.rgb(3).status()['readback']['red']
    record('abandoned_observer_expires', {'waited_seconds': round(time.monotonic() - started, 2)})
    board.matrix.clear();board.rgb(3).set(False,False,False)

    command = [str(ROOT / 'packages/device/.venv/bin/unoq-control'), 'watch', '--duration', '2', '--jsonl']
    process = subprocess.Popen(command, cwd=ROOT, env=clean_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if not select.select([process.stdout], [], [], 6)[0]:raise AssertionError('CLI observer did not start')
        first = process.stdout.readline()
        assert json.loads(first)['kind'] == 'snapshot'
        board.rgb(3).set(False, True, False)
        output, error = process.communicate(timeout=8)
        assert process.returncode == 0, error
        events = [json.loads(line) for line in (first + output).splitlines()]
        assert any(e['kind'] == 'rgb' and e['state']['id'] == 3 and e['state']['readback']['green'] for e in events)
    finally:
        if process.poll() is None:
            process.terminate();process.communicate(timeout=5)
    record('watch_cli_jsonl', {'events': len(events)})
    assert board.info()['boot_id'] == boot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise-outputs', action='store_true', help='Run visible RGB/matrix changes, then clear/off')
    parser.add_argument('--report', type=Path, default=CACHE / 'telemetry-validation.json')
    args = parser.parse_args(argv)
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    old_term = signal.signal(signal.SIGTERM, interrupted)
    report = {'tests': {}, 'exercised_outputs': args.exercise_outputs, 'result': 'started'}
    def record(name, value):
        report['tests'][name] = value
        print('PASS: ' + name, flush=True)
    try:
        require_board()
        from unoq_control import Board
        with Board() as board:
            report['firmware'] = board.info()
            report['snapshot'] = board.snapshot()
            report['health'] = board.health()
            record('read_only_snapshot_and_health', True)
            if args.exercise_outputs:
                try:
                    exercise(board, record)
                finally:
                    board.matrix.clear()
                    board.rgb(3).set(False, False, False);board.rgb(4).set(False, False, False)
                final = board.snapshot()
                assert final['matrix']['frame_hex'] == '0' * 26 and not final['matrix']['playing']
                assert all(not any(c['readback'].values()) for c in final['rgb'].values())
                report['final_snapshot'] = final
                report['final_health'] = board.health()
                record('final_readback_off_and_clear', True)
        report['result'] = 'passed'
        return 0
    except KeyboardInterrupt:
        report['result'] = 'interrupted'
        return 130
    except Exception as error:
        report['result'] = 'failed';report['error'] = type(error).__name__ + ': ' + str(error)
        print('Controller verification: ' + report['error'], file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, old_term)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(args.report, (json.dumps(report, indent=2) + '\n').encode())
        print('Report: ' + str(args.report), flush=True)


if __name__ == '__main__':
    sys.exit(main())
