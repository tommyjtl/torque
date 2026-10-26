#!/usr/bin/env python3
"""Opt-in uncoached matrix on/off acceptance. Leaves the requested blank display."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from torque import Board
from torque.protocol import Connection


def prompt(text, *, resume=False, permissions='auto'):
    with Connection() as client:
        start = client.request('status')
        accepted = client.request('prompt', prompt=text, resume=resume, permissions=permissions)
        cursor = accepted['cursor']
    calls, output = [], []
    with Connection() as client:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            batch = client.request('events', after=cursor)
            if batch['epoch'] != start['epoch'] or batch['gap']:
                raise RuntimeError('Acceptance test lost the authoritative event stream')
            cursor = batch['cursor']
            if batch['session']['pending']:
                client.request('cancel')
                raise RuntimeError('Routine natural-language control unexpectedly required approval')
            for event in batch['events']:
                if event['type'] != 'engine.output':
                    continue
                item = event['event']
                if item['type'] == 'tool_start':
                    calls.append({'name': item['name'], 'input': item.get('input')})
                elif item['type'] == 'text_delta':
                    output.append(item['delta'])
            if not batch['session']['active']:
                if batch['session']['outcome'] != 'end_turn':
                    raise RuntimeError('Natural-language turn failed')
                return {'prompt': text, 'calls': calls, 'reply': ''.join(output), 'approvals': 0}
            time.sleep(.1)
        client.request('cancel')
    raise RuntimeError('Natural-language turn exceeded its time limit')


def run():
    on = prompt('light up all led matrix now')
    time.sleep(1)
    with Board() as board:
        first = board.snapshot()
    with Connection() as client:
        first_status = client.request('status')
    if first['matrix']['frame_hex'] != 'ff' * 13 or first['matrix']['playing']:
        raise RuntimeError('All-on framebuffer did not survive the completed turn')
    if first_status['device']['display_mode'] != 'user':
        raise RuntimeError('User output was not retained above session feedback')
    off = prompt('turn it off', resume=True)
    time.sleep(1)
    with Board() as board:
        second = board.snapshot()
    with Connection() as client:
        second_status = client.request('status')
    if second['matrix']['frame_hex'] != '00' * 13 or second['matrix']['playing']:
        raise RuntimeError('Blank framebuffer did not survive the completed turn')
    if second_status['device']['display_mode'] != 'user':
        raise RuntimeError('Explicit off state was not retained')
    for turn in (on, off):
        names = [call['name'] for call in turn['calls']]
        if any(name not in ('device_snapshot', 'device_capabilities', 'matrix_fill', 'matrix_clear') for name in names):
            raise RuntimeError('Simple control used unnecessary shell, file or program tools')
        if sum(name in ('matrix_fill', 'matrix_clear') for name in names) != 1 or len(names) > 3:
            raise RuntimeError('Expected one direct matrix action and at most two bounded reads')
        if len(turn['reply']) > 500:
            raise RuntimeError('Simple action produced an unnecessarily long response')
    return {'passed': True, 'permission_mode': 'auto', 'on': on, 'off': off,
            'all_on_retained': True, 'blank_retained': True, 'uncoached': True,
            'framebuffer_evidence': True, 'optical_measurement': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise-outputs', action='store_true', required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    try:
        result = run()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(result, stream, indent=2)
        print(json.dumps(result, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print('Natural-language acceptance: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
