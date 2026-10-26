#!/usr/bin/env python3
"""Explicit service-restart check, without reinstalling, flashing or model calls."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
from system import run, wait_for_ready


def compare(before_status, before, after_status, after):
    if before_status['epoch'] == after_status['epoch']:
        raise RuntimeError('Daemon execution did not change')
    if after['boot_id'] != before['boot_id']:
        raise RuntimeError('MCU boot changed during a daemon-only restart')
    if after_status['device']['display_mode'] != 'user':
        raise RuntimeError('Retained user display was not adopted')
    if after['matrix']['frame_hex'] != before['matrix']['frame_hex'] or after['matrix']['playing'] != before['matrix']['playing']:
        raise RuntimeError('Retained framebuffer changed')
    if after['command_id'] != before['command_id']:
        raise RuntimeError('An actuator command was replayed during restart')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise-restart', action='store_true', required=True)
    parser.add_argument('--user', default=os.environ.get('SUDO_USER'))
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0 or not args.user:
            raise RuntimeError('Use sudo for this explicit system-service restart check')
        account = pwd.getpwnam(args.user)
        if account.pw_uid == 0:
            raise RuntimeError('The Torque service user must be a normal account')
        launcher = '/usr/local/bin/torque'
        before_status = wait_for_ready(launcher, args.user)
        if before_status['active'] or before_status['device']['display_mode'] != 'user':
            raise RuntimeError('Finish the current turn and set a retained matrix frame before this check')
        before = json.loads(run([launcher, 'device', 'snapshot'], user=args.user).stdout)
        run(['systemctl', 'restart', 'torque.service'])
        after_status = wait_for_ready(launcher, args.user, timeout=60)
        after = json.loads(run([launcher, 'device', 'snapshot'], user=args.user).stdout)
        compare(before_status, before, after_status, after)
        report = {'passed': True, 'release': Path('/opt/torque/current').resolve().name,
                  'retained_frame_after_daemon_restart': True,
                  'retained_blank_after_daemon_restart': after['matrix']['frame_hex'] == '00' * 13,
                  'no_actuator_replay_on_restart': True, 'firmware_boot_unchanged': True,
                  'before_command_id': before['command_id'], 'after_command_id': after['command_id'],
                  'permission_default': after_status['permission_mode']}
        path = Path(account.pw_dir) / '.cache/torque/natural-rollout.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        os.fchown(fd, account.pw_uid, account.pw_gid)
        with os.fdopen(fd, 'w') as stream:
            json.dump(report, stream, indent=2)
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Restart verification: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
