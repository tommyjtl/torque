#!/usr/bin/env python3
"""Cycle the Linux-controlled user RGB LED, restoring its original state."""
import argparse
import math
from pathlib import Path
import signal
import sys
import time

# Allow the Linux-only demo to run from a checkout without pip or a venv.
for parent in Path(__file__).resolve().parents:
    if (parent / 'packages/device/src/unoq_control').is_dir():
        sys.path.insert(0, str(parent / 'packages/device/src'))
        break
from unoq_control.leds import CHANNELS, UserLed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--interval', type=float, default=0.3)
    parser.add_argument('--status', action='store_true', help='Read state without changing any LED')
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100 or not math.isfinite(args.interval) or not 0.01 <= args.interval <= 10:
        parser.error('cycles must be 1..100; interval must be 0.01..10 seconds')
    led = UserLed()
    if args.status:
        for name, (brightness, maximum, trigger) in led.original.items():
            print(f'{name}: brightness={brightness}/{maximum}, trigger={trigger or "unavailable"}')
        return 0
    # SIGTERM and Ctrl-C both enter the restoration path.
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    led.cycle(args.cycles, args.interval)
    print('Color cycle finished; original LED brightness and triggers restored.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Stopped; restoration attempted.')
        sys.exit(130)
    except OSError as error:
        print('LED operation failed: ' + str(error) + '. Check LED access; no permissions were changed.', file=sys.stderr)
        sys.exit(1)
