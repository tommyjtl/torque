# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28,<1", "Pillow>=11,<13", "opencv-python-headless>=4.10,<5"]
# ///
"""Matched Mac Quake experiments. Both controllers send ordinary player inputs."""

import argparse
import concurrent.futures
import hashlib
import io
import json
import math
import statistics
import sys
import threading
import time
from pathlib import Path

import cv2
import httpx
from visual_tracker import FeatureBuffer, FrameBuffer

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT / "agent_view"))
from game import Game, view_signature, visual_change
from models import (
    Models,
    game_input,
    input_chunk,
    read_key,
    validate_choice,
)
from navigation import RouteMemory
from observatory import (
    FRAME_TICKS,
    TICK_RATE,
    Observatory,
    expired_action,
    prepare_start,
)


def ms():
    return time.monotonic() * 1000


def signed(angle):
    return (angle + 180) % 360 - 180


def stage(game, scene):
    if scene == "enemy":
        return prepare_start(game, "encounter", io.StringIO())
    for line in (HERE / "ledge-start.trace").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        n, f, s, u, y, p, b, i = line.split()
        game.yaw, game.pitch = float(y), float(p)
        jpg, state, _ = game.move(
            int(n), int(f), int(s), int(b), up=int(u), impulse=int(i), evaluate=True
        )
    return jpg, state


def seed_plan(scene):
    name = (
        "mac-running-jump.json"
        if scene == "ledge"
        else "mac-observatory-encounter.json"
    )
    data = json.loads((PROJECT / "evidence" / name).read_text())
    return data["live"] if scene == "ledge" else data["decisions"][0]


class InstrumentedGame(Game):
    def arm(self, scene, state, duration, shift, visible_at):
        self.scene = scene
        self.start_tick = self.tick
        self.limit = self.tick + duration
        self.start_time = visible_at
        self.wall = self.start_time / 1000
        self.reference_yaw = self.yaw
        self.shift = shift
        self.intent = None
        self.active_ticks = 0
        self.first_control_ms = None
        self.correction_ms = None
        self.correction_command = None
        self.first_success_tick = None
        self.on_ledge = 0
        self.endpoint = state

    def move(self, ticks, forward=0, side=0, buttons=0, **kwargs):
        armed = hasattr(self, "limit")
        if armed:
            ticks = min(ticks, self.limit - self.tick)
            if ticks <= 0:
                raise AssertionError("stepped past trial limit")
            sent = ms() - self.start_time
            angle = signed(self.yaw - self.reference_yaw)
            # Score only: a compensating input has removed >=2 degrees of the imposed
            # horizontal displacement. An overshoot with greater error gets no credit.
            previous = signed(self.last_yaw - self.reference_yaw)
            expected = "jump_forward" if self.scene == "ledge" else "aim_fire"
            if (
                self.shift
                and self.intent == expected
                and self.correction_ms is None
                and abs(self.shift + angle) <= abs(self.shift) - 2
                and abs(self.shift + angle) < abs(self.shift + previous)
            ):
                self.correction_ms = round(sent, 1)
                self.correction_command = {
                    "action": self.intent,
                    "tick": self.tick - self.start_tick,
                    "relative_yaw": round(angle, 2),
                    "residual_deg": round(self.shift + angle, 2),
                }
            if (
                forward
                or side
                or buttons
                or abs(signed(self.yaw - self.last_yaw)) > 0.1
                or abs(self.pitch - self.last_pitch) > 0.1
            ):
                self.active_ticks += ticks
                if self.first_control_ms is None:
                    self.first_control_ms = round(sent, 1)
        self.last_yaw, self.last_pitch = self.yaw, self.pitch
        jpg, state, row = super().move(ticks, forward, side, buttons, **kwargs)
        if armed and state:
            self.endpoint = state
            if self.scene == "ledge":
                x, y, z = map(float, state["pos"].split(","))
                on = (
                    624 <= x
                    and 80 <= y <= 304
                    and abs(z - 72) < 1
                    and int(state["flags"]) & 512
                )
                self.on_ledge = self.on_ledge + ticks if on else 0
                success = self.on_ledge >= 12
            else:
                success = int(state["kills"].split("/")[0]) >= 1
            if success and self.first_success_tick is None:
                self.first_success_tick = self.tick - self.start_tick
        return jpg, state, row

    def ended(self):
        return (
            self.tick >= self.limit
            or int(self.endpoint["hp"]) <= 0
            or int(self.endpoint["intermission"]) != 0
        )


class DirectModels(Models):
    """A single cloud call emits both the visible targets and the chosen macro."""

    def observe(self, jpeg):
        vision, self.choice = self.observe_and_choose(jpeg, self.recent, self.context)
        return vision

    def decide(self, vision, recent, navigation):
        return validate_choice(*self.choice, vision, recent, navigation)


class Baseline(Observatory):
    """Use the production decision cycle verbatim, with a bounded trial instead of the UI."""

    def __init__(self, models, executor, game):
        self.models, self.inference, self.game = models, executor, game
        self.cv = threading.Condition()
        self.run = 1
        self.closing = False
        self.pause_epoch = 0
        self.finish_requested = False

    def publish_frame(self, *args):
        self.finish_requested = self.game.ended()

    def update(self, run, **fields):
        if "phase" in fields:
            event = fields.get("current") or {}
            self.game.intent = (
                event.get("action") if event.get("applied_tick") is not None else None
            )
        return True

    def publish_map(self, *args):
        pass


def move_paced(game, memory, jpg, state, deadline, n, controls):
    n = min(n, game.limit - game.tick)
    jpg, state, _ = game.move(n, *controls, evaluate=True)
    memory.track(jpg, game.tick, game.yaw, game.pitch, *controls)
    deadline += n / TICK_RATE
    time.sleep(max(0, deadline - time.monotonic()))
    return jpg, state, deadline


def baseline(game, models, executor, memory, jpg, state, carry, log):
    host = Baseline(models, executor, game)
    deadline = game.wall
    recent = []
    if carry:
        action, ticks, controls = carry
        game.intent = action
        while ticks and not game.ended():
            n, keys = input_chunk(action, ticks, controls, FRAME_TICKS)
            jpg, state, deadline = move_paced(
                game, memory, jpg, state, deadline, n, keys
            )
            ticks -= n
    while not game.ended():
        if isinstance(models, DirectModels):
            models.recent = recent[-4:]
            models.context = memory.guidance(None)
        ev, jpg, state, deadline = host.decision_cycle(
            1,
            game,
            jpg,
            state,
            io.StringIO(),
            len(log) + 1,
            recent[-4:],
            0,
            deadline,
            memory,
        )
        log.append(
            {
                k: ev.get(k)
                for k in (
                    "action",
                    "observed_tick",
                    "applied_tick",
                    "vision_ms",
                    "decision_ms",
                    "note",
                )
            }
        )
        if ev["ticks"]:
            recent.append(
                {"action": ev["action"], "view_change_pct": ev["view_change_pct"]}
            )


def target_for(action, vision):
    return vision.get(
        {"aim_fire": "enemy", "follow_route": "route", "jump_forward": "landing"}.get(
            action
        )
    )


class Skill:
    def __init__(self, action, vision, source, buf, game, remaining=None):
        self.action, self.source = action, source
        self.total, self.forward, self.side, self.buttons, yaw, pitch = game_input(
            action, vision, game.pitch
        )
        self.left = remaining if remaining is not None else self.total
        point = target_for(action, vision)
        self.track = (
            buf.anchor(source, point, "enemy" if action == "aim_fire" else "surface")
            if point is not None
            else None
        )
        self.targeted = point is not None
        self.orient = (
            (yaw, pitch) if remaining is None and not self.targeted else (0, 0)
        )
        self.before = None

    def input(self, game):
        age = game.tick - self.source
        pt = self.track.point() if self.track is not None else None
        elapsed = self.total - self.left
        committed = self.action == "jump_forward" and elapsed >= 12
        if self.targeted and ((not pt) or age > 144) and not committed:
            return None
        if self.left <= 0:
            # Only a freshly confirmed, continuously tracked opponent permits another
            # shot while the asynchronous planner is still busy.
            if self.action != "aim_fire" or not pt or age > 144:
                return None
            self.left = 4
        if pt is not None and not committed:
            yaw = -math.degrees(math.atan((pt[0] - 50) / 50))
            pitch = (
                math.degrees(math.atan((pt[1] - 45) * 0.015))
                if self.action == "aim_fire"
                else 0
            )
            # Small deadband so tracker noise does not become constant mouse input.
            self.orient = (
                max(-15, min(15, 0.82 * yaw)) if abs(yaw) > 0.8 else 0,
                max(-12, min(12, 0.82 * pitch)) if abs(pitch) > 0.8 else 0,
            )
        yaw, pitch = self.orient
        game.yaw = (game.yaw + yaw) % 360
        game.pitch = max(-70, min(80, game.pitch + pitch))
        self.orient = (0, 0)
        n, keys = input_chunk(
            self.action, self.left, (self.forward, self.side, self.buttons), FRAME_TICKS
        )
        self.left -= n
        return n, keys


def candidate(
    game, models, executor, memory, buf, jpg, state, carry, seed, source, log
):
    deadline = game.wall
    skill = None
    if carry:
        action, left, _ = carry
        skill = Skill(action, seed["vision"], source, buf, game, remaining=left)
    future = None
    phase = None
    recent = []
    costs = []
    losses = 0
    corrections = 0
    event = {}
    observed = jpg
    submitted = ms()
    fallbacks = refreshes = 0
    request_after = 0
    features = isinstance(buf, FeatureBuffer)
    while not game.ended():
        if future is not None and future.done() and future.exception() is not None:
            failure = future.exception()
            if not isinstance(
                failure, (KeyError, ValueError, TypeError, httpx.HTTPError)
            ):
                raise failure
            log.append(
                dict(event, note="Inference failed", error=type(failure).__name__)
            )
            future = None
            request_after = ms() + 1000
        if future is not None and future.done():
            value = future.result()
            if phase == "vision":
                event["vision_ms"] = round(ms() - submitted)
                vision = value
                context = memory.guidance(vision["route"], vision.get("landing"))
                if (
                    features
                    and skill
                    and skill.action in ("aim_fire", "jump_forward", "follow_route")
                ):
                    key = {
                        "aim_fire": "enemy",
                        "jump_forward": "landing",
                        "follow_route": "route",
                    }[skill.action]
                    pt = vision.get(key)
                    if pt:
                        refreshed = buf.anchor(event["observed_tick"], pt, key)
                        if refreshed and refreshed.alive:
                            skill.track = refreshed
                            skill.targeted = True
                            skill.source = event["observed_tick"]
                            refreshes += 1
                    elif skill.action == "aim_fire":
                        skill = None
                if visual_change(view_signature(observed), jpg) < 8:
                    memory.describe(vision["scene"])
                submitted = ms()
                future = executor.submit(models.decide, vision, recent[-4:], context)
                phase = "decide"
            else:
                action, _ = value
                event.update(action=action, decision_ms=round(ms() - submitted))
                # Let an already-started jump complete its mechanical sequence.
                if skill and skill.action == "jump_forward" and skill.left > 0:
                    event["note"] = "jump committed"
                elif expired_action(
                    action,
                    game.tick - event["observed_tick"],
                    visual_change(view_signature(observed), jpg),
                ) and not target_for(action, vision):
                    event["note"] = "expired"
                elif game.tick - event["observed_tick"] > 144 and target_for(
                    action, vision
                ):
                    event["note"] = "expired"
                    skill = None
                else:
                    t = ms()
                    skill = Skill(action, vision, event["observed_tick"], buf, game)
                    costs.append(ms() - t)
                    skill.before = view_signature(jpg)
                    if skill.targeted and (not skill.track or not skill.track.alive):
                        losses += 1
                        if features and not expired_action(
                            action,
                            game.tick - event["observed_tick"],
                            visual_change(view_signature(observed), jpg),
                        ):
                            # Execute the same bounded macro the serial driver would still accept.
                            # This is one command, never a renewed fire/steering lock.
                            _, _, _, _, yaw, pitch = game_input(
                                action, vision, game.pitch
                            )
                            skill.track = None
                            skill.targeted = False
                            skill.orient = (yaw, pitch)
                            fallbacks += 1
                            event["note"] = "fresh semantic fallback"
                            event["applied_tick"] = game.tick
                        else:
                            skill = None
                            event["note"] = "lost before application"
                    else:
                        event["applied_tick"] = game.tick
                log.append(event)
                future = None
        if future is None and ms() >= request_after:
            observed = jpg
            event = {"observed_tick": game.tick, "note": ""}
            submitted = ms()
            future = executor.submit(models.observe, jpg)
            phase = "vision"

        t = ms()
        angles = (game.yaw, game.pitch)
        move = skill.input(game) if skill else None
        costs.append(ms() - t)
        if (game.yaw, game.pitch) != angles:
            corrections += 1
        if not move:
            if skill and skill.track is not None and not skill.track.alive:
                losses += 1
            skill = None
            move = (FRAME_TICKS, (0, 0, 0))
        n, keys = move
        game.intent = skill.action if skill else None
        jpg, state, deadline = move_paced(game, memory, jpg, state, deadline, n, keys)
        t = ms()
        buf.add(game.tick, jpg)
        if skill and skill.track:
            skill.track.update(buf.frames[-1][1])
        costs[-1] += ms() - t
        if skill and skill.before is not None and skill.left <= 0:
            recent.append(
                {
                    "action": skill.action,
                    "view_change_pct": visual_change(skill.before, jpg),
                }
            )
            skill.before = None
    if future is not None:
        future.cancel()
        log.append(
            dict(event, note="Trial ended before next plan", pending_phase=phase)
        )
    return {
        "local_compute_median_ms": round(statistics.median(costs), 2),
        "loss_events": losses,
        "steering_updates": corrections,
        "fresh_fallbacks": fallbacks,
        "vision_refreshes": refreshes,
    }


def run_trial(args, models, scene, mode, condition, angle):
    game = InstrumentedGame(
        args.binary, args.media, start_map="start" if scene == "enemy" else "e1m1"
    )
    try:
        jpg, state = stage(game, scene)
        fixture_hash = state["hash"]
        seed = seed_plan(scene)
        expected = {"ledge": "45951f0f", "enemy": "b85dca63"}[scene]
        if fixture_hash != expected:
            raise ValueError(f"Unexpected {scene} fixture state: {fixture_hash}")
        memory = RouteMemory()
        buf = FeatureBuffer() if mode == "features" else FrameBuffer()

        def sample(jpg):
            buf.add(game.tick, jpg)
            memory.track(jpg, game.tick, game.yaw, game.pitch)

        source = game.tick
        sample(jpg)
        carry = None
        if condition == "warm":
            action = seed["action"]
            total, f, s, b, y, p = game_input(action, seed["vision"], game.pitch)
            game.yaw = (game.yaw + y) % 360
            game.pitch += p
            _, keys = input_chunk(action, total, (f, s, b), 4)
            jpg, state, _ = game.move(4, *keys, evaluate=True)
            sample(jpg)
            # The same camera nudge and already-active instruction are given to both.
            # Neither controller receives the nudge label, its angle, or the scoring state.
            game.yaw = (game.yaw + angle) % 360
            _, keys = input_chunk(action, total - 4, (f, s, b), 4)
            jpg, state, _ = game.move(4, *keys, evaluate=True)
            visible_at = ms()
            sample(jpg)
            carry = (action, total - 8, (f, s, b))
        else:
            game.yaw = (game.yaw + angle) % 360
            jpg, state, _ = game.move(4, evaluate=True)
            visible_at = ms()
            sample(jpg)
        starting_hash = state["hash"]
        first_image = hashlib.sha256(jpg).hexdigest()
        log = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            game.arm(
                scene,
                state,
                args.ticks,
                angle if condition == "warm" else 0,
                visible_at,
            )
            extras = {}
            if mode in ("serial", "direct"):
                baseline(game, models, executor, memory, jpg, state, carry, log)
            else:
                extras = candidate(
                    game,
                    models,
                    executor,
                    memory,
                    buf,
                    jpg,
                    state,
                    carry,
                    seed,
                    source,
                    log,
                )
            wall_ms = round(ms() - game.start_time, 1)
        elapsed = game.tick - game.start_tick
        hp = int(game.endpoint["hp"])
        return dict(
            scene=scene,
            mode=mode,
            condition=condition,
            angle=angle,
            start_hash=starting_hash,
            first_image_sha256=first_image,
            fixture_hash=fixture_hash,
            elapsed_ticks=elapsed,
            wall_ms=wall_ms,
            final_hash=game.endpoint["hash"],
            hp=hp,
            kills=game.endpoint["kills"],
            success=hp > 0 and game.first_success_tick is not None,
            success_tick=game.first_success_tick,
            first_input_ms=game.first_control_ms,
            compensating_input_ms=game.correction_ms,
            correction_command=game.correction_command,
            neutral_ticks=elapsed - game.active_ticks,
            decision_events=log,
            **extras,
        )
    finally:
        game.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=PROJECT / "build/host/tyr-quake")
    parser.add_argument(
        "--media",
        type=Path,
        default=Path.home() / "Library/Application Support/Mojo Quake/media",
    )
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ticks", type=int, default=432)
    parser.add_argument("--smoke", action="store_true")
    alternatives = parser.add_mutually_exclusive_group()
    alternatives.add_argument(
        "--paired-features",
        action="store_true",
        help="Interleave a fresh serial control with the feature tracker",
    )
    alternatives.add_argument(
        "--features-only",
        action="store_true",
        help="Run the follow-up spatially verified tracker on the same conditions",
    )
    alternatives.add_argument(
        "--one-call",
        action="store_true",
        help="Paired single cloud call vs production, unprimed trials only",
    )
    args = parser.parse_args()
    if args.ticks < FRAME_TICKS:
        parser.error("--ticks must allow at least one input chunk")
    cv2.setNumThreads(1)
    conditions = (
        [("cold", 0)]
        if args.smoke
        else [
            ("cold", 0),
            ("warm", -10),
            ("cold", -8),
            ("warm", 10),
            ("cold", 8),
            ("warm", -14),
            ("warm", 14),
        ]
    )
    if args.one_call:
        conditions = [c for c in conditions if c[0] == "cold"]
    key = read_key(args.key_file)
    models = Models(key)
    direct = DirectModels(key) if args.one_call else None
    try:
        with args.output.open("x", buffering=1) as out:
            rounds = {"cold": 0, "warm": 0}
            for cond, angle in conditions:
                i = rounds[cond]
                rounds[cond] += 1
                for j, scene in enumerate(("ledge", "enemy")):
                    modes = (
                        ("serial", "tracked")
                        if (i + j) % 2 == 0
                        else ("tracked", "serial")
                    )
                    if args.paired_features:
                        modes = tuple(
                            "features" if m == "tracked" else m for m in modes
                        )
                    if args.features_only:
                        modes = ("features",)
                    if args.one_call:
                        modes = tuple("direct" if m == "tracked" else m for m in modes)
                    pair = []
                    for mode in modes:
                        row = run_trial(
                            args,
                            direct if mode == "direct" else models,
                            scene,
                            mode,
                            cond,
                            angle,
                        )
                        pair.append(row)
                        print(json.dumps(row), file=out)
                        print(
                            scene,
                            cond,
                            angle,
                            mode,
                            row["success"],
                            row["compensating_input_ms"],
                            row["wall_ms"],
                            flush=True,
                        )
                    if len(pair) == 2:
                        assert pair[0]["start_hash"] == pair[1]["start_hash"]
                        assert (
                            pair[0]["first_image_sha256"]
                            == pair[1]["first_image_sha256"]
                        )
    finally:
        models.close()
        if direct:
            direct.close()


if __name__ == "__main__":
    main()
