"""Measure Episode 1 scenes on an idle UNO Q desktop with a private PipeWire sink."""
from argparse import ArgumentParser
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


SCENES = [
    ("fight", "start", "ordinary-route", 1120, 1640),
    ("water", "e1m4", "grisly-water", 361, 736),
    ("transition", "start", "ordinary-route", 3630, 3900),
]


def stop_if_parent_exits(parent):
    # Linux also releases the sink if the benchmark is interrupted by SSH loss.
    if ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        os._exit(1)
    if os.getppid() != parent:
        os._exit(1)


def benchmark(bindir, media, replays, vsync):
    parent = os.getpid()
    sink = f"mojo_quake_bench_{parent}"
    keeper = subprocess.Popen(
        ["pw-cli"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, text=True, preexec_fn=lambda: stop_if_parent_exits(parent),
    )
    try:
        keeper.stdin.write("create-node adapter { factory.name=support.null-audio-sink "
                           f"node.name={sink} media.class=Audio/Sink audio.position=[ FL FR ] "
                           "node.virtual=true object.linger=false priority.session=0 }\n")
        keeper.stdin.flush()
        for _ in range(50):
            nodes = json.loads(subprocess.check_output(["pw-dump"]))
            if any(node.get("info", {}).get("props", {}).get("node.name") == sink for node in nodes):
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Private audio sink unavailable")
        for binary in ("tyr-quake", "tyr-glquake"):
            for scene, level, trace, warm, last in SCENES:
                if any(subprocess.run(["pgrep", "-x", name], stdout=subprocess.DEVNULL).returncode == 0
                       for name in ("tyr-quake", "tyr-glquake")):
                    raise RuntimeError("A Quake game is open on the desktop")
                with tempfile.TemporaryDirectory(prefix="mojo-quake-perf-") as temp:
                    profile = Path(temp) / "id1"
                    profile.mkdir()
                    (profile / "video.cfg").write_text(f'vid_vsync "{vsync}"\n')
                    result = subprocess.run(
                        [bindir/binary, "-basedir", media, "-fullscreen", "-width", "640",
                         "-height", "480", "-mqcpu2x", "-noudp", "-noconinput", "-nocdaudio",
                         "-mqwarmup", str(warm), "-mqticks", str(last), "-mqreplay",
                         replays/(trace+".trace"), "+map", level],
                        env=dict(os.environ, SDL_AUDIODRIVER="pulseaudio", PULSE_SINK=sink,
                                 MOJO_QUAKE_PROFILE=temp),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=True,
                    )
                lines = result.stdout.decode("utf-8", "replace").splitlines()
                metrics = [s for s in lines if s.startswith("MOJO_QUAKE ")]
                if len(metrics) != 1 or not any("Sound Initialized" in s for s in lines):
                    raise RuntimeError("\n".join(lines[-20:]))
                print(scene, binary, "vsync", vsync, metrics[0], flush=True)
    finally:
        keeper.terminate()
        try:
            keeper.wait(timeout=3)
        except subprocess.TimeoutExpired:
            keeper.kill()
            keeper.wait()
        keeper.stdin.close()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("bin_dir", type=Path)
    parser.add_argument("media", type=Path)
    parser.add_argument("--replays", type=Path, default=Path(__file__).parent/"replays")
    parser.add_argument("--vsync", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    benchmark(args.bin_dir.resolve(), args.media.resolve(), args.replays.resolve(), args.vsync)
