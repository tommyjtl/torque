#!/usr/bin/env python3
"""Preview Dot Matrix Animations offline; --play enables the UNO Q gallery/keypad."""
import argparse
import math
from pathlib import Path
import signal
import select
import os
import sys
import time
from xml.sax.saxutils import escape
from torque import Board, Frame
from torque.animations import half_helix, heart_pulse
from torque.input import Keypad, KeypadUnavailable, KeypadBusy, KeypadDisconnected, input_capabilities


def neon_drift(peak):
    """A soft diagonal front traveling from the top-right to the bottom-left."""
    frames = []
    for step in range(24):
        pixels = [0] * 104
        for y in range(5):
            for x in range(5):
                distance = ((y + 4 - x) - 10 * step / 24) % 10
                distance = min(distance, 10 - distance)
                pixels[(y + 1) * 13 + x + 4] = int(peak * max(0, 1 - distance / 1.5) + 0.5)
        frames.append(Frame(pixels, bits=3))
    return frames


def perimeter_path():
    return ([(x, 0) for x in range(5)] + [(4, y) for y in range(1, 5)] +
            [(x, 4) for x in range(3, -1, -1)] + [(0, y) for y in range(3, 0, -1)])


def crt_glide(peak):
    """Top-to-bottom CRT scanline with a fading wake and dark rows ahead."""
    frames = []
    for scan_row in range(5):
        pixels = [0] * 104
        for y in range(scan_row + 1):
            level = int(peak * 0.5**(scan_row - y) + 0.5)
            for x in range(5):
                pixels[(y + 1) * 13 + x + 4] = level
        # Preserve the reference's stepped scan at a readable speed while
        # keeping the gallery's common 25 ms frame clock and 32-frame limit.
        frames.extend([Frame(pixels, bits=3)] * 6)
    return frames


def field_frames(peak, count, field):
    """Quantize a small brightness field into full, masked UNO Q frames."""
    frames = []
    for step in range(count):
        pixels = [0] * 104
        for y in range(5):
            for x in range(5):
                pixels[(y + 1) * 13 + x + 4] = int(peak * min(1, max(0, field(step, x, y))) + 0.5)
        frames.append(Frame(pixels, bits=3))
    return frames


def pulse(distance, radius, width=1):
    return max(0, 1 - abs(distance - radius) / width)


def echo_ring(peak):
    """A centered diamond ripple followed by a weaker echo."""
    def field(step, x, y):
        distance = abs(x - 2) + abs(y - 2)
        radius = 7 * step / 32
        lead = pulse(distance, radius)
        echo = 0.45 * pulse(distance, radius - 1.75) if radius >= 1.75 else 0
        return max(lead, echo) * (1 - 0.06 * distance)
    return field_frames(peak, 32, field)


def origin_wave(peak):
    """One expansion from local (1,1); repeat the accent as a gallery loop."""
    return field_frames(peak, 32, lambda step, x, y:
                        pulse(abs(x - 1) + abs(y - 1), 8 * step / 32, 1.25))


def prism_bloom(peak):
    """Crossfade original geometric star, diamond, petal and cross fields."""
    def field(step, x, y):
        dx, dy = x - 2, y - 2
        radius = math.hypot(dx, dy)
        motifs = (float(abs(dx) == abs(dy)),
                  pulse(abs(dx) + abs(dy), 2, 1.2),
                  pulse(radius, 2, 0.9) * (0.35 + 0.65 * abs(math.sin(2 * math.atan2(dy, dx)))),
                  max(0, 1 - min(abs(dx), abs(dy))) * (1 - 0.12 * max(abs(dx), abs(dy))))
        phase = step / 8
        start = int(phase)
        blend = (1 - math.cos(math.pi * (phase - start))) / 2
        return motifs[start] * (1 - blend) + motifs[(start + 1) % 4] * blend
    return field_frames(peak, 32, field)


def sound_bars(peak):
    """Five bottom-anchored synthetic bars; these are not measured audio."""
    def field(step, x, y):
        height = 3 + 2 * math.sin(math.tau * step / 24 + 1.3 * x)
        fill = min(1, max(0, height - (4 - y)))
        above = min(1, max(0, height - (5 - y)))
        return fill * (1 if above < 1 else 0.7)
    return field_frames(peak, 24, field)


def chase_frames(peak, path, count, secondary=0, fold=False):
    """Interpolate a bright head and fading tail along a cyclic path."""
    frames = []
    for step in range(count):
        levels = [[0.0] * 5 for _ in range(5)]
        position = step * len(path) / count
        head, blend = int(position), position % 1
        for offset, strength in ((0, 1), (len(path) // 2, secondary)):
            for age, weight in enumerate((1, 0.65, 0.35, 0.15)):
                for advance, fraction in ((0, 1 - blend), (1, blend)):
                    x, y = path[(head + advance + offset - age) % len(path)]
                    levels[y][x] += strength * weight * fraction
        if fold:
            for advance, fraction in ((0, 1 - blend), (1, blend)):
                x, y = path[(head + advance) % len(path)]
                if x in (0, 4) and y in (0, 4):
                    levels[1 if y == 0 else 3][1 if x == 0 else 3] = 0.4 * fraction
        else:
            levels[2][2] = 0.15
        pixels = [0] * 104
        for y in range(5):
            for x in range(5):
                pixels[(y + 1) * 13 + x + 4] = int(peak * min(1, levels[y][x]) + 0.5)
        frames.append(Frame(pixels, bits=3))
    return frames


def mobius_run(peak):
    """One outer-edge train with a subtle inward cue at each corner fold."""
    return chase_frames(peak, perimeter_path(), 32, fold=True)


def plasma_veil(peak):
    """Two fading chases on a round perimeter, with a steady dim center."""
    path = [(x, y) for y in range(5) for x in range(5) if 4 <= (x - 2)**2 + (y - 2)**2 <= 5]
    path.sort(key=lambda point: (math.atan2(point[1] - 2, point[0] - 2) + math.pi / 2) % math.tau)
    return chase_frames(peak, path, 24, secondary=0.5)


KEYPAD_ANIMATIONS = {'half-helix': ('Half Helix', half_helix),
              'neon-drift': ('Neon Drift', neon_drift),
              'crt-glide': ('CRT Glide', crt_glide),
              'echo-ring': ('Echo Ring', echo_ring),
              'origin-wave': ('Origin Wave', origin_wave),
              'prism-bloom': ('Prism Bloom', prism_bloom),
              'sound-bars': ('Sound Bars', sound_bars),
              'mobius-run': ('Mobius Run', mobius_run),
              'plasma-veil': ('Plasma Veil', plasma_veil)}

# Additional clips are available by name and in offline previews, without using
# a number key or a tenth resident slot in the interactive gallery.
ANIMATIONS = {**KEYPAD_ANIMATIONS, 'heart-pulse': ('Heart Pulse', heart_pulse)}
DIGITS = {str(index): name for index, name in enumerate(KEYPAD_ANIMATIONS, 1)}


def render_frames(peak=7, animation='half-helix'):
    if type(peak) is not int or not 1 <= peak <= 7:
        raise ValueError('Peak brightness must be an integer in 1..7')
    if not isinstance(animation, str) or animation not in ANIMATIONS:
        raise ValueError('Unknown animation')
    return ANIMATIONS[animation][1](peak)


def write_preview(frames, duration_ms, destination, title='Half Helix'):
    """Discrete levels only; the browser does not interpolate extra brightness."""
    period = len(frames) * duration_ms / 1000
    times = ';'.join(f'{i / len(frames):.8f}' for i in range(len(frames) + 1))
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="650" height="400" viewBox="0 0 650 400">',
             f'<title>{escape(title)} — quantized 0–7 software preview</title>',
             '<rect width="650" height="400" rx="24" fill="#0b1018"/>']
    for i in range(104):
        levels = [frame.pixels[i] for frame in frames]
        # A faint unlit dot shows the physical grid; it is not LED output.
        values = ';'.join(f'{0.10 + 0.90 * level / 7:.5f}' for level in [*levels, levels[0]])
        parts.append(f'<circle cx="{25 + 50 * (i % 13)}" cy="{25 + 50 * (i // 13)}" r="13" '
                     f'fill="#64aeff" opacity="{0.10 + 0.90 * levels[0] / 7:.5f}">'
                     f'<animate attributeName="opacity" values="{values}" keyTimes="{times}" '
                     f'dur="{period:.3f}s" calcMode="discrete" repeatCount="indefinite"/></circle>')
    parts.append('</svg>')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text('\n'.join(parts) + '\n')


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


class Player:
    def __init__(self, board, duration_ms):
        self.board, self.duration_ms, self.dirty = board, duration_ms, False
        self.cached = {}

    def prepare(self, clips):
        matrix = self.board.matrix
        if not all(callable(getattr(matrix, method, None)) for method in ('cache', 'play_cached')):
            print('Resident presets unavailable in this SDK; selections will upload their clips.', flush=True)
            return False
        limits = self.board.capability('matrix-presets')
        if not isinstance(limits, dict) or type(limits.get('max_presets')) is not int or limits['max_presets'] < len(clips):
            print('Resident presets unavailable on this controller; selections will upload their clips.', flush=True)
            return False
        for slot, (name, frames) in enumerate(clips.items(), 1):
            print(f'Preloading {slot}/{len(clips)}: {ANIMATIONS[name][0]}', flush=True)
            matrix.load(frames, durations=self.duration_ms)
            self.dirty = True
            matrix.cache(slot)
            self.cached[tuple(frames)] = slot
        print('Presets ready: each selection now sends one playback command.', flush=True)
        return True

    def start(self, frames, repeat=1):
        slot = self.cached.get(tuple(frames))
        if slot is not None:
            self.board.matrix.play_cached(slot, repeat=repeat)
            self.dirty = True
        else:
            self.board.matrix.load(frames, durations=self.duration_ms)
            self.dirty = True
            self.board.matrix.play(repeat=repeat)
        self.deadline = (time.monotonic() + len(frames) * self.duration_ms * repeat / 1000 + 10
                         if repeat else None)

    def playing(self):
        playing = self.board.matrix.status()['playing']
        if playing and self.deadline is not None and time.monotonic() > self.deadline:
            raise TimeoutError('MCU playback exceeded the observation window')
        return playing

    def wait(self):
        while self.playing():
            time.sleep(0.1)

    def clear(self):
        if self.dirty:
            self.board.matrix.clear()
            self.dirty = False


def play(frames, duration_ms, repeat):
    signal.signal(signal.SIGTERM, interrupted)
    with Board() as board:
        player = Player(board, duration_ms)
        try:
            player.start(frames, repeat)
            player.wait()
        finally:
            player.clear()
    print('MCU reported playback finished; matrix requested blank. LEDs were not optically measured.')


class KeyboardDisconnected(OSError):
    pass


KEYPAD_KEYS = {**DIGITS, **{'KP' + digit: name for digit, name in DIGITS.items()}, 'ESC': 'quit'}


class KeychronKeys:
    """Translate shared project input events into gallery selections."""
    def __init__(self, address=None):
        self.keypad = Keypad(address=address)
        self.node = self.keypad.identity['node']

    def poll(self, timeout=0.01):
        try:
            events = self.keypad.poll(timeout=timeout)
        except KeypadDisconnected as error:
            raise KeyboardDisconnected(str(error)) from error
        return [KEYPAD_KEYS[event.key] for event in events
                if event.action == 'press' and event.key in KEYPAD_KEYS]

    def close(self):
        self.keypad.close()


def detect_keyboard(address=None):
    capabilities = input_capabilities(address=address)
    if capabilities['selection_required']:
        raise KeypadUnavailable('Several matching keypads are readable; select one with --keyboard-address')
    if not capabilities['available']:
        if address is not None:
            raise KeypadUnavailable('The selected keypad is unavailable; wake it and check input_capabilities()')
        return None
    # A busy lease or an identity/discovery race is an error, not permission to
    # select a different keypad or silently begin autoplay.
    return KeychronKeys(address=address)


class TerminalKeys:
    """Explicit SSH/local terminal input; always restore terminal settings."""
    def __init__(self):
        if not sys.stdin.isatty():
            raise ValueError('--input terminal requires an interactive terminal (use ssh -t)')
        import termios
        import tty
        self.fd, self.termios = sys.stdin.fileno(), termios
        self.previous = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)

    def poll(self, timeout=0.1):
        if not select.select([self.fd], [], [], timeout)[0]:
            return []
        data = os.read(self.fd, 1024)
        if not data:
            raise KeyboardDisconnected('Terminal input closed')
        mapping = {ord(digit): name for digit, name in DIGITS.items()}
        mapping.update({ord('q'): 'quit', ord('Q'): 'quit', 27: 'quit', 4: 'quit'})
        return [mapping[key] for key in data if key in mapping]

    def close(self):
        self.termios.tcsetattr(self.fd, self.termios.TCSADRAIN, self.previous)


def gallery(player, clips, repeat):
    for cycle in range(repeat):
        for name, frames in clips.items():
            print(f'Round {cycle + 1}/{repeat}: {ANIMATIONS[name][0]} (once)', flush=True)
            player.start(frames, repeat=1)
            player.wait()


def interactive(player, clips, source):
    menu = ' · '.join(f'{digit} {ANIMATIONS[name][0]}' for digit, name in DIGITS.items())
    print(menu + '. Select a continuous loop; Esc/Ctrl-C exits.', flush=True)
    active, selected, next_health = False, None, 0
    while True:
        actions = source.poll(timeout=0.01)
        if 'quit' in actions:
            return
        if actions:
            name = actions[-1]  # Latest press supersedes any clip still playing.
            if name != selected or not active:
                print(ANIMATIONS[name][0] + ' (looping)', flush=True)
                player.start(clips[name], repeat=0)
                active, selected = True, name
                next_health = time.monotonic() + 0.25
        if active and time.monotonic() >= next_health:
            if not player.playing():
                player.clear()
                active = False
            next_health = time.monotonic() + 0.25


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--play', action='store_true', help='Upload frames and play on the current grayscale controller')
    parser.add_argument('--animation', choices=ANIMATIONS, help='Select one animation instead of the gallery/keypad')
    parser.add_argument('--output-dir', type=Path, default=Path('projects/dot-matrix-animations'))
    parser.add_argument('--preview', type=Path, help='SVG path for a single --animation')
    parser.add_argument('--input', choices=('auto', 'keyboard', 'terminal', 'none'), default='auto',
                        help='Auto detects a readable Bluetooth Keychron; none runs the finite gallery')
    parser.add_argument('--keyboard-address', help='Optional discovered Bluetooth address when several keypads match')
    parser.add_argument('--peak', type=int, default=7, choices=range(1, 8), help='Peak native brightness, 1..7')
    parser.add_argument('--frame-ms', type=int, default=25, help='Frame duration in ms (default 25)')
    parser.add_argument('--repeat', type=int, default=3, help='Gallery rounds or repetitions of one selected clip')
    args = parser.parse_args(argv)
    if not 20 <= args.frame_ms <= 60000:
        parser.error('--frame-ms must be in 20..60000')
    if not 1 <= args.repeat <= 65535:
        parser.error('--repeat must be in 1..65535')
    if args.preview and not args.animation:
        parser.error('--preview requires --animation; use --output-dir for the gallery')
    if args.animation and args.input in ('keyboard', 'terminal'):
        parser.error('--animation selects one clip; omit it to enable keyboard selection')
    if args.keyboard_address and (args.animation or args.input in ('none', 'terminal')):
        parser.error('--keyboard-address selects a keypad with --input auto or keyboard, without --animation')
    names = ([args.animation] if args.animation else
             list(KEYPAD_ANIMATIONS if args.play else ANIMATIONS))
    clips = {name: render_frames(args.peak, name) for name in names}
    for name, frames in clips.items():
        destination = args.preview or args.output_dir / (name + '.svg')
        write_preview(frames, args.frame_ms, destination, ANIMATIONS[name][0])
        print(f'{ANIMATIONS[name][0]}: {destination}; {len(frames)} frames, '
              f'{len(frames) * args.frame_ms / 1000:.3f}s nominal loop.', flush=True)
    if not args.play:
        return 0  # Preview never opens input devices, a terminal, or a Board.
    if args.animation:
        play(clips[args.animation], args.frame_ms, args.repeat)
        return 0
    source = None
    try:
        if args.input == 'terminal':
            source = TerminalKeys()
        elif args.input in ('auto', 'keyboard'):
            source = detect_keyboard(address=args.keyboard_address)
            if source is None and args.input == 'keyboard':
                raise ValueError('No readable Bluetooth Keychron K0 Max Keyboard; no access settings were changed')
        if source is None:
            print('No keyboard selected/available; playing the full gallery for finite rounds.', flush=True)
        else:
            print('Input: ' + getattr(source, 'node', 'SSH/local terminal'), flush=True)
        signal.signal(signal.SIGTERM, interrupted)
        with Board() as board:
            player = Player(board, args.frame_ms)
            try:
                player.prepare(clips)
                if source is None:
                    gallery(player, clips, args.repeat)
                else:
                    try:
                        interactive(player, clips, source)
                    except KeyboardDisconnected:
                        print('Keyboard disconnected; falling back to the finite gallery.', flush=True)
                        gallery(player, clips, args.repeat)
            finally:
                player.clear()
    finally:
        if source is not None:
            source.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nDot Matrix Animations stopped; cleanup requested.')
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError) as error:
        print('Dot Matrix Animations: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
