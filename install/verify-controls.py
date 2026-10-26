#!/usr/bin/env python3
"""Readiness by default; explicit flags exercise bounded inference/output reset."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def command(*arguments):
    result = subprocess.run(['/usr/local/bin/torque', *arguments], capture_output=True, text=True, timeout=130)
    if result.returncode:
        raise RuntimeError('Torque command failed: ' + ' '.join(arguments[:2]))
    return json.loads(result.stdout)


def verify(*, models=False, reset=False):
    from torque import Board, Frame
    from torque.installation import verify_python_sources
    before = command('status', '--json')
    if before['active'] or before['pending'] or before['device']['owner'] is not None:
        raise RuntimeError('Keep Torque idle with no device program during acceptance')
    help_text = subprocess.run(['/usr/local/bin/torque', '--help'], capture_output=True, text=True, check=True).stdout
    if not before['device']['ready'] or not all(word in help_text for word in ('model', 'reset')):
        raise RuntimeError('Updated commands or device readiness unavailable')
    settings_path = Path.home() / '.config/torque/settings.json'
    settings_before = settings_path.read_bytes()
    settings = json.loads(settings_before)
    integrity = verify_python_sources(settings['release_root'])
    with Board() as board:
        identity = board.info()
    report = {'passed': False, 'release': Path('/opt/torque/current').resolve().name,
              'model': before['model'], 'model_commands': True, 'reset_command': True,
              'inference_exercised': models, 'outputs_exercised': reset, 'optical_measurement': False}
    report['installed_source_parity'] = integrity
    if models:
        print('Running explicit small text/tool probes; no project or hardware effects.', file=sys.stderr)
        listing = command('model', 'list', '--refresh', '--json')
        selected = command('model', 'use', before['model'], '--json')
        probe = command('model', 'test', before['model'], '--json')
        report.update(discovery_source=listing['source'], selected_same_model=not selected['changed'], model_probe=probe)
        if not probe['passed']:
            raise RuntimeError('Text/tool probe did not pass')
    if reset:
        if before['device'].get('display_mode') != 'status':
            raise RuntimeError('Acceptance will not overwrite an existing user-retained scene')
        blank = command('reset', '--blank', '--json')
        time.sleep(.5)
        with Board() as board:
            state = board.snapshot()
        current = command('status', '--json')
        blank_retained = (state['matrix']['frame_hex'] == '00' * 13 and not state['matrix']['playing'] and
                          current['device']['display_mode'] == 'user')
        standby = command('reset', '--json')
        with Board() as board:
            state = board.snapshot()
        cue = Frame.from_rows(json.loads((Path(settings['release_root']) / 'assets/status.json').read_text())['standby'])
        report.update(blank=blank, standby=standby, blank_retained=blank_retained,
                      standby_readback=state['matrix']['frame_hex'] == cue.to_hex())
        if not blank_retained or not report['standby_readback']:
            raise RuntimeError('Reset readback/retention did not match')
    after = command('status', '--json')
    with Board() as board:
        final_identity = board.info()
    report.update(firmware_boot_unchanged=identity == final_identity,
                  settings_unchanged=settings_before == settings_path.read_bytes(),
                  session_preserved=before['session_id'] == after['session_id'],
                  permissions_preserved=before['default_permission_mode'] == after['default_permission_mode'],
                  ownership_released=after['device']['owner'] is None)
    report['passed'] = all(report[key] for key in ('firmware_boot_unchanged', 'settings_unchanged', 'session_preserved',
                                                  'permissions_preserved', 'ownership_released'))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise-models', action='store_true', help='Authorize bounded billable text/tool probes')
    parser.add_argument('--exercise-reset', action='store_true', help='Authorize blank and standby reset tests; leaves standby')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(models=args.exercise_models, reset=args.exercise_reset)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        result = {'passed': False, 'error': str(error)}
    if args.output:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
