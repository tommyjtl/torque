#!/usr/bin/env python3
"""Cycle MCU RGB LED 3 through three colors three times, then turn it off."""
import signal
import argparse
import time
from torque import Board


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    signal.signal(signal.SIGTERM, interrupted)
    with Board() as board:
        led = board.rgb(3)
        try:
            for _ in range(3):
                for color in ((True, False, False), (False, True, False), (False, False, True)):
                    led.set(*color)
                    time.sleep(0.3)
        finally:
            led.set(False, False, False)
    print('Color commands completed; MCU LED requested off.')


if __name__ == '__main__':
    main()
