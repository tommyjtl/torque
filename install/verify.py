#!/usr/bin/env python3
"""Read-only by default; explicit flags authorize small agent/device checks."""
import argparse
import json
import os
from pathlib import Path
import queue
import shlex
import sys
import time
from torque import Board, Frame
from torque.protocol import Connection

ROWS = ['...##...##...', '..####.####..', '.###########.', '.###########.',
        '..#########..', '...#######...', '....#####....', '......#......']


def turn(prompt, approve, *, detach=False, permissions='ask'):
    with Connection() as client:
        before = client.request('status')
        reply = client.request('prompt', prompt=prompt, resume=False, permissions=permissions)
        cursor = reply['cursor']
    # The connection which sent the prompt is now closed. A new client observes
    # the same turn; it never sends another prompt to reconnect.
    if detach:
        time.sleep(1)
    output, effects, hooks, answered = [], [], set(), set()
    with Connection() as client:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            batch = client.request('events', after=cursor)
            if batch['epoch'] != before['epoch'] or batch['gap']:
                raise RuntimeError('Daemon restarted or verification missed events')
            cursor = batch['cursor']
            for event in batch['events']:
                if event['type'] == 'engine.hook':
                    hooks.add(event['event']['type'])
                if event['type'] == 'engine.output':
                    item = event['event']
                    if item['type'] == 'text_delta':
                        output.append(item['delta'])
                    elif item['type'] == 'tool_end':
                        effects.append(item)
            for pending in batch['session']['pending']:
                token = pending['request_id']
                if token not in answered:
                    allowed = bool(approve(pending))
                    client.request('approve', request_id=token,
                                   session_id=pending['session_id'], allow=allowed)
                    answered.add(token)
            if not batch['session']['active']:
                if batch['session']['outcome'] != 'end_turn':
                    raise RuntimeError('Agent turn did not complete successfully')
                return {'output': ''.join(output), 'effects': effects, 'hooks': sorted(hooks),
                        'decisions': len(answered), 'detached_client': True}
            time.sleep(0.1)
    raise RuntimeError('Agent check timed out; inspect torque status and cancel if necessary')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise-agent', action='store_true', help='Authorize a model turn and the exact uname -m tool')
    parser.add_argument('--exercise-device', action='store_true', help='Authorize a finite heart display and ownership/fanout tests')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    try:
        with Connection() as client:
            state = client.request('status')
        report = {'model': state['model'], 'device_ready': state['device']['ready'],
                  'physical_observation': 'not performed by software'}
        if args.exercise_agent:
            check = turn('Use shell to run exactly uname -m once and report its actual output. Do not use other tools.',
                         lambda p: p['tool'] == 'shell' and p['arguments'] == {'command': 'uname -m'}, detach=True)
            shells = [item for item in check['effects'] if item['name'] == 'shell' and not item['isError']]
            if len(shells) != 1 or 'aarch64' not in shells[0].get('content', ''):
                raise RuntimeError('Actual uname tool result was not verified')
            required = {'turn.start', 'turn.end', 'model.start', 'model.end', 'tool.start', 'tool.end', 'wait.start', 'wait.end'}
            if not required <= set(check['hooks']):
                raise RuntimeError('Required real lifecycle observations were missing')
            report['agent'] = {'passed': True, 'client_detach': True, 'shell_runs': len(shells), 'hooks': check['hooks']}
        if args.exercise_device:
            with Board() as writer, Board() as reader:
                with reader.watch() as watch:
                    try:
                        writer.matrix.draw(Frame.from_rows(ROWS))
                        snapshot = reader.snapshot()
                        if snapshot['matrix']['frame_hex'] != Frame.from_rows(ROWS).to_hex():
                            raise RuntimeError('Independent framebuffer readback did not match')
                        try:
                            reader.matrix.clear()
                        except RuntimeError:
                            pass
                        else:
                            raise RuntimeError('Concurrent writer was incorrectly accepted')
                        deadline = time.monotonic() + 3
                        seen = False
                        while time.monotonic() < deadline:
                            try:
                                event = watch.get(timeout=.2)
                            except queue.Empty:
                                continue
                            if event.get('kind') == 'matrix' and event.get('state', {}).get('frame_hex') == Frame.from_rows(ROWS).to_hex():
                                seen = True
                                break
                        if not seen:
                            raise RuntimeError('Shared observer did not receive the matrix event')
                    finally:
                        writer.matrix.clear()
            time.sleep(.5)
            with Connection() as client:
                final = client.request('status')
            if final['device']['owner'] is not None or final['device']['display_state'] != 'standby':
                raise RuntimeError('Status ownership did not return after program exit')
            report['device'] = {'passed': True, 'independent_readback': True,
                                'exclusive_writer': True, 'shared_observer': True,
                                'status_restored': True}
            if args.exercise_agent:
                name = 'projects/torque-validation-' + str(time.time_ns()) + '/main.py'
                source = ('import time\nfrom torque import Board, Frame\n'
                          'with Board() as b:\n    try:\n'
                          f'        b.matrix.draw(Frame.from_rows({ROWS!r}))\n'
                          '        print(b.snapshot()["matrix"]["frame_hex"])\n'
                          '        time.sleep(2)\n    finally:\n        b.matrix.clear()\n')
                program = str(Path(state['workspace']) / name)
                def approve(pending):
                    return (pending['tool'] == 'write_file' and pending['arguments'] == {'path': name, 'content': source}
                            or pending['tool'] == 'run_program' and pending['arguments'] in
                            ({'path': program, 'arguments': []}, {'path': name, 'arguments': []}))
                prompt = (f'Create and run {name} using write_file then run_program with an empty arguments list. '
                          'Use exactly the following source without adding comments or changing whitespace. '
                          f'Do not use shell.\nSource:\n{source}')
                check = turn(prompt, approve, detach=True)
                contents = (Path(state['workspace']) / name).read_text()
                programs = [e for e in check['effects'] if e['name'] == 'run_program' and not e['isError']]
                if contents != source or len(programs) != 1 or Frame.from_rows(ROWS).to_hex() not in programs[0].get('content', ''):
                    raise RuntimeError('Agent-generated program did not produce the expected device readback')
                report['first_program'] = {'passed': True, 'path': name, 'finite': True, 'firmware_upload': False}
        if not args.exercise_agent and not state['device']['ready']:
            raise RuntimeError(state['device']['error'])
        report['passed'] = True
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(report, stream, indent=2)
        print(json.dumps(report, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print('Torque verification: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
