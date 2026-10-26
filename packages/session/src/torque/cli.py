"""Torque terminal frontend. Disconnecting the frontend does not resend a turn."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .protocol import Connection
from . import control_cli


def show(connection, cursor, *, interactive, epoch=None):
    answered = set()
    while True:
        batch = connection.request('events', after=cursor)
        if epoch and epoch != batch['epoch']:
            raise RuntimeError('Torque restarted. Inspect torque status before resuming; no prompt was resent.')
        epoch = batch['epoch']
        if batch['gap']:
            print('\n[Some earlier output is unavailable; current state was refreshed.]')
        for event in batch['events']:
            if event['type'] == 'engine.output':
                output = event['event']
                if output['type'] == 'text_delta':
                    print(output['delta'], end='', flush=True)
            elif event['type'] == 'worker.error':
                print('\nEngine error: ' + event['error'])
        cursor = batch['cursor']
        for pending in batch['session']['pending']:
            token = pending['request_id']
            if token in answered:
                continue
            print('\nApprove ' + pending['tool'] + ': ' + json.dumps(pending['arguments'], ensure_ascii=False))
            allow = interactive and input('Run this exact action once? [y/N] ').strip().lower() == 'y'
            connection.request('approve', request_id=token, session_id=pending['session_id'], allow=allow)
            answered.add(token)
        if not batch['session']['active']:
            print()
            return batch['session']
        time.sleep(0.15)


def interrupt_in_chat(connection):
    # A signal may interrupt a partial socket read; discard that stream first.
    connection.reconnect()
    print('\nStopping active work and resetting outputs…', flush=True)
    with control_cli.timeout(connection, 65):
        result = connection.request('reset', blank=False)
    state = connection.request('status')
    if result['passed']:
        print('Work stopped; managed outputs reset to standby.')
    else:
        print('Work stopped; output reset incomplete: ' + result.get('error', 'readback failed'))
    return state


def chat_turn(connection, cursor, *, epoch):
    try:
        return show(connection, cursor, interactive=True, epoch=epoch)
    except KeyboardInterrupt:
        return interrupt_in_chat(connection)


def main(argv=None):
    from .runtime import process_lease
    try:
        with process_lease():
            return _main(argv)
    except (RuntimeError,OSError,ValueError) as error:
        print('torque: '+str(error),file=sys.stderr)
        return 1


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    from . import update
    update.add_commands(sub)
    control_cli.add_commands(sub)
    parser.add_argument('--permissions', choices=['auto', 'ask', 'full'], default=None,
                        help='Turn/session policy; auto runs routine board/workspace actions')
    for name in ('status', 'doctor'):
        sub.add_parser(name).add_argument('--json', action='store_true')
    ask = sub.add_parser('ask')
    ask.add_argument('prompt')
    ask.add_argument('--resume', action='store_true')
    ask.add_argument('--permissions', choices=['auto', 'ask', 'full'], default=argparse.SUPPRESS)
    sub.add_parser('attach')
    sub.add_parser('cancel')
    device = sub.add_parser('device')
    device.add_argument('action', choices=['snapshot', 'health'])
    run = sub.add_parser('run')
    run.add_argument('script', type=Path)
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    example = sub.add_parser('example', help='List or run bundled examples')
    example.add_argument('--mode', default='run', help='Launch mode from the manifest; place before SLUG')
    example.add_argument('slug', nargs='?')
    example.add_argument('arguments', nargs=argparse.REMAINDER, help='Arguments forwarded to the example')
    args = parser.parse_args(argv)
    try:
        if args.command == 'update':
            return update.dispatch(args)
        if args.command == 'example':
            from . import examples
            if args.slug is None:
                if args.mode != 'run':
                    raise ValueError('Select an example slug when using --mode')
                catalog = examples.discover()
                for entry in catalog.values():
                    print(f'{entry.slug:24} {entry.title} [{", ".join(entry.modes)}]\n  {entry.description}')
                return 0
            forwarded = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
            return examples.run(args.slug, forwarded, mode=args.mode)
        with Connection() as connection:
            state = connection.request('status')
            if args.command in ('model', 'reset'):
                return control_cli.run(connection, args)
            if args.command in ('status', 'doctor'):
                if args.json:
                    print(json.dumps(state, indent=2))
                else:
                    print('Torque · ' + state['model'])
                    if state.get('release_id'):
                        print('Release: ' + state['release_id'])
                    print('Workspace: ' + state['workspace'])
                    print('Device: ' + ('ready' if state['device']['ready'] else state['device']['error']))
                    if state['device'].get('reset_fault'):
                        print('Outputs: reset verification failed; automatic repaint is suspended.')
                    print('Session: ' + state['outcome'])
                    if state.get('maintenance'):
                        print('Control operation: ' + state['maintenance'])
                    if not state['credential_ready']:
                        print('Credential: ' + state['credential_error'])
                    print('Permissions: ' + state['permission_mode'] + '; model requests start only when prompted.')
                return 0 if state['device']['ready'] else 1
            if args.command == 'run':
                path = (Path.cwd() / args.script).resolve()
                if not path.is_relative_to(Path(state['workspace']) / 'projects'):
                    raise ValueError('Run user programs from the Torque projects directory')
                env = os.environ.copy()
                for name in list(env):
                    if name.endswith(('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD')):
                        env.pop(name)
                from .runtime import pinned_python, process_lease
                with process_lease(live=True) as descriptors:
                    options = {'pass_fds': descriptors} if descriptors else {}
                    return subprocess.call([pinned_python(), str(path), *args.arguments], env=env, cwd=path.parent, **options)
            if args.command == 'device':
                print(json.dumps(connection.request('device', operation=args.action, arguments={}), indent=2))
                return 0
            if args.command == 'cancel':
                connection.request('cancel')
                print('Cancellation requested.')
                return 0
            if args.command == 'attach':
                show(connection, 0, interactive=sys.stdin.isatty(), epoch=state['epoch'])
                return 0
            if args.command == 'ask':
                reply = connection.request('prompt', prompt=args.prompt, resume=args.resume, permissions=args.permissions)
                result = show(connection, reply['cursor'], interactive=sys.stdin.isatty(), epoch=state['epoch'])
                return 0 if result['outcome'] == 'end_turn' else 1
            print('Torque · ' + state['model'] + '\nWorkspace: ' + state['workspace'])
            print('Device: ' + ('ready' if state['device']['ready'] else str(state['device']['error'])))
            print('/help for commands. Ctrl-C stops work and resets outputs; /exit leaves chat.')
            if state['active']:
                state = chat_turn(connection, 0, epoch=state['epoch'])
            resume = state['session_id'] is not None
            while True:
                try:
                    prompt = input('\n› ').strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    print()
                    continue
                if not prompt:
                    continue
                if prompt in ('/quit', '/exit'):
                    break
                if prompt == '/help':
                    print('/new starts a conversation; /status shows readiness; /model chooses a model; /reset restores outputs.\n'
                          'Ctrl-C stops active work, resets outputs and returns here; /exit or Ctrl-D leaves chat.\n'
                          'Auto permits routine board/project tools; broader shell commands require approval.\n'
                          'Use --permissions ask or full to choose an explicit policy. Use torque cancel to stop work.')
                    continue
                if prompt == '/new':
                    resume = False
                    continue
                if prompt == '/status':
                    print(json.dumps(connection.request('status'), indent=2))
                    continue
                try:
                    if prompt.startswith('/'):
                        if control_cli.slash(connection, prompt) is None:
                            print('Unknown command. Run /help.')
                        continue
                    reply = connection.request('prompt', prompt=prompt, resume=resume, permissions=args.permissions)
                    chat_turn(connection, reply['cursor'], epoch=state['epoch'])
                except KeyboardInterrupt:
                    interrupt_in_chat(connection)
                    continue
                except (RuntimeError, OSError, ValueError) as error:
                    print('torque: ' + str(error), file=sys.stderr)
                    continue
                resume = True
        return 0
    except KeyboardInterrupt:
        if args.command in ('run','example'):
            print('\nProgram stopped; cleanup is handled by the program.')
            return 130
        if args.command == 'model' and getattr(args, 'model_action', None) != 'test':
            print('\nModel command interrupted.')
            return 130
        try:
            with Connection() as control, control_cli.timeout(control, 65):
                if args.command == 'model':
                    control.request('cancel')
                    print('\nModel probe cancelled.')
                else:
                    result = control.request('reset', blank=False)
                    print('\nWork stopped; outputs reset to standby.' if result['passed'] else
                          '\nWork stopped; output reset incomplete: ' + result.get('error', 'readback failed'))
        except (RuntimeError, OSError):
            print('\nCould not confirm cancellation. Inspect torque status.')
        return 130
    except (RuntimeError, OSError, ValueError) as error:
        print('torque: ' + str(error), file=sys.stderr)
        if args.command == 'doctor':
            print('Check systemctl status torque.service and ~/.config/torque/settings.json.\n'
                  'Run setup privately for a missing credential; never print its value.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
