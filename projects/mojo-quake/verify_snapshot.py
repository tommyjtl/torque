"""Check cross-renderer gameplay snapshots with the ordinary E1M1 input recording."""
from argparse import ArgumentParser
from pathlib import Path
import os
import re
import struct
import subprocess
import tempfile


SAVE_TICK = 2153
CHECK_TICKS = (SAVE_TICK, SAVE_TICK + 1, SAVE_TICK + 10, SAVE_TICK + 40, SAVE_TICK + 130)


def replay_segment(recording, start=0):
    rows = []
    tick = 0
    for line in recording.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        count, controls = line.split(" ", 1)
        stop = tick + int(count)
        for boundary in (*[point for point in CHECK_TICKS if tick <= point < stop], stop):
            if boundary > max(start, tick):
                rows.append(f"{boundary - max(start, tick)} {controls}")
            tick = boundary
            if tick >= start and tick in CHECK_TICKS and (not rows or rows[-1] != "state"):
                rows.append("state")
    return "\n".join(rows) + "\n"


def run(binary, media, profile, replay, *options):
    cpu = binary.name == "tyr-quake"
    env = dict(os.environ, MOJO_QUAKE_PROFILE=str(profile), SDL_AUDIODRIVER="dummy")
    if cpu:
        env["SDL_VIDEODRIVER"] = "dummy"
    command = [binary, "-basedir", media, "-window", "-width", "640", "-height", "480",
               "-noudp", "-noconinput", "-nocdaudio", "-mqfast", "-mqhidden", "-mqexact",
               "-mqticks", "5000", "-mqreplay", replay]
    if cpu:
        command.append("-mqcpu2x")
    result = subprocess.run([*command, *options], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=60, check=True)
    log = result.stdout.decode("utf-8", "replace")
    if "MQ_END map=" not in log:
        raise RuntimeError(log[-3500:])
    return log


def checkpoints(log):
    return [(kind, int(tick), digest) for kind, tick, digest in
            re.findall(r"MQ_EXACT checkpoint=(STATE|END) command=(\d+) digest=([0-9a-f]+)", log)]


def corrupt(slot, data_mismatch):
    data = bytearray(slot.read_bytes())
    start = data.index(b"MQS1")
    if data_mismatch:
        # Keep a valid envelope around a different map revision identifier.
        data[start + 16 + 64] ^= 1
        value = 2166136261
        for byte in data[start+12:]:
            value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
        struct.pack_into("<I", data, start+8, value)
    else:
        del data[-19:]
    slot.write_bytes(data)


def verify(bindir, media, source, cpu_only):
    engines = [bindir / "tyr-quake"]
    if not cpu_only:
        engines.append(bindir / "tyr-glquake")
    with tempfile.TemporaryDirectory(prefix="mojo-quake-check-") as temp:
        root = Path(temp)
        (root / "id1").mkdir()
        full, suffix = root / "full.trace", root / "suffix.trace"
        full.write_text(replay_segment(source))
        suffix.write_text(replay_segment(source, SAVE_TICK))
        for writer, reader in zip(engines, reversed(engines)):
            original = run(writer, media, root, full, "-mqsaveat", str(SAVE_TICK), "+map", "start")
            match = re.search(rf"MQ_MOTION .*command={SAVE_TICK} moving_lifts=(\d+) projectiles=(\d+)", original)
            assert match and all(int(v) > 0 for v in match.groups()), original
            resumption = run(reader, media, root, suffix, "+load", "replay")
            expected = checkpoints(original)
            actual = [(kind, tick+SAVE_TICK, digest) for kind, tick, digest in checkpoints(resumption)]
            assert len(expected) == len(CHECK_TICKS)+1 and actual == expected, (expected, actual)
            print(f"{writer.name} -> {reader.name}: lift={match[1]}, projectiles={match[2]}, "
                  f"restored={actual[0][-1]}, final={actual[-1][-1]}, checkpoints={len(actual)}")
        slot = root / "id1/replay.sav"
        original_bytes = slot.read_bytes()
        for mismatch in (False, True):
            slot.write_bytes(original_bytes)
            corrupt(slot, mismatch)
            rejected = run(engines[0], media, root, full, "-mqloadat", str(SAVE_TICK), "+map", "start")
            assert "Snapshot rejected" in rejected and checkpoints(rejected) == expected
            print("Live game preserved after", "mismatched map identity" if mismatch else "truncated save")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("bin_dir", type=Path)
    parser.add_argument("media", type=Path)
    parser.add_argument("--recording", type=Path, default=Path(__file__).parent / "replays/moving-lift.trace")
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()
    verify(args.bin_dir.resolve(), args.media.resolve(), args.recording, args.cpu_only)
