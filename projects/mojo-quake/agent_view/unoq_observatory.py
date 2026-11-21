# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28,<1", "numpy>=1.26,<3", "opencv-python-headless>=4.10,<5", "Pillow>=11,<13"]
# ///
"""Host the UNO Q live pilot on the Mac. The SSH peer owns Quake's clock."""

import argparse
import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import zlib

import httpx
from PIL import Image

from encounter_memory import EncounterMemory, screen_yaw
from landmarks import validated_marker
from models import CLOUD_MODELS, Models, read_key
from hud import HealthHUD
from navigation import RouteMemory
from planning import read_plan
from route_guide import RouteAtlas, RouteGuide, STAGES
from unoq_bridge import HZ, MAX_ROUTE_STEER, MAX_TURN_ANGLE, MOVES

HERE = Path(__file__).resolve().parent
BOARD_CACHE = ".cache/mojo-quake-board"
OPPONENT_LABELS = ("live_ahead", "live_left", "live_right", "fallen", "none", "unclear")


def board_bundle():
    files = [
        HERE / "unoq_bridge.py",
        HERE.parent / "build/unoq/tyr-quake",
        HERE.parent / "replays/slipgate-encounter.trace",
    ]
    digests = [hashlib.sha256(path.read_bytes()).hexdigest() for path in files]
    tag = hashlib.sha256(" ".join(digests).encode()).hexdigest()[:16]
    return files, digests, f"{BOARD_CACHE}/{tag}"


def stage_bundle(board):
    files, digests, destination = board_bundle()
    ssh = ["ssh", "-4", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", board]
    check = (
        "printf '%s\\n' "
        + " ".join(f"'{digest}  {path.name}'" for path, digest in zip(files, digests))
        + " | sha256sum -c --status"
    )
    if (
        subprocess.run([*ssh, f"cd {destination} 2>/dev/null && {check}"]).returncode
        == 0
    ):
        return
    stage = subprocess.check_output(
        [*ssh, f"mkdir -p {BOARD_CACHE} && mktemp -d {BOARD_CACHE}/stage.XXXXXXXX"],
        text=True,
    ).strip()
    if not re.fullmatch(re.escape(BOARD_CACHE) + r"/stage\.[A-Za-z0-9]{8}", stage):
        raise RuntimeError("Unexpected staging directory on the board")
    subprocess.run(
        [
            "scp",
            "-4",
            "-q",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            *map(str, files),
            f"{board}:{stage}/",
        ],
        check=True,
    )
    subprocess.run(
        [
            *ssh,
            f"(cd {stage} && {check}) && mv -Tn {stage} {destination} && (cd {destination} && {check})",
        ],
        check=True,
    )


def jpeg_from_board(encoded):
    raw = zlib.decompress(base64.b64decode(encoded, validate=True))
    if len(raw) != 768 + 320 * 240:
        raise ValueError("Incomplete UNO Q camera image")
    picture = Image.frombytes("P", (320, 240), raw[768:])
    picture.putpalette(raw[:768])
    buf = io.BytesIO()
    picture.convert("RGB").save(buf, "JPEG", quality=82)
    return buf.getvalue()


def route_input(hint, memory):
    action = hint.get("lift_exit_input") or (
        hint.get("suggested") if hint.get("matched") else hint.get("search_turn")
    )
    if action in MOVES and action not in memory.get("blocked_inputs", []):
        return action
    return None


def move_choices(hint, memory):
    basic = [
        k
        for k in MOVES
        if k not in ("follow_route", "touch_switch", "ride_lift", "wait_door", "check_view")
    ]
    blocked = set(memory.get("blocked_inputs", []))
    suggested = route_input(hint, memory)
    if suggested:
        basic = [suggested, "back_up"]
    if hint.get("lift_exit_input"):
        # Reversing here can reboard the lift before the next camera match.
        basic = [action for action in basic if action != "back_up"]
    basic += ["face_left", "face_right", "fire"]
    return [k for k in dict.fromkeys(basic) if k not in blocked]


def limit_blind_turns(choice, source_tick, history, navigation):
    action = choice["action"]
    turn = MOVES[action][3]
    if (
        not turn
        or choice["opponent"].startswith("live_")
        or choice.get("encounter_reason")
    ):
        return choice

    turns = []
    for receipt in reversed(history):
        if source_tick - receipt["end_tick"] > 3 * HZ:
            break
        if receipt["status"] != "applied" or receipt.get("action") == "check_view":
            continue
        previous = MOVES.get(receipt.get("action"))
        if (
            not previous
            or not previous[3]
            or receipt.get("opponent", "").startswith("live_")
        ):
            break
        turns.append(receipt)
    reversing = turns and turn * MOVES[turns[0]["action"]][3] < 0
    quick_reversal = reversing and source_tick - turns[0]["end_tick"] < HZ
    if len(turns) < 3 and not quick_reversal:
        return choice

    lift_exit_input = navigation.get("prepared_route", {}).get("lift_exit_input")
    if lift_exit_input == action:
        return choice
    blocked = navigation["exploration"].get("blocked_inputs", [])
    action = "check_view" if lift_exit_input or "back_up" in blocked else "back_up"
    return dict(
        choice,
        action=action,
        camera_reason="Breaking up repeated camera turns without a visible opponent.",
    )


def camera_steer(choice, navigation):
    action = choice["action"]
    route = navigation["prepared_route"]
    if action == "follow_route":
        yaw = screen_yaw(route["route"][0])
        return max(-MAX_ROUTE_STEER, min(MAX_ROUTE_STEER, yaw))
    if action == "touch_switch":
        return screen_yaw(choice["switch_point"][0])
    default = MOVES[action][3]
    if not default:
        return 0

    x = choice.get("opponent_x")
    if x is not None:
        yaw = screen_yaw(x)
    elif choice.get("encounter_reason") and action in ("face_left", "face_right"):
        yaw = (
            navigation.get("encounter", {})
            .get("last_sighting", {})
            .get("relative_yaw", 0)
        )
    elif route.get("lift_exit_input") == action:
        yaw = route["lift_exit_yaw"]
    elif route.get("search_turn") == action:
        yaw = route.get("search_yaw", 0)
    else:
        return 0
    if yaw * default <= 0:
        return 0
    return math.copysign(min(MAX_TURN_ANGLE, max(2, abs(yaw))), yaw)


class BoardGuide(RouteGuide):
    def __init__(self, atlas):
        super().__init__(atlas)
        self.last_match_tick = None
        self.lift_exit = None

    def board_view(self, jpg, yaw, tick, pitch=0):
        hint = dict(self.observe(jpg, yaw, pitch), source_tick=tick)
        if hint["matched"]:
            self.last_match_tick = tick
            self.lift_exit = None
            # Retain the travel heading for the first steps off the lift.
            # These are reference replay ticks, independent of the live clock.
            reference = hint["reference_tick"]
            if STAGES[1][0] < reference <= 988:
                anchor = self.atlas.samples[self.index].position
                target = next(
                    s.position for s in self.atlas.samples if s.tick >= reference + 25
                )
                dx, dy = (target - anchor)[:2]
                self.lift_exit = (math.degrees(math.atan2(dy, dx)), tick)
        elif self.last_match_tick is not None and tick - self.last_match_tick <= 4 * 72:
            # A short camera scan can recover a corner even when the preview
            # jumped over the viewpoint where the demonstration turned.
            stage = hint["stage"] - 1
            boundary = STAGES[stage][0]
            target_tick = min(hint["reference_tick"] + 90, boundary)
            if boundary - hint["reference_tick"] < 60 and stage + 1 < len(STAGES):
                target_tick = STAGES[stage + 1][1]
            anchor = self.atlas.samples[self.index].position
            target = min(
                self.atlas.samples, key=lambda p: abs(p.tick - target_tick)
            ).position
            dx, dy = (target - anchor)[:2]
            turn = (math.degrees(math.atan2(dy, dx)) - yaw + 180) % 360 - 180
            if math.hypot(dx, dy) > 48 and abs(turn) > 22:
                hint["search_turn"] = "turn_left" if turn > 0 else "turn_right"
                hint["search_yaw"] = round(turn, 1)
        if hint["stage"] == 2 and hint.get("name") == "Descending lift":
            hint["control"] = "Walk into the red diamond wall button to lower the lift."
        if self.lift_exit and tick - self.lift_exit[1] <= 6 * HZ:
            bearing, _ = self.lift_exit
            turn = (bearing - yaw + 180) % 360 - 180
            if abs(turn) > 36:
                hint["lift_exit_input"] = "turn_left" if turn > 0 else "turn_right"
                hint["lift_exit_yaw"] = round(turn, 1)
            else:
                hint["lift_exit_input"] = "follow_route"
                hint["route"] = [round(50 - 50 * math.tan(math.radians(turn)), 1), 55]
        return hint


def choose(model, jpeg, plan, recent, initial_turn, navigation=None):
    navigation = navigation or {}
    hint, memory = navigation.get("prepared_route", {}), navigation.get(
        "exploration", {}
    )
    choices = (
        ["turn_left", "turn_right"] if initial_turn else move_choices(hint, memory)
    )
    lift = not initial_turn and bool(hint.get("control"))
    lift_exit = bool(hint.get("lift_exit_input"))
    blocked = set(memory.get("blocked_inputs", []))
    blocked_switch = lift and "advance" in blocked
    reposition = []
    if blocked_switch:
        reposition = [
            action
            for action in ("strafe_left", "strafe_right", "back_up")
            if action not in blocked and (action != "back_up" or not lift_exit)
        ]
        choices.extend(reposition)
    if (navigation.get("encounter") or lift or lift_exit) and not initial_turn:
        choices.append("check_view")
    if lift and not blocked_switch:
        choices.append("touch_switch")
    if lift and navigation.get("recent_switch_attempt"):
        choices.append("ride_lift")
    if lift and plan and (
        plan.get("next_input") == "shoot_switch"
        or (plan.get("marker") or {}).get("kind") == "shoot_button"
        or (blocked_switch and plan.get("next_input") == "touch_switch")
    ):
        plan = None
    if navigation.get("visible_ammo") == 0 and "fire" in choices:
        choices.remove("fire")
    choices = list(dict.fromkeys(choices))
    objective = (
        "Inspect either side of the E1M1 entrance with one camera turn."
        if initial_turn
        else hint.get("objective", "Explore The Slipgate Complex and find its exit.")
    )
    lift_instructions = ""
    if lift:
        if blocked_switch:
            objective = "Find a clear approach to the red diamond lift button."
            navigation = dict(
                navigation,
                prepared_route={
                    **hint, "control": "Red diamond button at the descending lift."
                },
            )
            lift_instructions = (
                "The direct walk toward the red lift button failed. "
                "If there is no live opponent or visible descent, reposition now. "
                "Follow a clear map_input or take an available sidestep toward open floor "
                "while keeping the lift button in view. Back up only if the sides are blocked. "
            )
        else:
            lift_instructions = (
                "The red diamond wall button at this lift activates by touching it. "
                "Select touch_switch if the live image shows the button with a clear approach. "
                "Return switch_point [x,y] as percentages of the entire image, centered on the diamond. "
                "Use null for switch_point on other actions. If the button is at the edge of the image, turn toward it first. "
            )
        lift_instructions += (
            "During visible descent, choose ride_lift when available. "
            "Confirm the platform is moving before waiting to reach the lower passage. "
        )
    exit_instructions = (
        "You are leaving the lift. Use map_input to head toward the lightning door "
        "when the way is clear. Backing up here can put you back on the platform. "
        if lift_exit
        else ""
    )
    prompt = (
        "You are playing the Quake video game from its current rendered image. "
        "Select an action only from allowed. The planner gives objectives and can suggest unavailable moves. "
        "Return JSON with opponent (live_ahead, live_left, live_right, fallen, none or unclear), "
        "opponent_x (0 at the left edge, 50 at center, 100 at the right edge; use null if no live monster is visible), "
        "action (one of the supplied inputs), and scene "
        "(one short sentence describing a concrete visible cue for that move). "
        "Look for living Quake monsters before navigation. If a living monster is straight ahead "
        "and the shotgun can shoot, choose fire. If one is off-center, use face_left or face_right "
        "to inspect it on the next frame. Ignore the player's HUD face, weapon, corpses, lamps and switches. "
        "After a health drop, inspect for danger. If the most recent shot is unconfirmed, "
        "check the fresh view for the same monster, which may be recoiling. A past sighting does not "
        "count as a live opponent in this frame. check_view holds still briefly for a new observation. "
        "Use map_input as the next navigation input when it is available and the way is clear. "
        "A search turn points back toward the route after losing the match. "
        "When there is no map_input, the last landmark is a reference and could be elsewhere. "
        "Give fresh obstacles and previous failed movement priority over an older planner suggestion. "
        + lift_instructions
        + exit_instructions
        + json.dumps(
            dict(
                objective=objective,
                allowed=choices,
                map_input=None if initial_turn else route_input(hint, memory),
                planner=plan,
                recent=recent,
                navigation=navigation,
            )
        )
    )
    properties = {
        "opponent": {"type": "string", "enum": OPPONENT_LABELS},
        "opponent_x": {"type": ["number", "null"]},
        "action": {"type": "string", "enum": choices},
        "scene": {"type": "string"},
    }
    if "touch_switch" in choices:
        properties["switch_point"] = {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        }
    schema = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    reply = model._read_frame(jpeg, prompt, 145 if lift else 112, schema=schema)
    action = reply.get("action")
    opponent = reply.get("opponent")
    if opponent not in OPPONENT_LABELS:
        opponent = "unclear"
    if (
        action not in choices
        or not isinstance(reply.get("scene"), str)
        or not reply["scene"].strip()
    ):
        if blocked_switch and action == "touch_switch":
            recovery = "check_view"
            if reposition and opponent in ("none", "fallen"):
                recovery = next(
                    (a for a in reposition if a not in recent), reposition[0]
                )
            return dict(
                action=recovery,
                scene="The direct approach to the lift button is blocked.",
                opponent=opponent,
                camera_reason="Gemma requested an unavailable switch approach.",
            )
        raise ValueError("Gemma returned an invalid game decision")
    if action == "fire" and opponent != "live_ahead":
        if lift:
            return dict(
                action="check_view",
                scene="Checking the lift area for a reachable button or passage.",
                opponent=opponent,
            )
        raise ValueError(
            "Quake shot withheld pending a fresh view of a live opponent ahead."
        )
    x = reply.get("opponent_x")
    decision = dict(
        action=action, scene=reply["scene"].strip()[:350], opponent=opponent
    )
    if action == "touch_switch":
        marker = validated_marker(
            {"kind": "touch_button", "point": reply.get("switch_point")}
        )
        if (
            marker
            and 14 <= marker["point"][0] <= 86
            and not opponent.startswith("live_")
        ):
            decision["switch_point"] = marker["point"]
        else:
            decision.update(
                action="check_view",
                scene="Checking for a clear approach to the lift button.",
            )
    if (
        opponent.startswith("live_")
        and type(x) in (int, float)
        and 0 <= x <= 100
        and (opponent != "live_left" or x < 50)
        and (opponent != "live_right" or x > 50)
    ):
        decision["opponent_x"] = x
    return decision


class Pilot:
    def __init__(self, board, key, records, key_file=None):
        self.board = board
        self.records = records
        self.key_file = key_file
        self.hud = HealthHUD(
            Path.home() / "Library/Application Support/Mojo Quake/media/id1/pak0.pak"
        )
        self.atlas = RouteAtlas(
            HERE.parent / "build/host/tyr-quake",
            Path.home() / "Library/Application Support/Mojo Quake/media",
        )
        self.route_line = [
            [int(s.position[0]), int(s.position[1]), s.tick] for s in self.atlas.samples
        ]
        self.gemma = Models(key, single_call=True, cloud_model=CLOUD_MODELS["gemma"])
        self.planner = Models(
            key, single_call=True, cloud_model=CLOUD_MODELS["minimax"]
        )
        self.actor_pool = ThreadPoolExecutor(1)
        self.plan_pool = ThreadPoolExecutor(1)
        self.cv = threading.Condition()
        self.process = None
        self.generation = self.revision = self.token = self.seq = 0
        self.closed = False
        self.heartbeat = threading.Thread(target=self.ping_loop, daemon=True)
        self.reset()
        self.mode = self.requested = "closed"
        self.phase = "Game closed"
        self.heartbeat.start()

    def reset(self):
        self.guide = BoardGuide(self.atlas)
        self.terminal = None
        self.memory = RouteMemory()
        self.encounter = EncounterMemory()
        self.motion = None
        self.matched_trail = deque(maxlen=160)
        self.route_hint = None
        self.matcher = None
        self.settle_until = 0
        self.last_plan_key = None
        self.info = self.frame = self.jpeg = self.plan = self.active = (
            self.last_decision
        ) = None
        self.mode = self.requested = "paused"
        self.phase = "Connecting"
        self.error = ""
        self.history = deque(maxlen=50)
        self.actor = self.strategy = None
        self.plan_since = self.retry = self.last_source = -10000
        self.last_accept = 0
        self.offset = self.rtt = None
        self.arrivals = deque(maxlen=36)
        self.directory = None

    def changed(self):
        self.revision += 1
        self.cv.notify_all()

    def log(self, record):
        with (self.directory / "events.jsonl").open("a") as stream:
            print(json.dumps(record, separators=(",", ":")), file=stream)

    def connect(self, *, encounter=False):
        with self.cv:
            if self.process is not None or self.closed:
                return False
            self.generation += 1
            self.reset()
            self.directory = Path(tempfile.mkdtemp(prefix="board-", dir=self.records))
            _, _, bundle = board_bundle()
            err = (self.directory / "ssh.log").open("w")
            try:
                self.process = subprocess.Popen(
                    [
                        "ssh",
                        "-4",
                        "-T",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "ConnectTimeout=5",
                        "-o",
                        "ServerAliveInterval=3",
                        "-o",
                        "ServerAliveCountMax=2",
                        self.board,
                        f"exec python3 -u {bundle}/unoq_bridge.py"
                        + (" --encounter" if encounter else ""),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=err,
                )
            finally:
                err.close()
            threading.Thread(
                target=self.receive_loop,
                args=(self.process, self.generation, self.directory),
                daemon=True,
            ).start()
            self.changed()
            return True

    def send(self, **message):
        if self.process is None:
            return False
        try:
            self.process.stdin.write((json.dumps(message) + "\n").encode())
            self.process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def ping_loop(self):
        while True:
            with self.cv:
                if self.closed:
                    return
                if self.process is not None:
                    self.send(op="ping", sent=time.monotonic())
            time.sleep(0.75)

    def command(self, name):
        if name in ("connect", "encounter"):
            return self.connect(encounter=name == "encounter")
        with self.cv:
            if self.process is None or (name != "close" and not self.frame):
                return False
            if name not in ("play", "pause", "step", "close"):
                return False
            if self.terminal and name in ("play", "step"):
                return False
            if name in ("play", "step") and self.key_file is not None:
                try:
                    auth = "Bearer " + read_key(self.key_file)
                except (OSError, ValueError) as exc:
                    self.error = str(exc)
                    self.changed()
                    return False
                for model in (self.gemma, self.planner):
                    model.cloud.headers["Authorization"] = auth
                self.error = ""
            self.token += 1
            self.requested = "paused" if name in ("pause", "close") else name
            self.phase = "Closing game" if name == "close" else "Awaiting board"
            if name == "close":
                self.requested = "closed"
            sent = self.send(op=name, token=self.token)
            self.changed()
            return sent

    def receive_loop(self, process, gen, directory):
        failure = ""
        try:
            for line in process.stdout:
                msg = json.loads(line)
                now = time.monotonic()
                jpeg = (
                    jpeg_from_board(msg.pop("pixels"))
                    if msg["type"] == "frame"
                    else None
                )
                with self.cv:
                    if gen != self.generation:
                        break
                    self.receive(msg, jpeg, now)
            status = process.wait(timeout=4)
            if status:
                failure = (
                    f"Board connection exited ({status}). "
                    + (directory / "ssh.log").read_text(errors="replace")[-350:]
                )
        except (
            ValueError,
            KeyError,
            OSError,
            subprocess.SubprocessError,
            zlib.error,
        ) as exc:
            failure = str(exc)
        finally:
            process.stdout.close()
            try:
                process.stdin.close()
            except OSError:
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            with self.cv:
                if gen == self.generation:
                    self.process = None
                    if self.active:
                        self.finish_receipt(
                            "Connection closed",
                            self.frame["tick"] if self.frame else None,
                        )
                    self.requested = self.mode = "closed"
                    self.phase = "Disconnected" if failure else "Game closed"
                    self.error = failure
                    self.changed()

    def finish_receipt(self, status, tick, stats=None):
        self.active.update(status=status, end_tick=tick)
        if stats:
            self.active["end_state"] = stats
        self.last_decision = self.active.copy()
        self.history.append(self.last_decision)
        self.log(self.last_decision)
        self.active = None

    def receive(self, msg, jpeg, now):
        kind = msg["type"]
        if kind == "ready":
            self.info = msg
            self.phase = "Starting E1M1"
            if msg.get("start") == "encounter":
                self.guide.index = min(
                    range(len(self.atlas.samples)),
                    key=lambda i: abs(self.atlas.samples[i].tick - 703),
                )
        elif kind == "pong":
            rtt = now - msg["sent"]
            if self.rtt is None or rtt < self.rtt:
                self.rtt = rtt
                self.offset = (now + msg["sent"]) / 2 - msg["board_time"]
            return
        elif kind == "mode":
            if "token" in msg and msg["token"] != self.token:
                return
            if msg.get("token") == self.token or (
                "token" not in msg and self.requested != "closed"
            ):
                if msg["mode"] in ("step", "play"):
                    self.arrivals.clear()
                self.mode = msg["mode"]
                self.requested = self.mode
                self.phase = (
                    "Paused" if self.mode == "paused" else "Waiting for a board frame"
                )
            if msg.get("reason"):
                self.error = msg["reason"]
        elif kind == "frame":
            self.send(op="ack", sequence=msg["sequence"])
            self.frame, self.jpeg = msg, jpeg
            stats = msg.get("stats", {})
            if not self.terminal and stats:
                if float(stats.get("hp", 1)) <= 0:
                    self.terminal = "Player died"
                elif (
                    int(stats.get("intermission", 0))
                    or stats.get("map", "e1m1") != "e1m1"
                ):
                    self.terminal = "Level complete"
                if self.terminal:
                    self.command("pause")
            if self.terminal:
                self.phase = self.terminal
                self.changed()
                return
            self.track_frame(jpeg, msg["tick"], msg["yaw"], msg.get("pitch", 0))
            self.arrivals.append((msg["tick"], now))
            if self.mode == "paused" and self.requested == "paused":
                self.phase = "Paused"
            if self.mode in ("play", "step") and self.requested == self.mode:
                self.offer(now)
            elif self.mode == "paused" and self.route_hint is None:
                self.offer(now)
        elif kind == "applied" and self.active and msg["id"] == self.active["id"]:
            self.active.update(
                applied_tick=msg["tick"], age_ms=msg["age_ms"], status="Applying"
            )
            if msg.get("turn_degrees"):
                self.active.update(
                    turn_degrees=msg["turn_degrees"], turn_ticks=msg["turn_ticks"]
                )
            self.phase = "Applying input"
            count = self.frame.get("stats", {}).get("kills", "").partition("/")[0]
            self.encounter.applied(
                self.active, msg["tick"], int(count) if count.isdigit() else None
            )
            duration, forward, side, _ = MOVES[msg["action"]]
            duration = msg.get("duration_ticks", duration)
            alignment = msg["turn_ticks"] if msg["action"] == "touch_switch" else 0
            self.motion = (
                msg["tick"] + alignment, msg["tick"] + duration - 1, forward, side
            )
        elif (
            kind in ("reject", "end") and self.active and msg["id"] == self.active["id"]
        ):
            if kind == "reject":
                self.finish_receipt(msg["reason"], msg["tick"])
                self.phase = "Refreshing observation"
            else:
                count = msg["stats"].get("kills", "").partition("/")[0]
                confirmed = self.encounter.confirm_kills(
                    int(count) if count.isdigit() else None
                )
                if (
                    self.active.get("action") == "fire"
                    and self.active.get("applied_tick") is not None
                ):
                    self.active["shot_outcome"] = (
                        "Confirmed kill" if confirmed else "Shot outcome unconfirmed"
                    )
                if msg["status"] == "applied":
                    self.last_accept += 1
                    if self.active.get("action") == "wait_door":
                        self.guide.door_waited = True
                if self.motion:
                    start, stop, fwd, side = self.motion
                    self.motion = (start, min(stop, msg["tick"]), fwd, side)
                    if fwd or side:
                        self.settle_until = msg["tick"] + 12
                if (
                    self.mode == "step"
                    and self.requested == "step"
                    and msg["status"] == "applied"
                ):
                    self.requested = "paused"
                self.finish_receipt(msg["status"], msg["tick"], msg["stats"])
        self.changed()

    def track_frame(self, jpg, tick, yaw, pitch=0):
        if self.memory.last_img is not None and tick <= self.memory.tick:
            return
        if self.motion:
            start, end, forward, side = self.motion
            if start <= tick <= end:
                self.memory.track(jpg, tick, yaw, pitch, forward, side)
                return
            if tick > end:
                # SSH can drop intermediate previews. Anchor the completed input
                # to its receipt, then let neutral frames settle the image comparison.
                if self.memory.tick < end:
                    self.memory.track(jpg, end, yaw, pitch, forward, side)
                self.motion = None
        self.memory.track(jpg, tick, yaw, pitch)

    def offer(self, now):
        tick = self.frame["tick"]
        if (
            self.matcher
            or self.actor
            or self.active
            or now < self.retry
            or tick <= self.last_source
            or tick < self.settle_until
        ):
            return
        self.last_source = tick
        img, yaw, captured = self.jpeg, self.frame["yaw"], self.frame["captured"]
        job = self.actor_pool.submit(
            self.guide.board_view, img, yaw, tick, self.frame.get("pitch", 0)
        )
        self.matcher = job
        job.add_done_callback(
            lambda f, gen=self.generation, token=self.token: self.located(
                f, gen, token, tick, img, yaw, captured, now
            )
        )

    def located(self, job, gen, token, tick, img, yaw, captured, received):
        with self.cv:
            if gen != self.generation:
                return
            self.matcher = None
            try:
                hint = dict(job.result(), source_tick=tick)
            except Exception as exc:
                self.error = f"Route match failed: {exc}"
                self.retry = time.monotonic() + 1
                self.changed()
                return
            self.route_hint = hint
            if hint["matched"] and (
                not self.matched_trail
                or self.matched_trail[-1] != hint["reference_tick"]
            ):
                self.matched_trail.append(hint["reference_tick"])
            self.changed()
            if (
                token != self.token
                or self.mode not in ("play", "step")
                or self.requested != self.mode
            ):
                return
            memory = self.memory.guidance(hint.get("route"))
            self.request_decision(tick, img, yaw, captured, received, hint, memory)

    def request_decision(self, tick, img, yaw, captured, received, hint, memory):
        now = time.monotonic()
        hp, ammo = self.hud.read_status(img)
        self.encounter.observe_health(hp, tick)
        context = {
            "prepared_route": hint,
            "exploration": memory,
            "visible_hp": hp,
            "visible_ammo": ammo,
        }
        encounter = self.encounter.context(tick, yaw)
        if encounter:
            context["encounter"] = encounter
        if hint.get("control") and any(
            r.get("action") == "touch_switch"
            and r["status"] == "applied"
            and tick - r["end_tick"] <= 3 * HZ
            for r in reversed(self.history)
        ):
            context["recent_switch_attempt"] = True
        plan_key = (hint["stage"], tuple(memory["blocked_inputs"]))
        interval = 2 if plan_key != self.last_plan_key else 10
        if self.strategy is None and now - self.plan_since >= interval:
            self.plan_since = now
            self.last_plan_key = plan_key
            job = self.plan_pool.submit(
                read_plan,
                self.planner,
                img,
                {
                    "goal": "Find the E1M1 exit",
                    "recent_inputs": [r.get("action") for r in list(self.history)[-4:]],
                    **context,
                },
                self.atlas.photos[hint["photo"]],
            )
            self.strategy = job
            job.add_done_callback(
                lambda f, g=self.generation, t=tick: self.planned(f, g, t)
            )
        self.seq += 1
        ident = self.seq
        (self.directory / f"{ident}.jpg").write_bytes(img)
        initial = (
            self.mode == "step"
            and not self.last_accept
            and (self.info or {}).get("start") == "entrance"
        )
        current = dict(
            id=ident,
            source_tick=tick,
            before_yaw=yaw,
            navigation=context,
            status="Reading frame",
            capture_to_mac_ms=(
                round(1000 * (received - self.offset - captured), 1)
                if self.offset is not None
                else None
            ),
            objective=(
                "Inspect one side of the entrance" if initial else hint["objective"]
            ),
        )
        self.active = current
        plan = (
            self.plan
            if self.plan and tick - self.plan["source_tick"] <= 20 * 72
            else None
        )
        job = self.actor_pool.submit(
            choose,
            self.gemma,
            img,
            plan,
            [r.get("action") for r in list(self.history)[-5:]],
            initial,
            context,
        )
        self.actor = job
        self.phase = "Gemma is reading the board frame"
        job.add_done_callback(
            lambda f, g=self.generation, k=self.token, i=ident, s=now: self.decided(
                f, g, k, i, s
            )
        )

    def planned(self, job, gen, tick):
        with self.cv:
            if self.generation != gen:
                return
            self.strategy = None
            try:
                self.plan = dict(job.result(), source_tick=tick)
            except Exception as exc:
                self.plan = dict(
                    objective="Planner unavailable",
                    evidence=str(exc)[:160],
                    source_tick=tick,
                )
            self.changed()

    def decided(self, job, gen, token, ident, started):
        with self.cv:
            if gen != self.generation:
                return
            self.actor = None
            if not self.active or self.active["id"] != ident:
                return
            if token != self.token or self.requested not in ("play", "step"):
                self.finish_receipt("Interrupted", self.frame["tick"])
                self.changed()
                return
            try:
                choice = job.result()
                if self.active["objective"] != "Inspect one side of the entrance":
                    choice = self.encounter.react(
                        choice,
                        self.active["source_tick"],
                        self.active["before_yaw"],
                        self.active["navigation"].get("encounter", {}),
                    )
                    choice = limit_blind_turns(
                        choice,
                        self.active["source_tick"],
                        self.history,
                        self.active["navigation"],
                    )
                self.active.update(
                    choice, api_ms=round((time.monotonic() - started) * 1000)
                )
                steer = camera_steer(choice, self.active["navigation"])
                self.error = ""
                self.active["status"] = self.phase = "Awaiting input receipt"
                if not self.send(
                    op="input",
                    id=ident,
                    source=self.active["source_tick"],
                    action=choice["action"],
                    steer=steer,
                ):
                    raise RuntimeError("Board input link closed")
            except Exception as exc:
                self.error = str(exc)[:200]
                self.finish_receipt("Model or link error", self.frame["tick"])
                self.retry = time.monotonic() + 1
                if isinstance(
                    exc, httpx.HTTPStatusError
                ) and exc.response.status_code in (401, 403):
                    self.error = f"Modular Cloud rejected this credential (HTTP {exc.response.status_code}). Update the Mac credential and press Play or Single step."
                    self.command("pause")
            self.changed()

    def snapshot(self, after):
        with self.cv:
            if after == self.revision:
                self.cv.wait_for(
                    lambda: self.revision != after or self.closed, timeout=3
                )
            f = self.frame or {}
            fps = None
            if len(self.arrivals) > 1:
                elapsed = self.arrivals[-1][1] - self.arrivals[0][1]
                if elapsed > 0:
                    fps = round((len(self.arrivals) - 1) / elapsed, 1)
            return dict(
                revision=self.revision,
                generation=self.generation,
                board=self.info,
                mode=self.mode,
                requested=self.requested,
                phase=self.phase,
                error=self.error,
                terminal=self.terminal,
                connected=self.process is not None,
                tick=f.get("tick"),
                stats=f.get("stats", {}),
                route=self.route_hint,
                matched_trail=list(self.matched_trail),
                exploration=self.memory.diagram(),
                yaw=f.get("yaw"),
                hz=f.get("hz"),
                display_fps=f.get("display_fps"),
                preview_fps=fps,
                dropped=f.get("dropped", 0),
                capture_mac_ms=(
                    1000 * (f["captured"] + self.offset)
                    if f and self.offset is not None
                    else None
                ),
                server_ms=time.monotonic() * 1000,
                rtt_ms=round(1000 * self.rtt, 1) if self.rtt is not None else None,
                picture=base64.b64encode(self.jpeg).decode() if self.jpeg else None,
                plan=self.plan,
                current=self.active.copy() if self.active else None,
                last=self.last_decision,
                history=list(reversed(self.history)),
            )

    def close(self):
        with self.cv:
            self.closed = True
            self.send(op="close")
            self.cv.wait_for(lambda: self.process is None, timeout=6)
        self.actor_pool.shutdown(wait=True, cancel_futures=True)
        self.plan_pool.shutdown(wait=True, cancel_futures=True)
        self.gemma.close()
        self.planner.close()


class Web(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body=b"", kind="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.headers.get("Host") not in self.server.hosts:
            return self.reply(403)
        url = urlsplit(self.path)
        p = self.server.pilot
        if url.path == "/api/live":
            try:
                after = int(parse_qs(url.query).get("after", [-1])[0])
            except ValueError:
                return self.reply(400)
            return self.reply(200, json.dumps(p.snapshot(after)).encode())
        if url.path == "/api/clock":
            return self.reply(200, json.dumps(time.monotonic() * 1000).encode())
        if url.path == "/api/route":
            return self.reply(
                200,
                json.dumps(
                    {"points": p.route_line, "stages": [[s[0], s[2]] for s in STAGES]}
                ).encode(),
            )
        image = re.fullmatch(r"/api/frame/(\d{1,9})/(\d{1,9})", url.path)
        if image:
            with p.cv:
                if p.directory is not None and int(image[1]) == p.generation:
                    path = p.directory / (image[2] + ".jpg")
                    if path.is_file():
                        return self.reply(200, path.read_bytes(), "image/jpeg")
            return self.reply(404)
        assets = {
            "/": ("board.html", "text/html; charset=utf-8"),
            "/board.js": ("board.js", "text/javascript"),
            "/style.css": ("style.css", "text/css"),
        }
        if url.path in assets:
            name, kind = assets[url.path]
            return self.reply(200, (HERE / name).read_bytes(), kind)
        self.reply(404)

    def do_POST(self):
        host = self.headers.get("Host")
        if (
            host not in self.server.hosts
            or self.headers.get("Origin") != "http://" + host
        ):
            return self.reply(403)
        if self.path not in (
            "/api/play",
            "/api/step",
            "/api/pause",
            "/api/close",
            "/api/connect",
            "/api/encounter",
        ):
            return self.reply(404)
        return self.reply(204 if self.server.pilot.command(self.path[5:]) else 409)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", default="arduino@tommy-uno-q.local")
    parser.add_argument(
        "--stage",
        action="store_true",
        help="Stage and verify the bridge and ARM64 game before connecting",
    )
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument(
        "--start", choices=("entrance", "encounter", "closed"), default="entrance"
    )
    parser.add_argument(
        "--records", type=Path, default=HERE.parent / "build/board-observatory"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.@-]*", args.board):
        parser.error("Invalid SSH board address")
    if args.stage:
        stage_bundle(args.board)
    args.records.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Web)
    server.hosts = {
        f"127.0.0.1:{server.server_port}",
        f"localhost:{server.server_port}",
    }
    pilot = Pilot(args.board, read_key(args.key_file), args.records, args.key_file)
    server.pilot = pilot
    try:
        if args.start != "closed":
            pilot.connect(encounter=args.start == "encounter")
        print(f"UNO Q Observatory: http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        pilot.close()


if __name__ == "__main__":
    main()
