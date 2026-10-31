"""Finite, local microphone level history. Preview uses labelled synthetic data."""
import argparse
from contextlib import nullcontext
import json
import math
from pathlib import Path
import signal
import time

from torque import Board, Frame
from torque.audio import AudioError, Microphone, audio_capabilities


def level_height(dbfs, floor=-60, ceiling=-12):
    return max(0, min(8, math.ceil((dbfs - floor) / (ceiling - floor) * 8))) if math.isfinite(dbfs) else 0


def level_frame(history):
    values = [0] * 104
    for x, height in enumerate(([0] * 13 + list(history))[-13:]):
        for y in range(8 - height, 8):
            values[y * 13 + x] = 7 if y == 8 - height else 3
    return Frame(tuple(values), bits=3)


def preview(path):
    frame = level_frame([0, 1, 2, 4, 6, 8, 7, 4, 2, 1, 3, 5, 2])
    circles = ''.join(f'<circle cx="{20+x*18}" cy="{58+y*18}" r="5" fill="#2879ed" '
                      f'opacity="{0.08 if value == 0 else value/7:.2f}"/>'
                      for y in range(8) for x in range(13)
                      for value in [frame.pixels[y*13+x]])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="216" viewBox="0 0 256 216">'
                    '<rect width="256" height="216" rx="12" fill="#101722"/>'
                    '<text x="14" y="25" fill="white" font-family="sans-serif" font-size="13">Microphone level history</text>'
                    '<text x="14" y="42" fill="#aab8ce" font-family="sans-serif" font-size="10">Synthetic offline preview · no capture</text>'
                    + circles + '</svg>\n')


def interrupted(*_):
    raise KeyboardInterrupt


def live(args):
    signal.signal(signal.SIGTERM, interrupted)
    chunks, peak, minimum, maximum, active, draws = 0, 0.0, 8, 0, 0, 0
    history, next_draw, next_report = [], 0, 0
    print(f'Opening local microphone for {args.seconds} seconds. No audio files or network uploads.', flush=True)
    with Microphone(card=args.card, seconds=args.seconds + 5) as mic:
        # Acquire the matrix only after capture actually opened successfully.
        with (nullcontext(None) if args.console_only else Board()) as board:
            started = time.monotonic()
            deadline = started + args.seconds
            print('MICROPHONE_READY: speak or clap near the microphone; Ctrl-C stops.', flush=True)
            try:
                while time.monotonic() < deadline:
                    chunk = mic.read(frames=1200, latest=True)
                    if chunk is None:
                        break
                    rms = chunk.rms
                    dbfs = 20 * math.log10(rms) if rms else -math.inf
                    height = level_height(dbfs, args.floor_dbfs)
                    chunks += 1
                    peak = max(peak, chunk.peak)
                    minimum, maximum = min(minimum, height), max(maximum, height)
                    active += height > 0
                    now = time.monotonic()
                    if now >= next_draw:
                        history = [*history, height][-13:]
                        if board is not None:
                            board.matrix.draw(level_frame(history))
                            draws += 1
                        next_draw = now + 1 / args.fps
                    if now >= next_report:
                        print(f'Level {height}/8; {dbfs:.1f} dBFS; peak {chunk.peak:.5f}', flush=True)
                        next_report = now + 0.2
                elapsed = time.monotonic() - started
            finally:
                if board is not None:
                    board.matrix.clear()
    result = {'chunks': chunks, 'peak': round(peak, 7), 'minimum_height': minimum if chunks else 0,
              'maximum_height': maximum, 'active_chunks': active, 'matrix_updates': draws,
              'elapsed_seconds': round(elapsed, 3), 'audio_saved': False,
              'audio_uploaded': False, 'optical_measurement': False}
    print('Capture stopped; routing cleanup completed. ' + json.dumps(result), flush=True)
    if not active:
        print('No signal above the display floor. Check the microphone/plug, mute switch and routing; '
              'device enumeration alone does not prove microphone input.', flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly open the microphone; otherwise generate a synthetic preview')
    parser.add_argument('--list', action='store_true', help='Report endpoints/access without recording')
    parser.add_argument('--card', help='Discovered ALSA card ID; not a changing numeric index')
    parser.add_argument('--seconds', type=int, default=30, help='Capture duration, 1..120 seconds (default 30)')
    parser.add_argument('--fps', type=int, default=15, help='Maximum matrix updates per second, 1..15 (default 15)')
    parser.add_argument('--floor-dbfs', type=float, default=-60, help='Display floor, -90..-20 dBFS; not calibrated loudness')
    parser.add_argument('--console-only', action='store_true', help='Capture levels without connecting to the MCU')
    parser.add_argument('--output-dir', type=Path, default=Path('projects/microphone-level-meter'))
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 120 or not 1 <= args.fps <= 15:
        parser.error('Use --seconds 1..120 and --fps 1..15')
    if not math.isfinite(args.floor_dbfs) or not -90 <= args.floor_dbfs <= -20:
        parser.error('--floor-dbfs must be in -90..-20')
    if args.list:
        print(json.dumps(audio_capabilities(card=args.card), indent=2))
        return 0
    if not args.live:
        path = args.output_dir / 'preview.svg'
        preview(path)
        print('Synthetic preview: ' + str(path) + '; no microphone or MCU opened.')
        return 0
    return live(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nMicrophone meter stopped; context cleanup requested.')
        raise SystemExit(130)
    except (AudioError, OSError, TimeoutError, ValueError) as error:
        print('Microphone Level Meter: ' + str(error))
        raise SystemExit(1)
