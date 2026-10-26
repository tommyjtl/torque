#!/usr/bin/env python3
"""Upload a finite sweep once; the MCU plays frames without per-frame RPCs."""
import argparse
import signal
import time
from torque import Board, Frame


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detach', action='store_true', help='Exit after play; MCU finishes three sweeps and holds the last column')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    frames = [Frame(tuple(int(i % 13 == column) for i in range(104))) for column in range(13)]
    detached = False
    with Board() as board:
        try:
            upload = board.matrix.load(frames, durations=100)
            board.matrix.play(repeat=3)
            if args.detach:
                detached = True
                print(f'Animation {upload} started; MCU will finish without this Python process.')
                return
            deadline = time.monotonic() + 15
            while board.matrix.status()['playing']:
                if time.monotonic() > deadline:
                    raise TimeoutError('Animation did not finish within the observation window')
                time.sleep(0.1)
        finally:
            if not detached:
                board.matrix.clear()
    print('MCU reported playback finished; matrix requested blank.')


if __name__ == '__main__':
    main()
