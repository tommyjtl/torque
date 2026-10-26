"""Read-only identity/status by default; control requires an explicit subcommand."""
import argparse
import json
import math
import queue
import sys
import time
from . import Board, ControllerError, Frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=3)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('info')
    sub.add_parser('status')
    sub.add_parser('snapshot')
    sub.add_parser('health')
    watch = sub.add_parser('watch')
    watch.add_argument('--duration', type=float, help='Observe for this many seconds; default: until Ctrl-C')
    watch.add_argument('--jsonl', action='store_true', help='Emit one normalized JSON event per line')
    watch.add_argument('--reconnect-attempts', type=int, default=3, help='Bounded retries after connection/MCU loss (0..100)')
    sub.add_parser('clear')
    sub.add_parser('stop')
    rgb = sub.add_parser('rgb')
    rgb.add_argument('led', type=int, choices=[3, 4])
    rgb.add_argument('channels', nargs=3, type=int, choices=[0, 1], metavar='0|1')
    draw = sub.add_parser('draw')
    draw.add_argument('file', help='JSON array of 104 pixels or 8 strings of 13 pixels')
    args = parser.parse_args(argv)
    if args.command == 'watch' and args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error('--duration must be a positive number of seconds')
    try:
        frame = None
        if args.command == 'draw':
            with open(args.file) as stream:
                value = json.load(stream)
            frame = Frame.from_rows(value) if isinstance(value, list) and value and isinstance(value[0], str) else Frame(value)
        with Board(timeout=args.timeout) as board:
            if args.command == 'info':
                print(json.dumps(board.info(), indent=2))
            elif args.command == 'status':
                print(json.dumps(board.matrix.status(), indent=2))
            elif args.command in ('snapshot', 'health'):
                print(json.dumps(getattr(board, args.command)(), indent=2))
            elif args.command == 'watch':
                with board.watch(reconnect_attempts=args.reconnect_attempts) as observer:
                    deadline = time.monotonic() + args.duration if args.duration else None
                    while deadline is None or time.monotonic() < deadline:
                        wait = 0.2 if deadline is None else min(0.2, max(0.001, deadline - time.monotonic()))
                        try:
                            event = observer.get(timeout=wait)
                        except queue.Empty:
                            continue
                        except StopIteration:
                            break
                        if args.jsonl:
                            print(json.dumps(event, separators=(',', ':')), flush=True)
                        else:
                            print(json.dumps(event, indent=2), flush=True)
            elif args.command == 'rgb':
                board.rgb(args.led).set(*(bool(c) for c in args.channels))
            elif args.command == 'draw':
                board.matrix.draw(frame)
            else:
                getattr(board.matrix, args.command)()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ControllerError, OSError, ValueError, TypeError) as error:
        print('UNO Q: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
