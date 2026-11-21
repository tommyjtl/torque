"""Replay an entire shareware campaign on both native renderers."""
from argparse import ArgumentParser
import gzip
from hashlib import sha256
import math
import os
from pathlib import Path
import subprocess
import tempfile

from prepare_shareware import PAK_SHA


def read_recording(path):
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    ticks = 0
    for index, row in enumerate(data.splitlines(), 1):
        if not row.strip() or row.startswith(b"#"):
            continue
        fields = row.split()
        if len(fields) != 8 or not fields[0].isdigit() or not 1 <= int(fields[0]) <= 100000:
            raise ValueError(f"Expected ordinary movement inputs on line {index} of {path.name}")
        movement = tuple(map(int, fields[1:4]))
        yaw, pitch = map(float, fields[4:6])
        buttons, impulse = map(int, fields[6:8])
        if (any(abs(value) > 400 for value in movement) or not math.isfinite(yaw) or
                abs(yaw) > 360 or not -70 <= pitch <= 80 or not 0 <= buttons <= 3 or
                impulse not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12)):
            raise ValueError(f"Invalid player input on line {index} of {path.name}")
        ticks += int(fields[0])
    if not ticks:
        raise ValueError(f"Empty recording in {path}")
    return data, ticks


def checkpoints(log):
    selected = []
    for line in log.splitlines():
        if line.startswith(("MQ_ENTER ", "MQ_EXIT ", "MQ_FINALE ", "MQ_END ")):
            kind, *fields = line.split()
            selected.append((kind[3:], dict(field.split("=", 1) for field in fields)))
    return selected


def confirm_episode(events, route, ticks):
    maps = ["e1m1", "e1m2", "e1m3", "e1m4"]
    if route == "secret":
        maps.append("e1m8")
    maps += ["e1m5", "e1m6", "e1m7"]
    expected = [("ENTER", "start")]
    for name in maps:
        expected += [("ENTER", name), ("EXIT", name)]
    expected += [("ENTER", "start"), ("END", "start")]
    actual = [(kind, state["map"]) for kind, state in events if kind != "FINALE"]
    if actual != expected:
        raise ValueError(f"{route} route map order was {actual}")
    if not any(kind == "FINALE" and state["map"] == "e1m7" for kind, state in events):
        raise ValueError("Missing House of Chthon finale")
    for kind, state in events:
        gravity = 100 if state["map"] == "e1m8" else 800
        if int(state["skill"]) != 1 or float(state["gravity"]) != gravity:
            raise ValueError(f"Unexpected skill or gravity at {kind} {state['map']}")
        if kind == "EXIT" and state["map"] == "e1m7":
            if not int(state["runes"]) & 1:
                raise ValueError("Missing first rune on episode exit")
    arrived, end = (state for _, state in events[-2:])
    if (int(end["command"]) != ticks or not (int(arrived["runes"]) & int(end["runes"]) & 1)
            or int(end["intermission"]) or int(end["hp"]) <= 0 or arrived["pos"] == end["pos"]):
        raise ValueError("The recording did not finish at the hub with its first rune")


def confirm_lightning(log):
    health = []
    plates = set()
    events = []
    for line in log.splitlines():
        if line.startswith(("MQ_BOSS ", "MQ_PLATE ")):
            kind, *fields = line.split()
            state = dict(pair.split("=", 1) for pair in fields)
            if kind == "MQ_BOSS":
                remaining = int(state["health"])
                if health and remaining < health[-1]:
                    if plates != {"north", "south", "lightning"}:
                        raise ValueError(f"Missing electrode or lightning input before hit at {state['command']}")
                    plates.clear()
                health.append(remaining)
            else:
                plates.add(state["action"])
            events.append((kind, state))
    # The dormant entity can appear with zero health before the rune wakes it.
    if 3 not in health or health[health.index(3):] != [3, 2, 1, 0]:
        raise ValueError(f"Unexpected Normal Chthon health sequence: {health}")
    return events


def run(binary, media, data, ticks, profile):
    profile.mkdir()
    command = [
        binary, "-basedir", media, "-window", "-mqhidden", "-width", "640", "-height", "480",
        "-noconinput", "-noudp", "-nocdaudio", "-mqfast", "-mqinventory", "-mqticks",
        str(ticks + 3000), "-mqreplay", "-", "+map", "start",
    ]
    env = dict(os.environ, MOJO_QUAKE_PROFILE=str(profile), SDL_AUDIODRIVER="dummy")
    if binary.name == "tyr-quake":
        command.insert(1, "-mqcpu2x")
        env["SDL_VIDEODRIVER"] = "dummy"
    result = subprocess.run(command, env=env, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=300)
    log = result.stdout.decode("utf-8", "replace")
    if result.returncode:
        raise RuntimeError(f"{binary.name} stopped with status {result.returncode}\n{log[-1200:]}")
    if binary.name == "tyr-glquake" and "GL_RENDERER: FD702" not in log:
        raise RuntimeError("Expected the UNO Q Adreno driver in the GPU run")
    return log


def verify(bindir, media, recordings, routes, logs=None):
    if sha256((media / "id1/pak0.pak").read_bytes()).hexdigest() != PAK_SHA:
        raise ValueError("The verification requires the Quake 1.06 shareware PAK")
    if logs:
        logs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mojo-quake-campaign-") as dirname:
        for route in routes:
            path = recordings / f"{route}-route.trace"
            if not path.exists():
                path = path.with_suffix(".trace.gz")
            data, ticks = read_recording(path)
            reference = None
            for renderer in ("tyr-quake", "tyr-glquake"):
                log = run(bindir / renderer, media, data, ticks, Path(dirname) / f"{route}-{renderer}")
                if logs:
                    (logs / f"{route}-{renderer}.log").write_text(log)
                events = checkpoints(log)
                confirm_episode(events, route, ticks)
                observations = (events, confirm_lightning(log))
                if reference is not None and observations != reference:
                    raise ValueError(f"Renderer checkpoints differ on the {route} route")
                reference = observations
                print(route, renderer, "ticks", ticks, "final hash", events[-1][1]["hash"])
            print("Matched", len(reference[0]), "campaign checkpoints and all boss events")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("bin_dir", type=Path)
    parser.add_argument("media", type=Path)
    parser.add_argument("--recordings", type=Path, default=Path(__file__).parent / "replays")
    parser.add_argument("--route", choices=("ordinary", "secret"))
    parser.add_argument("--logs", type=Path)
    args = parser.parse_args()
    verify(args.bin_dir.resolve(), args.media.resolve(), args.recordings,
           [args.route] if args.route else ["ordinary", "secret"], args.logs)
