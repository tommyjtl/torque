"""Start one finite benchmark independently of an intermittent SSH connection."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('cpu', 'gpu'))
    parser.add_argument('--repeats', type=int, choices=(1, 3), default=3)
    args = parser.parse_args()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            argv = (process / 'cmdline').read_bytes().split(b'\0')
            if str(ROOT / 'runner.py').encode() in argv:
                raise RuntimeError('This experiment already has a running job')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    logfile = ROOT / 'scratch' / (time.strftime('%Y%m%dT%H%M%S') + '-' + args.mode + '-launch.log')
    with logfile.open('w') as log:
        process = subprocess.Popen([shutil.which('torque'), 'run', str(ROOT / 'runner.py'),
                                    args.mode, '--repeats', str(args.repeats)],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True)
    receipt = {'pid': process.pid, 'mode': args.mode, 'repeats': args.repeats,
               'launch_log': str(logfile), 'native_deadline_seconds': 1200}
    (ROOT / 'scratch/latest-job.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
