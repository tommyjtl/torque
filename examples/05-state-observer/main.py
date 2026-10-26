#!/usr/bin/env python3
"""Observe MCU state for 15 seconds without changing LEDs or playback."""
import json
import argparse
import queue
import time
from torque import Board


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    with Board() as board:
        print(json.dumps(board.snapshot(), indent=2), flush=True)
        with board.watch() as observer:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    event = observer.get(timeout=min(0.2, max(0.001, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                print(json.dumps(event, separators=(',', ':')), flush=True)


if __name__ == '__main__':
    main()
