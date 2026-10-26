#!/usr/bin/env python3
"""Show a heart and an asymmetric border, then clear the matrix."""
import signal
import argparse
import time
from torque import Board, Frame

HEART = Frame.from_rows([
    '...##...##...',
    '..####.####..',
    '.###########.',
    '.###########.',
    '..#########..',
    '...#######...',
    '....#####....',
    '......#......',
])
BORDER = Frame.from_rows([
    '#############',
    '##..........#',
    '#.#.........#',
    '#...........#',
    '#...........#',
    '#...........#',
    '#...........#',
    '#############',
])


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    signal.signal(signal.SIGTERM, interrupted)
    with Board() as board:
        try:
            for frame in (HEART, BORDER):
                board.matrix.draw(frame)
                time.sleep(0.8)
        finally:
            board.matrix.clear()
    print('Both frame commands completed; matrix requested blank.')


if __name__ == '__main__':
    main()
