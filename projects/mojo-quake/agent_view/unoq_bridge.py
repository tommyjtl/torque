"""UNO Q end of the SSH game link. Uses only the standard library on the board."""

import base64
import collections
import fcntl
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import zlib

HZ = 72
MAX_TURN_ANGLE = 45
MAX_ROUTE_STEER = 36
TURN_DEGREES_PER_TICK = 4.5
# Duration in simulation ticks, forward, side, relative camera yaw.
MOVES = {
    "turn_left": (12, 0, 0, 32),
    "turn_right": (12, 0, 0, -32),
    "face_left": (8, 0, 0, 20),
    "face_right": (8, 0, 0, -20),
    "fire": (24, 0, 0, 0),
    "check_view": (8, 0, 0, 0),
    "advance": (24, 290, 0, 0),
    "follow_route": (24, 290, 0, 0),
    "touch_switch": (24, 290, 0, 0),
    "wait_door": (50, 0, 0, 0),
    "ride_lift": (48, 0, 0, 0),
    "back_up": (20, -230, 0, 0),
    "strafe_left": (16, 0, -230, 0),
    "strafe_right": (16, 0, 230, 0),
}


def turn_duration(angle):
    return max(2, math.ceil(abs(angle) / TURN_DEGREES_PER_TICK)) if angle else 0


def valid_steer(action, steer):
    if (
        type(steer) not in (float, int)
        or not -MAX_TURN_ANGLE <= steer <= MAX_TURN_ANGLE
    ):
        return False
    if not steer:
        return True
    if action in ("follow_route", "touch_switch"):
        return abs(steer) <= MAX_ROUTE_STEER
    # Signed offsets for look actions must agree with the selected direction.
    return steer * MOVES[action][3] > 0


class Output:
    """A blocked SSH writer can replace its pending picture, never a command receipt."""

    def __init__(self):
        self.cv = threading.Condition()
        self.events = collections.deque()
        self.latest = None
        self.in_flight = None
        self.sequence = 0
        self.drops = 0
        self.lost = threading.Event()
        threading.Thread(target=self.write, daemon=True).start()

    def put(self, kind, **fields):
        with self.cv:
            msg = dict(type=kind, **fields)
            if kind == "frame":
                self.sequence += 1
                msg["sequence"] = self.sequence
                self.drops += self.latest is not None
                msg["dropped"] = self.drops
                self.latest = msg
            else:
                self.events.append(msg)
            self.cv.notify()

    def acknowledge(self, sequence):
        with self.cv:
            if sequence == self.in_flight:
                self.in_flight = None
                self.cv.notify()

    def write(self):
        try:
            while True:
                with self.cv:
                    self.cv.wait_for(
                        lambda: self.events
                        or (self.latest is not None and self.in_flight is None)
                    )
                    if self.events:
                        msg = self.events.popleft()
                    else:
                        msg, self.latest = self.latest, None
                        self.in_flight = msg["sequence"]
                print(json.dumps(msg, separators=(",", ":")), flush=True)
        except (BrokenPipeError, OSError):
            self.lost.set()


class NativeGame:
    def __init__(self, profile, start_map="e1m1"):
        media = Path.home() / ".local/share/mojo-quake/media"
        binary = Path(__file__).resolve().with_name("tyr-quake")
        env = dict(
            os.environ,
            DISPLAY=os.environ.get("DISPLAY") or ":0",
            XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}",
            MOJO_QUAKE_PROFILE=profile,
        )
        self.p = subprocess.Popen(
            [
                str(binary),
                "-basedir",
                str(media),
                "-width",
                "640",
                "-height",
                "480",
                "-mqcpu2x",
                "-fullscreen",
                "-mqfast",
                "-mqagent",
                "-mqreplay",
                "-",
                "-noudp",
                "-nocdaudio",
                "-noconinput",
                "+con_notifytime",
                "0",
                "+scr_conspeed",
                "99999",
                "+scr_sbaralpha",
                "1",
                "+skill",
                "1",
                "+map",
                start_map,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            env=env,
        )
        self.tick = 0
        self.yaw = 90.0
        self.pitch = 0.0
        try:
            self.line(b"MQ_AGENT_READY ")
        except BaseException:
            self.close()
            raise

    def line(self, prefix):
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("Quake closed its frame pipe.")
            if line.startswith(prefix):
                return line.decode("ascii").strip().split()

    def move(self, count, forward=0, side=0, *, attack=False):
        self.p.stdin.write(
            f"{count} {forward} {side} 0 {self.yaw:.4f} {self.pitch:.4f} {int(attack)} 0\n".encode()
        )
        self.p.stdin.flush()
        _, tick, w, h, fmt = self.line(b"MQ_FRAME ")
        if (w, h, fmt) != ("320", "240", "INDEXED") or int(tick) != self.tick + count:
            raise RuntimeError("Unexpected native frame dimensions, format or tick.")
        buf = self.p.stdout.read(768 + 320 * 240)
        if len(buf) != 768 + 320 * 240:
            raise RuntimeError("Incomplete native frame.")
        self.tick = int(tick)
        return buf

    def stats(self):
        self.p.stdin.write(b"state\n")
        self.p.stdin.flush()
        info = dict(kv.split("=", 1) for kv in self.line(b"MQ_STATE ")[1:])
        return {
            k: info[k]
            for k in (
                "hash",
                "map",
                "yaw",
                "pos",
                "hp",
                "kills",
                "intermission",
                "ammo",
                "weapon",
            )
        }

    def close(self):
        self.p.stdin.close()
        try:
            self.p.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.p.terminate()
            try:
                self.p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        self.p.stdout.close()


def encounter_frame(game):
    for line in (
        Path(__file__).with_name("slipgate-encounter.trace").read_text().splitlines()
    ):
        if not line.strip() or line.startswith("#"):
            continue
        n, f, side, _, yaw, pitch, _, _ = line.split()
        game.yaw, game.pitch = float(yaw), float(pitch)
        # Stage the familiar camera using movement only. Gemma supplies the first attack.
        image = game.move(min(int(n), 703 - game.tick), int(f), int(side))
        if game.tick == 703:
            state = game.stats()
            if (
                state["map"] != "e1m1"
                or float(state["hp"]) <= 0
                or state["kills"].split("/")[0] != "0"
            ):
                raise RuntimeError("Quake did not reach the first encounter.")
            return image
    raise RuntimeError("Incomplete Quake encounter recording.")


def serve(game, encounter=False):
    out = Output()
    incoming = queue.Queue()

    def read():
        try:
            with os.fdopen(os.dup(sys.stdin.fileno()), "rb") as commands:
                for line in commands:
                    message = json.loads(line)
                    incoming.put(message)
                    if message.get("op") == "close":
                        return
        finally:
            incoming.put({"op": "close"})

    threading.Thread(target=read, daemon=True).start()
    mode, active, last_id, token = "paused", None, 0, 0
    stamps = {}
    perf = collections.deque()
    stats = game.stats() if game.tick else {}

    def frame(pixels, stamp):
        stamps[game.tick] = stamp
        while len(stamps) > 64:
            del stamps[next(iter(stamps))]
        duration = perf[-1][0] - perf[0][0] if len(perf) > 1 else 0
        out.put(
            "frame",
            tick=game.tick,
            captured=stamp,
            yaw=game.yaw,
            pitch=game.pitch,
            mode=mode,
            stats=stats,
            hz=round((perf[-1][1] - perf[0][1]) / duration, 1) if duration else None,
            display_fps=round((len(perf) - 1) / duration, 1) if duration else None,
            pixels=base64.b64encode(zlib.compress(pixels, 1)).decode("ascii"),
        )

    pixels = encounter_frame(game) if encounter else game.move(24)
    stats = game.stats()
    out.put(
        "ready",
        board=os.uname().nodename,
        pid=game.p.pid,
        renderer="Mojo software",
        screen="640 × 480",
        start="encounter" if encounter else "entrance",
    )
    frame(pixels, time.monotonic())
    deadline = last_contact = mode_since = time.monotonic()
    last_preview = game.tick
    while not out.lost.is_set():
        timeout = 0.25 if mode == "paused" else max(0, deadline - time.monotonic())
        try:
            msg = incoming.get(timeout=timeout)
        except queue.Empty:
            msg = None
        if msg is not None:
            op = msg.get("op")
            now = time.monotonic()
            last_contact = now
            if op == "close":
                return
            if op == "ack":
                out.acknowledge(msg.get("sequence"))
            elif op == "ping":
                out.put("pong", sent=msg["sent"], board_time=now)
            elif op in ("play", "step", "pause"):
                token = msg["token"]
                if active:
                    out.put(
                        "end",
                        id=active["id"],
                        tick=game.tick,
                        status="interrupted",
                        stats=game.stats(),
                    )
                active = None
                mode = "paused" if op == "pause" else op
                mode_since = deadline = now
                perf.clear()
                out.put("mode", mode=mode, tick=game.tick, token=token)
                if mode == "paused":
                    frame(pixels, now)
            elif op == "input":
                i = msg.get("id")
                source = msg.get("source")
                action = msg.get("action")
                steer = msg.get("steer", 0)
                age = (
                    now - stamps.get(source, -1e10) if type(source) is int else math.inf
                )
                reason = None
                if type(i) is not int or i <= last_id or action not in MOVES:
                    reason = "invalid input"
                elif not valid_steer(action, steer):
                    reason = "invalid route direction"
                elif mode == "paused" or active:
                    reason = "board not accepting input"
                elif age > 1.5 or not 0 <= game.tick - source <= 96:
                    reason = "stale observation"
                elif action == "fire":
                    if age > 0.85 or game.tick - source > 60:
                        reason = "stale opponent sighting"
                    else:
                        stats = game.stats()
                        if float(stats["hp"]) <= 0 or int(stats["intermission"]):
                            reason = "round ended"
                if type(i) is int:
                    last_id = max(last_id, i)
                if reason:
                    out.put("reject", id=i, tick=game.tick, reason=reason)
                else:
                    duration, forward, side, turn = MOVES[action]
                    turning_in_place = bool(turn)
                    turn = steer or turn
                    turning_ticks = turn_duration(turn)
                    align_ticks = turning_ticks if action == "touch_switch" else 0
                    if turning_in_place:
                        duration = turning_ticks
                    duration += align_ticks
                    active = dict(
                        id=i,
                        source=source,
                        action=action,
                        left=duration,
                        duration=duration,
                        forward=forward,
                        side=side,
                        turn=turn,
                        turn_ticks=turning_ticks,
                        align_ticks=align_ticks,
                        start_yaw=game.yaw,
                        started=False,
                    )
            # Pings and commands must not postpone a due simulation tick.
        now = time.monotonic()
        if mode == "paused" or now < deadline:
            continue
        if now - last_contact > 4 or (
            mode == "step" and not active and now - mode_since > 10
        ):
            if active:
                out.put(
                    "end",
                    id=active["id"],
                    tick=game.tick,
                    status="interrupted",
                    stats=game.stats(),
                )
            active = None
            mode = "paused"
            out.put(
                "mode", mode=mode, tick=game.tick, token=token, reason="Control timeout"
            )
            frame(pixels, now)
            continue
        # Nominal 60 physical presents for 72 simulation ticks. Catch up locally in
        # bounded batches if a presentation missed its deadline.
        count = max(1, min(6, 1 + int((now - deadline) * HZ)))
        if game.tick % 6 == 4:
            count = max(2, count)
        first = game.tick + 1
        if active:
            count = min(count, active["left"])
            elapsed = active["duration"] - active["left"]
            aligning = elapsed < active["align_ticks"]
            if aligning:
                count = min(count, active["align_ticks"] - elapsed)
            if active["turn"]:
                fraction = min(1, (elapsed + count) / active["turn_ticks"])
                game.yaw = (active["start_yaw"] + fraction * active["turn"]) % 360
            pixels = game.move(
                count,
                0 if aligning else active["forward"],
                active["side"],
                attack=active["action"] == "fire",
            )
        else:
            pixels = game.move(count)
        stamp = time.monotonic()
        perf.append((stamp, game.tick))
        while len(perf) > 2 and perf[0][0] < stamp - 2:
            perf.popleft()
        deadline += count / HZ
        if stamp - deadline > 0.5:
            deadline = stamp
        finished = False
        if active:
            if not active["started"]:
                out.put(
                    "applied",
                    id=active["id"],
                    source=active["source"],
                    action=active["action"],
                    tick=first,
                    age_ms=round(1000 * (stamp - stamps[active["source"]]), 1),
                    duration_ticks=active["duration"],
                    turn_degrees=active["turn"],
                    turn_ticks=active["turn_ticks"],
                )
                active["started"] = True
            active["left"] -= count
            if active["left"] == 0:
                stats = game.stats()
                out.put(
                    "end",
                    id=active["id"],
                    status="applied",
                    tick=game.tick,
                    stats=stats,
                )
                active = None
                finished = True
                if mode == "step":
                    mode = "paused"
                    out.put("mode", mode=mode, tick=game.tick, token=token)
        if game.tick - last_preview >= 4 or finished:
            frame(pixels, stamp)
            last_preview = game.tick


def main():
    encounter = sys.argv[1:] == ["--encounter"]
    if sys.argv[1:] and not encounter:
        raise SystemExit("Expected --encounter or no arguments.")
    directory = Path.home() / ".cache/mojo-quake-board"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "agent.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A board game bridge is already running.")
        for proc in Path("/proc").glob("[0-9]*/comm"):
            try:
                if proc.stat().st_uid == os.getuid() and proc.read_text().strip() in (
                    "tyr-quake",
                    "tyr-glquake",
                ):
                    raise SystemExit("Quake is already open on the board desktop.")
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
        with tempfile.TemporaryDirectory(prefix="session-", dir=directory) as profile:
            game = NativeGame(profile, "start" if encounter else "e1m1")
            try:
                serve(game, encounter)
            finally:
                game.close()


if __name__ == "__main__":
    main()
