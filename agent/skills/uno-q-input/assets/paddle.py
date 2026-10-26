#!/usr/bin/env python3
"""Catch a falling pixel. Default is offline preview; --play changes outputs."""
import argparse
from contextlib import ExitStack
import random
import signal
import time

from torque import Board, Frame
from torque.input import Keypad, KeypadBusy, KeypadUnavailable, KeypadDisconnected


class Game:
    def __init__(self, seed=7):
        self.random = random.Random(seed)
        self.paddle, self.x, self.y = 6, self.random.randrange(13), 0
        self.score = self.missed = 0
        self.paused = False
        self.elapsed = 0.0
        self.actions = {'left': 0, 'right': 0, 'pause': 0}

    def move(self, direction):
        if not self.paused:
            previous = self.paddle
            self.paddle = max(1, min(11, self.paddle + direction))
            if self.paddle != previous:
                self.actions['right' if direction > 0 else 'left'] += 1

    def press(self, key):
        if key in ('KP5', 'KNOB_PRESS'):
            self.paused = not self.paused
            self.actions['pause'] += 1
        elif key in ('KP4', 'LEFT', 'KNOB_DOWN'):
            self.move(-1)
        elif key in ('KP6', 'RIGHT', 'KNOB_UP'):
            self.move(1)

    def step(self, seconds):
        if self.paused:
            return
        self.elapsed += seconds
        while self.elapsed >= 0.25:
            self.elapsed -= 0.25
            self.y += 1
            if self.y == 7:
                if abs(self.x - self.paddle) <= 1:
                    self.score += 1
                else:
                    self.missed += 1
                self.x, self.y = self.random.randrange(13), 0

    def frame(self):
        pixels = [0] * 104
        pixels[self.y * 13 + self.x] = 1
        for x in range(self.paddle - 1, self.paddle + 2):
            pixels[7 * 13 + x] = 1
        return Frame(pixels)


def interrupted(*_):
    raise KeyboardInterrupt


def play(seconds, input_mode, seed, address=None):
    game = Game(seed)
    reason = 'duration'
    with ExitStack() as stack:
        keypad = None
        if input_mode != 'none':
            try:
                keypad = stack.enter_context(Keypad(address=address))
            except KeypadBusy:
                raise
            except KeypadUnavailable:
                if input_mode == 'keypad':
                    raise
                print('No readable keypad: running finite autoplay.')
        if keypad:
            print('4/6 or knob down/up move; 5 or knob press pause; Escape exits.')
        else:
            print(f'Autoplay for {seconds:g} seconds.')
        board = stack.enter_context(Board())
        start = previous = time.monotonic()
        next_move = start
        last = None
        try:
            while time.monotonic() - start < seconds:
                events = []
                if keypad:
                    try:
                        events = keypad.poll(0.02)
                    except KeypadDisconnected:
                        print('Keypad disconnected: stopping the game.')
                        reason = 'disconnected'
                        break
                else:
                    time.sleep(0.02)
                now = time.monotonic()
                quit_requested = False
                for event in events:
                    if event.action == 'press':
                        if event.key == 'ESC':
                            quit_requested = True
                            break
                        game.press(event.key)
                        if event.key in ('KP4', 'KP6', 'LEFT', 'RIGHT'):
                            next_move = now + 0.15
                if quit_requested:
                    reason = 'escape'
                    break
                if keypad and now >= next_move:
                    left = keypad.is_down('KP4') or keypad.is_down('LEFT')
                    right = keypad.is_down('KP6') or keypad.is_down('RIGHT')
                    game.move(int(right) - int(left))
                    next_move = now + 0.15
                if keypad is None:
                    game.paddle = max(1, min(11, game.x))
                game.step(min(now - previous, 0.25))
                previous = now
                frame = game.frame()
                if frame != last:
                    board.matrix.draw(frame)
                    last = frame
        finally:
            board.matrix.clear()
    print(f'Finished ({reason}): caught={game.score}, missed={game.missed}; actions={game.actions}.')
    return 1 if reason == 'disconnected' else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--play', action='store_true')
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--input', choices=('auto', 'keypad', 'none'), default='auto')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--address', help='Choose one discovered Bluetooth address if needed')
    args = parser.parse_args(argv)
    if not 0.1 <= args.seconds <= 120:
        parser.error('--seconds must be 0.1..120')
    if not args.play:
        print('Offline preview:')
        pixels = Game(args.seed).frame().pixels
        for row in range(8):
            print(''.join('#' if pixel else '.' for pixel in pixels[row * 13:(row + 1) * 13]))
        print('Use --play --input keypad for manual controls, or --play --input none for autoplay.')
        return 0
    signal.signal(signal.SIGTERM, interrupted)
    try:
        return play(args.seconds, args.input, args.seed, args.address)
    except KeyboardInterrupt:
        print('Stopped; output cleanup requested.')
        return 130
    except (KeypadUnavailable, OSError, RuntimeError) as error:
        print('Game stopped: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
