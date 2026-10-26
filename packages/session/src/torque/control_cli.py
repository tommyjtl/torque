"""Local control-command parsing shared by the shell and interactive chat."""
import argparse
from contextlib import contextmanager
import json
import shlex
import sys


def add_commands(sub):
    model = sub.add_parser('model', help='Choose, list or test Modular models')
    actions = model.add_subparsers(dest='model_action')
    listing = actions.add_parser('list', help='List models without inference')
    listing.add_argument('--refresh', action='store_true')
    use = actions.add_parser('use', help='Save a model for subsequent turns')
    use.add_argument('model_id')
    test = actions.add_parser('test', help='Run small billable text/tool probes')
    test.add_argument('model_id')
    for parser in (listing, use, test):
        parser.add_argument('--json', action='store_true')
    reset = sub.add_parser('reset', help='Cancel work and restore managed hardware outputs')
    reset.add_argument('--blank', action='store_true')
    reset.add_argument('--json', action='store_true')


@contextmanager
def timeout(connection, seconds):
    sock = getattr(connection, 'socket', None)
    if sock is None:
        yield
        return
    previous = sock.gettimeout()
    sock.settimeout(seconds)
    try:
        yield
    finally:
        sock.settimeout(previous)


def print_models(result, *, numbered=False):
    if result.get('error'):
        print('Discovery: ' + result['error'], file=sys.stderr)
    print('Models · ' + result['source'] + (' (stale/unconfirmed)' if result['stale'] else ''))
    for index, row in enumerate(result['models'], 1):
        prefix = f'{index:2}. ' if numbered else ''
        marker = '*' if row['selected'] else ' '
        discovery = 'listed' if row['discovered'] is True else 'not listed' if row['discovered'] is False else 'unconfirmed'
        check = row.get('verification')
        verified = 'untested' if not check else 'probe passed' if check['passed'] else 'probe failed'
        budget = row['metadata'].get('contextWindow', 'unknown')
        print(f"{prefix}{marker} {row['id']} · {row['source']} · {discovery} · {verified} · context/budget {budget}")
    if result.get('truncated'):
        print(f"Showing {len(result['models'])}/{result['total']} models; select another by exact ID with torque model use MODEL_ID.")


def run(connection, args):
    as_json = getattr(args, 'json', False)
    if args.command == 'reset':
        try:
            with timeout(connection, 65):
                result = connection.request('reset', blank=args.blank)
        except KeyboardInterrupt:
            connection.reconnect()
            print('\nReset continues in the daemon; inspect torque status.')
            return 130
        if as_json:
            print(json.dumps(result, indent=2))
        else:
            print('Reset complete: ' + result['target'] if result['passed'] else 'Reset incomplete: ' + result.get('error', 'readback failed'))
            for name, component in result['components'].items():
                print('  ' + name + ': ' + component['status'] +
                      (' · ' + component['reason'] if component.get('reason') else ''))
        return 0 if result['passed'] else 1
    action = getattr(args, 'model_action', None)
    if action in (None, 'list'):
        if action is None and not sys.stdin.isatty():
            raise ValueError('Model picker requires a terminal; use torque model list or torque model use MODEL_ID')
        try:
            with timeout(connection, 35):
                result = connection.request('model', action='list', refresh=getattr(args, 'refresh', False))
            if as_json:
                print(json.dumps(result, indent=2))
            else:
                print_models(result, numbered=action is None)
            if action == 'list':
                return 0 if result['ok'] else 1
            answer = input('Choose a number or exact ID (Enter cancels): ').strip()
        except KeyboardInterrupt:
            connection.reconnect()
            print('\nModel listing/selection cancelled.')
            return 130
        if not answer:
            return 0
        if answer.isdigit():
            index = int(answer) - 1
            if not 0 <= index < len(result['models']):
                raise ValueError('Invalid model selection')
            answer = result['models'][index]['id']
        action, name = 'use', answer
    else:
        name = args.model_id
    if action == 'test':
        print('Testing model with up to six small billable requests; no hardware/file effects.', file=sys.stderr)
    with timeout(connection, 125 if action == 'test' else 35):
        result = connection.request('model', action=action, model_id=name)
    if as_json:
        print(json.dumps(result, indent=2))
    elif action == 'use':
        print('Selected ' + result['model'] + ' for subsequent turns (' + result['source'] + ').')
        if result.get('stale_discovery'):
            print('Discovery is stale; online availability has not been rechecked.')
    else:
        print('Model probe ' + ('passed' if result['passed'] else 'failed') + ': ' + result['model'])
        if result.get('error'):
            print(result['error'])
    return 0 if action == 'use' or result['passed'] else 1


def slash(connection, text):
    """Return None for other slash commands; never forward parser errors to a model."""
    words = shlex.split(text[1:])
    if not words or words[0] not in ('model', 'reset'):
        return None
    parser = argparse.ArgumentParser(prog='/')
    add_commands(parser.add_subparsers(dest='command'))
    try:
        args = parser.parse_args(words)
    except SystemExit as error:
        return error.code
    return run(connection, args)
