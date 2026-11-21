"""Replay an observatory entrance run in a clean native game. No archived native saves are imported."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

P = Path(__file__).resolve().parent
sys.path.insert(0, str(P / "agent_view"))
from game import Game
from checkpoints import checkpoint_operation


def verify(directory, binary, media):
    events = [
        json.loads(row)
        for row in (directory / "decisions.jsonl").read_text().splitlines()
    ]
    meta = json.loads((directory / "recording.json").read_text())
    if not events or events[0]["observed_tick"] != 24 or meta["scenario"] != "entrance":
        raise ValueError("The recording must begin at the normal entrance.")
    if [e["seq"] for e in events] != list(range(1, len(events) + 1)):
        raise ValueError("Incomplete decision ledger.")
    if any(e.get("timing") != "real-time" for e in events):
        raise ValueError("The recording includes a non-real-time decision.")
    if any(a["end_tick"] != b["observed_tick"] for a, b in zip(events, events[1:])):
        raise ValueError("Gap or overlap between decision intervals.")
    manifest = directory / "attempt.json"
    configuration = json.loads(manifest.read_text()) if manifest.exists() else {}
    if configuration.get("resume_session"):
        raise ValueError("This run resumed a prior session.")
    starts = {e["observed_tick"]: e for e in events}
    ends = {e["end_tick"]: e for e in events}
    digest = hashlib.sha256((directory / "inputs.trace").read_bytes()).hexdigest()
    g = Game(binary, media, start_map="e1m1")
    sources = set()
    saved = set()
    loads = boundary = 0
    exit_tick = None
    last = None
    try:
        lines = (directory / "inputs.trace").read_text().splitlines()
        if list(map(float, lines[0].split())) != [24, 0, 0, 0, 90, 0, 0, 0]:
            raise ValueError("Unexpected entrance setup.")
        for line in lines:
            e = starts.get(g.tick)
            op = e.get("checkpoint") if e else None
            if e:
                if e["observed_stats"]["hash"] != g.pipe.state()["hash"]:
                    raise ValueError(f"Observation mismatch at {g.tick}")
                sources.add(e.get("input_source") or e.get("controller"))
            if op:
                slot = op["slot"]
                if op["op"] == "save":
                    if slot in saved:
                        raise ValueError("Duplicate slot")
                    saved.add(slot)
                elif op["op"] == "load":
                    if slot not in saved:
                        raise ValueError("Slot not created during replay")
                    loads += 1
                else:
                    raise ValueError("Unexpected checkpoint operation")
                checkpoint_operation(g, op)
            n, forward, side, up, yaw, pitch, buttons, impulse = line.split()
            g.yaw, g.pitch = float(yaw), float(pitch)
            stop = g.tick + int(n)
            img, state, _ = g.move(
                int(n),
                int(forward),
                int(side),
                int(buttons),
                up=int(up),
                impulse=int(impulse),
                evaluate=stop in ends or stop in starts,
            )
            if not state:
                continue
            last = state
            if stop in ends:
                ref = ends[stop]["evaluator"]
                if (
                    ref["hash"] != state["hash"]
                    or ref["map"] != state["map"]
                    or int(ref["intermission"]) != int(state["intermission"])
                ):
                    raise ValueError(f"End mismatch at {stop}")
                boundary += 1
            if (
                state["map"] == "e1m2"
                or state["map"] == "e1m1"
                and int(state["intermission"]) == 1
            ):
                exit_tick = stop if exit_tick is None else exit_tick
        if boundary != len(events) or g.tick != events[-1]["end_tick"] or last is None:
            raise ValueError("The input trace does not terminate at the final decision.")
        final = last["map"] == "e1m2" or (
            last["map"] == "e1m1" and int(last["intermission"]) == 1
        )
        return dict(
            result="verified exit" if final and exit_tick is not None else "no exit",
            session=directory.name,
            prepared_route=bool(configuration.get("prepared_e1m1_route") or any(e.get("route_guide") for e in events)),
            exit_tick=exit_tick,
            checks=boundary,
            trace_sha256=digest,
            saves=len(saved),
            reloads=loads,
            input_sources=sorted(sources),
            ticks=g.tick,
            reported_result=meta["result"],
        )
    finally:
        g.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--binary", type=Path, default=P / "build/host/tyr-quake")
    parser.add_argument(
        "--media",
        type=Path,
        default=Path.home() / "Library/Application Support/Mojo Quake/media",
    )
    args = parser.parse_args()
    result = verify(args.session, args.binary, args.media)
    (args.session / "independent-replay.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))
    sys.exit(0 if result["result"] == "verified exit" else 1)
