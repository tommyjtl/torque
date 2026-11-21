# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28,<1", "Pillow>=11,<13", "numpy>=1.26,<3", "opencv-python-headless>=4.10,<5"]
# ///
"""Run the local Quake agent and its browser observatory."""

import argparse
import base64
import json
import os
import subprocess
import tempfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Condition, Thread
from urllib.parse import urlsplit

import httpx
from checkpoints import Checkpoints, checkpoint_operation, relocate
from exploration import Exploration
from game import Game, view_signature, visual_change
from hud import DamageSense, HealthHUD
from jev_player import JUMP_TURN, JevPlayer, camera_image
from landmarks import MARK_ACTION, PanelScout, ground_vision
from lookahead import MotionStream, Option, PreviewSearch
from models import (
    CLOUD_MODELS,
    DECISION_MODEL,
    LEVEL_GOAL,
    VISION_MODEL,
    Models,
    game_input,
    input_chunk,
    read_key,
    resolve_proposal,
)
from navigation import RouteMemory, sector
from planning import LOCAL_MODEL, LocalPlayer, ModularGemmaPlayer, PlanFeed
from recordings import Recordings
from route_guide import GUIDE_VERSION, STAGES, RouteAtlas, RouteGuide
from scene_lanes import LaneSense, SceneEstimator
from skills import SkillBook
from movement_lessons import MovementLessons
from survey import PROBES, survey_keys
from targets import CharacterTrack, GameCharacters, combat_motion, track_character

HERE = Path(__file__).resolve().parent
TICK_RATE = 72
FRAME_TICKS = 4


def expired_action(action, age, change):
    # Screen coordinates age faster than a general navigation intent.
    ttl = (
        3
        if action
        in (
            "aim_fire",
            "fire",
            "advance_fire",
            "follow_route",
            "jump_forward",
            "touch_switch",
            "shoot_switch",
        )
        else 8
    )
    return age >= ttl * TICK_RATE or (age >= TICK_RATE and change >= 12)


def recent_context(history):
    """Only visible observations, applied inputs and image feedback reach the player."""
    recent = []
    for event in list(history)[-4:]:
        if not event.get("ticks"):
            continue
        item = {"action": event["action"], "view_change_pct": event["view_change_pct"]}
        vision = event.get("vision") or {}
        for key in ("blocker", "clearance"):
            if key in vision:
                item[key] = vision[key]
        if vision.get("switch") is not None:
            item["saw_switch"] = True
        if vision.get("platform") is not None:
            item["saw_platform"] = True
        if event.get("damage"):
            item["visible_health_loss"] = True
        recent.append(item)
    return recent


def evaluator_stats(state):
    return {
        key: state[key] for key in ("map", "hp", "kills", "intermission", "pos", "hash")
    }


def terminal_phase(state, decisions, limit):
    if int(state["hp"]) <= 0:
        return "Player died"
    if (state["map"] == "e1m1" and int(state["intermission"]) == 1) or state[
        "map"
    ] == "e1m2":
        return "Level complete"
    if limit is not None and decisions >= limit:
        return "Step limit reached"
    return None


def session_outcome(state, decisions, limit, book):
    outcome = terminal_phase(state, decisions, limit)
    if outcome == "Player died" and book and book.saved:
        return (
            "Step limit reached" if limit is not None and decisions >= limit else None
        )
    return outcome


def screen_outcome(jpeg, hud, count=0, limit=None, book=None):
    """The acting controller sees death and intermission on the same display as a player."""
    if hud.completed(jpeg):
        return "Level complete"
    visible_hp = hud.read(jpeg)
    if visible_hp is not None and visible_hp <= 0 and not (book and book.saved):
        return "Player died"
    if limit is not None and count >= limit:
        return "Step limit reached"
    return None


def prepare_start(game, scenario, trace):
    if scenario == "entrance":
        jpg, state, row = game.move(24, evaluate=True)
        print(row, file=trace)
        return jpg, state
    # Use the existing navigation recording to stage a visible first encounter.
    # Remove every attack input. The first shot is chosen by the live agent.
    handoff = 703
    for line in (
        (HERE.parent / "replays/slipgate-encounter.trace").read_text().splitlines()
    ):
        if not line.strip() or line.startswith("#"):
            continue
        n, f, s, u, yaw, pitch, buttons, impulse = line.split()
        n = min(int(n), handoff - game.tick)
        game.yaw, game.pitch = float(yaw), float(pitch)
        final = game.tick + n == handoff
        jpg, state, row = game.move(
            n,
            int(f),
            int(s),
            int(buttons) & ~1,
            up=int(u),
            impulse=int(impulse),
            evaluate=final,
        )
        print(row, file=trace)
        if final:
            if (
                state["map"] != "e1m1"
                or int(state["hp"]) <= 0
                or state["kills"].split("/")[0] != "0"
            ):
                raise RuntimeError("Encounter start failed validation")
            return jpg, state
    raise ValueError("The encounter recording is incomplete")


def restore_session(game, source, events, trace, log, captured, memory):
    """Rebuild a paused run from its inputs, checking every recorded decision."""
    book = memory.checkpoints or Checkpoints()
    observed = {e["observed_tick"]: e for e in events}
    completed = {e["end_tick"]: e for e in events}
    landmarks = {
        e.get("vision_tick"): e["vision"]
        for e in events
        if e.get("vision") and e.get("remembered_scene", True)
    }
    first_observation = events[0]["observed_tick"]
    frames = {}
    history = deque(maxlen=80)
    state = None
    for line in (source / "inputs.trace").read_text().splitlines():
        op = (observed.get(game.tick) or {}).get("checkpoint")
        if op:
            checkpoint_operation(game, op)
            if op["op"] == "save":
                game.archive_checkpoint(op["slot"], captured.parent / "saves")
        n, f, s, u, yaw, pitch, buttons, impulse = line.split()
        game.yaw, game.pitch = float(yaw), float(pitch)
        end = game.tick + int(n)
        image, state, row = game.move(
            int(n),
            int(f),
            int(s),
            int(buttons),
            up=int(u),
            impulse=int(impulse),
            evaluate=end in completed or end in observed,
        )
        print(row, file=trace)
        if op and op["op"] == "load":
            relocate(memory, book.saved[op["slot"]], image, game)
        elif end == first_observation:
            memory.track(image, end, game.yaw, game.pitch)
        elif end > first_observation:
            memory.track(image, end, game.yaw, game.pitch, int(f), int(s), int(buttons))
        if end in landmarks and memory.describe(landmarks[end]["scene"]):
            memory.remember_passages(landmarks[end])
        if end in observed:
            if state["hash"] != observed[end]["observed_stats"]["hash"]:
                raise ValueError(f"Observation mismatch at tick {end}")
            original = source / "frames" / f"{end}.jpg"
            pixels = original.read_bytes() if original.is_file() else image
            recorded_hint = observed[end].get("route_guide")
            guide = getattr(memory, "route_guide", None)
            if guide and recorded_hint and recorded_hint.get("version") != GUIDE_VERSION:
                # Older recordings could jump straight from the spawn room to the
                # exit section. Re-localize from the archived observation on resume.
                guide.observe(pixels, game.yaw, game.pitch)
            (captured / f"{end}.jpg").write_bytes(pixels)
            frames[end] = base64.b64encode(pixels).decode()
        if end in completed:
            event = completed[end]
            if state["hash"] != event["evaluator"]["hash"]:
                raise ValueError(f"Gameplay mismatch at tick {end}")
            guide = getattr(memory, "route_guide", None)
            if guide:
                guide.restore_observation(event)
                if event.get("checkpoint"):
                    op = event["checkpoint"]
                    guide.checkpoint(op["slot"], op["op"] == "load")
            if event.get("checkpoint"):
                saved_op = event["checkpoint"]
                if saved_op["op"] == "save":
                    saved_op = dict(saved_op, place=memory.here)
                book.record(saved_op, end)
            else:
                book.observe_action(event, memory.yaw)
                if memory.exploration:
                    memory.exploration.restore(event, memory.origin_yaw or 0)
            for notice in event.get("door_notices", []):
                current_notice = dict(notice)
                if current_notice["place"] >= len(memory.places):
                    current_notice["place"] = memory.here
                memory.mechanisms.see_notice(**current_notice)
            if event.get("action") == "leave_locked_door":
                memory.mechanisms.departure(event["observed_tick"])
            memory.mechanisms.tested(event, end)
            archived = {k: v for k, v in event.items() if k != "evaluator"}
            history.append(dict(archived, frame=frames.pop(event["observed_tick"])))
            print(json.dumps(event), file=log)
    if (
        not history
        or history[-1]["seq"] != len(events)
        or game.tick != events[-1]["end_tick"]
    ):
        raise ValueError("The session did not end at a recorded decision")
    return image, state, history


class GemmaFrameChecks:
    def __init__(self):
        self.last_tick = -10000
        self.confirm = False

    def request(self, tick, hit_age):
        elapsed = tick - self.last_tick
        if self.confirm:
            reason = "After a camera turn"
        elif hit_age is not None and 0 <= hit_age <= 36 and elapsed >= 24:
            reason = "After a health drop"
        elif elapsed >= TICK_RATE:
            reason = "Periodic game view"
        else:
            return None
        self.last_tick = tick
        self.confirm = False
        return reason


class Observatory:
    def __init__(self, args, models, *, planner=None, local_player=None):
        self.args, self.models = args, models
        self.direct_jev = getattr(args, "controller", None) == "jev"
        self.route_atlas = RouteAtlas(args.binary, args.media) if getattr(args, "e1m1_guide", False) else None
        self.guide_display = None
        self.planner, self.local_backend = planner, local_player
        self.gemma_checks = None
        self.switchable = bool(getattr(args, "offer_layered", False))
        self.requested_local = local_player is not None and (
            not self.switchable or args.controller == "layered"
        )
        self.local_player = local_player if self.requested_local else None
        self.plan_pool = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="quake-strategy")
            if planner
            else None
        )
        self.plan_display = None
        self.active_directory = None
        pak = args.media / "id1/pak0.pak"
        self.health_hud = HealthHUD(pak) if pak.is_file() else None
        weights = getattr(args, "enemy_detector", None)
        self.characters = (
            GameCharacters(weights, getattr(args, "weapon_profile", None))
            if weights
            else None
        )
        scene_weights = getattr(args, "scene_model", None)
        self.scene_estimator = SceneEstimator(scene_weights) if scene_weights else None
        self.screen_enemy = None
        self.checkpoint_info = None
        self.skills = SkillBook(args.records)
        self.recordings = Recordings(args)
        self.finish_requested = False
        self.pause_epoch = 0
        self.inference = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="quake-inference"
        )
        self.cv = Condition()
        self.revision = 0
        self.run = time.time_ns() // 1000000
        self.resume = None
        self.scenario = "entrance"
        if args.resume_session:
            events = [
                json.loads(line)
                for line in (args.resume_session / "decisions.jsonl")
                .read_text()
                .splitlines()
            ]
            if not events or events[0]["observed_tick"] not in (24, 703):
                raise ValueError(
                    "The session needs a recognized start and at least one completed decision"
                )
            self.scenario = (
                "encounter" if events[0]["observed_tick"] == 703 else "entrance"
            )
            self.resume = (args.resume_session, events)
        self.auto = self.single = self.busy = self.ready = self.ended = self.closing = (
            False
        )
        self.phase = "Starting game"
        self.frame = ""
        self.tick = 0
        self.stats = {}
        self.current = None
        self.navigation_map = {}
        self.navigation_revision = 0
        self.history = deque(maxlen=80)
        self.error = ""
        self.worker = Thread(target=self.work, daemon=True)
        self.worker.start()

    def changed(self):
        self.revision += 1
        self.cv.notify_all()

    def command(self, op):
        with self.cv:
            if op in ("reset", "entrance", "encounter"):
                self.scenario = "encounter" if op == "encounter" else "entrance"
                self.run += 1
                self.resume = None
                self.finish_requested = False
                self.auto = self.single = self.ready = self.ended = False
                self.current, self.error, self.frame = None, "", ""
                self.tick, self.stats, self.phase = 0, {}, "Starting game"
                self.navigation_map = {}
                self.plan_display = self.active_directory = None
                self.guide_display = None
                if self.gemma_checks is not None:
                    self.gemma_checks = GemmaFrameChecks()
                self.navigation_revision += 1
                self.history.clear()
            elif op in ("gemma-text", "gemma-screenshots"):
                if not isinstance(self.local_backend, ModularGemmaPlayer) or not self.requested_local or self.ended or self.finish_requested:
                    return False
                enabled = op == "gemma-screenshots"
                if enabled != (self.gemma_checks is not None):
                    self.gemma_checks = GemmaFrameChecks() if enabled else None
                    self.pause_epoch += 1
            elif op in ("local-planner", "cloud-player"):
                if not self.switchable or self.ended or self.finish_requested:
                    return False
                requested = op == "local-planner"
                if requested != self.requested_local:
                    self.requested_local = requested
                    self.pause_epoch += 1
            elif op == "pause":
                self.pause_epoch += 1
                self.auto = self.single = False
            elif (
                op == "finish"
                and self.ready
                and not self.ended
                and (self.busy or self.history)
            ):
                self.finish_requested = True
                self.auto = self.single = False
            elif (
                op in ("play", "step")
                and self.ready
                and not self.ended
                and not self.finish_requested
            ):
                self.auto = op == "play"
                self.single = op == "step" and not self.busy
            else:
                return False
            self.changed()
            return True

    def snapshot(self, after):
        with self.cv:
            self.cv.wait_for(lambda: self.revision != after or self.closing, timeout=4)
            if self.revision == after:
                return None
            return {
                "revision": self.revision,
                "run": self.run,
                "scenario": self.scenario,
                "timing": "real-time",
                "goal": LEVEL_GOAL,
                "navigation_revision": self.navigation_revision,
                "phase": self.phase,
                "auto": self.auto,
                "busy": self.busy,
                "ready": self.ready,
                "ended": self.ended,
                "finishing": self.finish_requested,
                "tick": self.tick,
                "frame": self.frame,
                "screen_enemy": self.screen_enemy,
                "checkpoints": self.checkpoint_info,
                "planning": self.plan_display,
                "route_guide": self.guide_display,
                "route_stages": [stage[2] for stage in STAGES] if self.route_atlas else [],
                "player_modes": self.switchable,
                "gemma_input": ("gemma-screenshots" if self.gemma_checks is not None else "gemma-text")
                               if isinstance(self.local_backend, ModularGemmaPlayer) and self.requested_local else None,
                "requested_controller": "jev" if self.direct_jev else "layered"
                if self.requested_local
                else ("single-call" if self.models.single_call else "split")
                if hasattr(self.models, "single_call")
                else "split",
                "current": self.current,
                "stats": self.stats,
                "error": self.error,
                "history": [
                    {
                        k: v
                        for k, v in event.items()
                        if k not in ("frame", "planner_request", "plan")
                    }
                    for event in self.history
                ],
                "vision_model": getattr(self.models, "cloud_model", VISION_MODEL),
                "controller": "jev" if self.direct_jev else "layered"
                if self.local_player
                else "single-call"
                if getattr(self.models, "single_call", False)
                else "split",
                "layered_model": getattr(self.local_backend, "model", None),
                "decision_model": getattr(self.local_player, "model", LOCAL_MODEL)
                if self.local_player
                else getattr(self.models, "cloud_model", VISION_MODEL)
                if getattr(self.models, "single_call", False)
                else DECISION_MODEL,
            }

    def configure_controller(self, memory, directory, run, tick, past=None):
        self.local_player = self.local_backend if self.requested_local else None
        enabled = self.planner and (
            self.local_player
            or not self.switchable
            or getattr(self.args, "planner_model", None)
        )
        if enabled and not memory.plans:
            memory.plans = PlanFeed(self.planner, self.plan_pool, directory, past)
        elif not enabled and past and past.is_file():
            from shutil import copyfile

            copyfile(past, directory / "planner.jsonl")
        elif not enabled and memory.plans:
            memory.plans.invalidate("Cloud player selected.", tick)
            memory.plans = None
        self.update(run, plan_display=memory.plans.snapshot() if memory.plans else None)

    def publish_map(self, run, memory):
        with self.cv:
            if self.run == run:
                self.navigation_map = memory.diagram()
                self.navigation_revision += 1
                self.changed()

    def archived(self, run, seq):
        with self.cv:
            if run == self.run:
                return next((r.copy() for r in self.history if r["seq"] == seq), None)

    def update(self, run, **fields):
        with self.cv:
            if self.run != run or self.closing:
                return False
            for key, value in fields.items():
                setattr(self, key, value)
            self.changed()
            return True

    def publish_frame(self, run, game, jpg, state, character=None):
        fields = {"frame": base64.b64encode(jpg).decode(), "tick": game.tick}
        fields["screen_enemy"] = character
        if state:
            fields["stats"] = evaluator_stats(state)
        return self.update(run, **fields)

    def decision_cycle(
        self,
        run,
        game,
        jpg,
        state,
        trace,
        seq,
        recent,
        pause_epoch,
        deadline,
        memory,
        damage=None,
    ):
        """Only this thread advances Quake. Model I/O runs on a separate worker."""
        combined = getattr(self.models, "single_call", False)
        event = {
            "controller": "jev" if self.direct_jev else "layered"
            if self.local_player
            else "single-call"
            if combined
            else "split",
            "cloud_model": getattr(self.models, "cloud_model", VISION_MODEL),
            "inference_ms": None,
            "seq": seq,
            "timing": "real-time",
            "observed_tick": game.tick,
            "observed_stats": evaluator_stats(state),
            "vision": None,
            "vision_tick": None,
            "action": None,
            "applied_tick": None,
            "decision_tick": None,
            "reason": "",
            "vision_ms": None,
            "decision_ms": None,
            "note": "",
        }
        observed_rejection = (
            memory.character_track.last_rejection if memory.character_track else None
        )
        if self.local_player:
            event["decision_model"] = getattr(self.local_player, "model", LOCAL_MODEL)
        observed_jpeg = jpg
        gemma_checks = getattr(self, "gemma_checks", None)
        reference = view_signature(jpg)
        before_input = reference
        controls = (0, 0, 0)
        remaining = 0
        retry_at = None
        branch_yaw = 0
        passage = boundary = None
        submitted = time.monotonic()
        exploration = memory.exploration
        if exploration:
            travel = exploration.boundary_for(game)
            exploration.check(game.tick)
        else:
            travel = None
        if exploration:
            event["exploration"] = exploration.summary(game.tick)
        lessons = getattr(memory, "movement_lessons", None)
        guide = getattr(memory, "route_guide", None)
        route_hint = None
        if guide:
            route_hint = guide.observe(jpg, game.yaw, game.pitch)
            event["route_guide"] = route_hint
            self.update(run, guide_display=route_hint)
        following_guide = bool(route_hint and route_hint["suggested"])
        if following_guide:
            travel = None
        if lessons and getattr(self.args, "future_passages", False) and exploration:
            lessons.see_junction(game.tick, event["exploration"])
        plans = memory.plans
        offered = None
        if plans:
            plans.tick(game, jpg, memory)
            plans.request_if_needed(game, jpg, seq, memory, damage, recent)
            event["plan"] = dict(plans.active()) if plans.active() else None
            event["planner_request"] = (
                dict(plans.records[-1]) if plans.records else None
            )
            self.update(run, plan_display=plans.snapshot())
        hit = damage.take_pending() if damage else None
        if memory.lane_sense:
            memory.lane_sense.update(jpg, game.tick, game.yaw, game.pitch)
        lanes = (
            memory.lane_sense.current(game.tick, game.yaw, game.pitch)
            if memory.lane_sense
            else None
        )
        target = memory.character
        panel = memory.panels.eligible(game.tick, game.yaw) if memory.panels else None
        grounded = plans.ground(jpg, game) if plans else None
        same_fallen = bool(
            grounded
            and grounded["kind"] == "fallen_character"
            and target
            and abs(grounded["point"][0] - target["point"][0]) < 5
            and abs(grounded["point"][1] - target["point"][1]) < 5
        )
        tracking = (
            bool(target) and not same_fallen and not (damage and damage.ammo == 0)
        )
        last_sighting = game.tick
        survey = exploration.survey if exploration else None
        committed = survey.ready_probe(game.yaw, game.pitch) if survey and not route_hint else None
        preview = getattr(memory, "preview", None)
        stream = None
        option = None
        exit_move = None
        archive = getattr(preview, "archive", None)
        if archive:
            event["archive_search"] = archive.status()
            exit_move = archive.live_move(jpg, game.yaw, game.pitch, game.preview_source)
            if exit_move:
                _, witness = exit_move
                floor_hp = max(4, (witness.get("expected_health") or 12) - 8)
                if damage and damage.health is not None and damage.health < floor_hp:
                    exit_move = None
        if preview and not exit_move:
            if hit or tracking or not self.local_player:
                if preview.job and preview.job[2] == preview.generation:
                    preview.invalidate()
            elif self.local_player:
                active = plans.active() if plans else None
                option = preview.take(
                    jpg, game, (active or {}).get("intent", "explore"), grounded,
                    **({"departure": memory.checkpoints.departure_context()} if memory.checkpoints and getattr(self.args, "frontier_saves", False) else {}),
                )
        if self.direct_jev:
            # Request Jev's own input from its exact RGB frame. Game ticks continue
            # with neutral controls until the reply is fresh enough to apply.
            hit = tracking = None
            context = memory.guidance(None)
            if damage:
                context["hud"] = damage.context(game.tick)
            if memory.skill_book:
                context["past_traversal"] = memory.skill_book.hints()
            if plans and plans.active():
                offered = dict(plans.active())
                context["strategy"] = {k:offered.get(k) for k in ("objective","evidence","success","next_input")}
            event["navigation"] = context
            image = camera_image(jpg)
            (self.active_directory / "jev-frames" / f"{game.tick}.jpg").write_bytes(image)
            event["jev_frame_tick"] = game.tick
            source = None
            if self.health_hud and hasattr(game, "preview_source"):
                try:
                    source = game.preview_source()
                except RuntimeError:
                    pass
            submitted = time.monotonic()
            future = self.inference.submit(self.models.choose, image, recent, context, source, self.health_hud)
            phase = "Jev is reading the scene"
        elif exit_move:
            future = None
            option, witness = exit_move
            archive.applied(witness)
            rows = option.rows(game.yaw, game.pitch)
            stream = MotionStream(rows)
            remaining = sum(row[0] for row in rows)
            tracking = False
            if preview.job:
                preview.invalidate()
            event.update(action=option.kind, input_source="Visual frontier planner", visual_goal_move=witness,
                         applied_tick=game.tick, decision_tick=game.tick, locomotion_bearing=option.heading,
                         reason="The current camera matches a private, in-attempt view with a tested continuation to the exit screen.")
            phase = "Following visually confirmed exit"
        elif hit:
            future = None
            action = hit["action"]
            remaining = 36 if action == "evade_and_scan" else 32
            controls = (-280, 0, 0)
            event.update(
                action=action,
                input_source="HUD reflex",
                damage=hit,
                decision_tick=game.tick,
                applied_tick=game.tick,
                reason=f"Visible health dropped from {hit['from_hp']} to {hit['to_hp']}.",
            )
            memory.intention = (None, None)
            phase = "Evading hit"
            if tracking:
                event["tracking"] = []
                phase = "Retreating while tracking"
            previous = preview.receipt if preview else None
            if (
                not target
                and previous
                and game.tick - previous["selected_tick"] <= 2 * TICK_RATE
                and (previous.get("vertical_response") or {}).get("responds")
            ):
                rows = Option(game.yaw, "climb_out", 48, -18).rows(game.yaw, game.pitch)
                stream = MotionStream(rows)
                remaining = sum(r[0] for r in rows)
                event.update(
                    action="swim_to_surface",
                    reason=event["reason"]
                    + " A recent camera test showed that upward input moved the player.",
                )
                phase = "Swimming up after hit"
        elif tracking:
            future = None
            remaining = 24
            controls = (0, 0, 0)
            event.update(
                action="aim_fire",
                input_source="Local character detector",
                vision={
                    "scene": "A character is visible in the game camera.",
                    "enemy": target["point"],
                    "route": None,
                },
                vision_tick=game.tick,
                vision_ms=target["ms"],
                vision_detector=self.characters.name,
                decision_tick=game.tick,
                applied_tick=game.tick,
                reason="Tracking the visible character.",
                tracking=[],
            )
            phase = "Tracking character"
        elif preview and self.local_player:
            future = None
            lessons = getattr(memory, "movement_lessons", None)
            guidance = recovery = None
            if lessons:
                visible_hud = damage.context(game.tick) if damage else {}
                notice = visible_hud.get("game_message") if visible_hud.get("message_ticks_ago", 99999) <= 144 else None
                lessons.see_landing(game.tick, grounded, notice)
                guidance = lessons.context(game.tick)
                recovery = lessons.recovery(game.tick, game.yaw, (lanes or {}).get("pick"))
                if guidance:
                    event["movement_lesson"] = dict(guidance, mode=lessons.mode, recovery_heading=recovery)
            # Prefer a validated turn already offered by the search over a speculative reflex.
            new_direction = option is not None and (
                option.kind != "walk" or abs((option.heading - game.yaw + 180) % 360 - 180) >= 40
            )
            recovering = recovery is not None and lessons.mode == "active" and not new_direction
            chosen = option is not None and not recovering
            if recovering:
                preview.invalidate()
                option = Option(recovery, "clear_corner", 42)
            receipt = preview.last_offer
            if option is None:
                # Keep the game clock running when the first search is warming up.
                if lessons and lessons.mode == "active" and preview.handoff_pending(game.tick):
                    # World time and threat detection continue. Preserve the viewpoint on which the
                    # worker is evaluating moves until a short, visually checked handoff is ready.
                    option = Option(game.yaw, "watch_passage", 8, game.pitch)
                elif preview.job:
                    option = Option(game.yaw, duration=8, pitch=game.pitch)
                else:
                    direction = {"left": 36, "right": -36}.get(
                        (lanes or {}).get("pick"), 0
                    )
                    option = Option((game.yaw + direction) % 360)
            rows = option.rows(game.yaw, game.pitch)
            if lessons and lessons.mode == "active" and option.kind != "watch_passage" and not preview.job:
                rows.append((8, 0, 0, 0, rows[-1][4], rows[-1][5], 0))
            stream = MotionStream(rows)
            remaining = sum(r[0] for r in rows)
            if (
                memory.mechanisms.status == "verify_door"
                and game.tick > memory.mechanisms.return_by
            ):
                memory.mechanisms.status = "find_control"
            if not preview.job:
                preview.submit(
                    game,
                    rows,
                    plans.active() if plans else None,
                    memory.mechanisms.context(),
                    damage.context(game.tick) if damage else None,
                    **({"lesson": lessons.advice(game.tick)} if lessons and lessons.advice(game.tick) else {}),
                )
            event.update(
                action=option.kind,
                input_source="Movement lesson" if recovering else "Own-save lookahead" if chosen else "Camera navigation",
                applied_tick=game.tick,
                decision_tick=game.tick,
                lookahead=receipt or preview.last_offer,
                comparison_pending=bool(preview.job),
                locomotion_bearing=round(option.heading % 360, 2),
                reason=(
                    "Blocked-forward cue: back up and survey a different heading." if recovering else
                    f"{option.label()} ranked first among {len(receipt['alternatives'])} camera previews."
                    if chosen
                    else f"{option.label()} while the background search compares passages."
                ),
            )
            if chosen:
                guide = receipt.get("panorama_plan")
                event["vision"] = {
                    "scene": guide["evidence"]
                    if guide
                    else f"The live camera matched the expected view at tick {game.tick}.",
                    "enemy": None,
                    "route": None,
                    "landing": None,
                }
                event["vision_tick"] = game.tick
            phase = "Following tested passage" if chosen else "Comparing passages"
        elif (
            panel
            and not grounded
            and not (route_hint and route_hint["suggested"])
            and not (damage and damage.strafe_after_hit(game.tick))
        ):
            future = None
            mark = panel["point"]
            vision = {
                "scene": "A compact red marking remains visible inside a darker surround.",
                "panel": mark,
                "enemy": None,
                "route": None,
                "landing": None,
            }
            action = "inspect_panel"
            remaining, forward, side, buttons, yaw, pitch = game_input(
                action, vision, game.pitch
            )
            controls = forward, side, buttons
            game.yaw = (game.yaw + yaw) % 360
            game.pitch = max(-70, min(80, game.pitch + pitch))
            memory.panels.commit(game.tick)
            event.update(
                action=action,
                input_source="Landmark inspection",
                vision=vision,
                vision_tick=game.tick,
                applied_tick=game.tick,
                decision_tick=game.tick,
                mark=panel,
                reason="Approaching the visible panel and waiting briefly for a response.",
            )
            phase = "Testing marked surface"
        elif not following_guide and not grounded and memory.mechanisms.departure(game.tick):
            future = None
            remaining = 48
            controls = (280, 0, 0)
            event.update(
                action="leave_locked_door",
                input_source="Game message",
                applied_tick=game.tick,
                decision_tick=game.tick,
                reason=memory.mechanisms.context()["objective"],
                navigation=memory.guidance(None),
            )
            branch_yaw = 95 if not memory.mechanisms.tests % 2 else -95
            phase = "Leaving locked door"
        elif (
            not following_guide and not grounded
            and (return_sector := memory.mechanisms.direction(memory, game.tick))
            is not None
        ):
            future = None
            remaining = 32
            controls = (270, 0, 0)
            branch_yaw = (
                (memory.origin_yaw or 0) + 45 * return_sector - game.yaw + 180
            ) % 360 - 180
            event.update(
                action="return_to_door",
                input_source="Game message",
                applied_tick=game.tick,
                decision_tick=game.tick,
                reason="Following a remembered connection to check the previously locked door.",
                navigation=memory.guidance(None),
            )
            phase = "Checking door"
        elif (
            travel
            and not self.local_player
            and not (grounded and grounded["kind"] in MARK_ACTION)
        ):
            boundary = travel
            future = None
            remaining = 54
            boundary.begin(jpg)
            event.update(
                action="follow_boundary",
                input_source="Camera navigation",
                applied_tick=game.tick,
                decision_tick=game.tick,
                reason="Keep moving past familiar views and turn when the camera shows little forward travel.",
            )
            phase = "Following boundary"
        elif (
            committed
            and not travel
            and not (damage and damage.strafe_after_hit(game.tick))
        ):
            future = None
            passage = survey
            passage.begin(jpg)
            remaining = 54 if committed == "test_ledge" else 42
            event.update(
                action=committed,
                input_source="Navigation recovery",
                decision_tick=game.tick,
                applied_tick=game.tick,
                navigation=memory.guidance(None),
                reason="Turn complete. Testing the selected passage before choosing another direction.",
            )
            phase = "Testing passage"
        elif combined:
            event["navigation"] = memory.guidance(None)
            if memory.skill_book:
                event["navigation"]["past_traversal"] = memory.skill_book.hints()
            if lanes:
                event["camera_lanes"] = lanes
                event["navigation"]["camera_lanes"] = lanes["pick"]
            if grounded:
                event["grounded"] = grounded
                event["navigation"]["grounded"] = grounded
            if target and not same_fallen:
                event["navigation"]["local_character"] = target["point"]
            if damage:
                event["navigation"]["hud"] = damage.context(game.tick)
            if plans and plans.active():
                offered = dict(plans.active())
                event["navigation"]["strategy"] = {
                    k: offered.get(k)
                    for k in (
                        "id",
                        "objective",
                        "evidence",
                        "success",
                        "next_input",
                        "intent",
                        "character",
                    )
                }
            if self.local_player:
                event["vision"] = {
                    "scene": (
                        "A character silhouette is visible in the game frame."
                        if target
                        else "No character lock in this frame. "
                        + str(memory.last_outcome)
                    ),
                    "enemy": target["point"] if target and not same_fallen else None,
                    "route": None,
                    "landing": None,
                }
                if lanes:
                    event["vision"]["route"] = lanes.get("point")
                    event["vision"]["scene"] = (
                        "The camera shows little clearance within the forward view."
                        if lanes["pick"] == "scan"
                        else f"The RGB scene model estimates the {lanes['pick']} lane has the most clearance."
                    )
                    event["vision_ms"] = lanes["ms"]
                ground_vision(event["vision"], grounded)
                navigation = event["navigation"]
                if route_hint:
                    navigation["prepared_route"] = route_hint
                    if route_hint.get("route") or route_hint.get("landing"):
                        for field in ("route", "landing"):
                            event["vision"][field] = route_hint.get(field)
                    if route_hint.get("landing"):
                        event["vision"]["clearance"] = "jump_up"
                    if route_hint.get("suggested") == "ride_lift":
                        event["vision"]["blocker"] = "moving_platform"
                    if route_hint["suggested"]:
                        event["vision"]["scene"] = route_hint["objective"]
                # A centered marker can still point at the same failed approach.
                # Resolve the actual route bearing before Laya sees its choices.
                navigation.update(memory.guidance(event["vision"].get("route"), event["vision"].get("landing")))
                if navigation.get("movement_lesson"):
                    event["movement_lesson"] = navigation["movement_lesson"]
                    if memory.skill_book:
                        navigation["past_traversal"] = (
                            memory.skill_book.hints("stalled_forward") or navigation.get("past_traversal", [])
                        )
                if grounded and not (route_hint and route_hint["suggested"]):
                    event["vision"]["scene"] = (
                        f"Matched the planner's {grounded['kind'].replace('_', ' ')} in the current frame."
                    )
                event["vision_tick"] = game.tick
                frame_reason = None
                if gemma_checks is not None and isinstance(self.local_player, ModularGemmaPlayer) and not target:
                    frame_reason = gemma_checks.request(game.tick, navigation.get("hud", {}).get("hit_ticks_ago"))
                if frame_reason:
                    event["gemma_frame_reason"] = frame_reason
                    future = self.inference.submit(self.local_player.choose_with_frame, recent, navigation, jpg)
                else:
                    future = self.inference.submit(self.local_player.choose, recent, navigation)
                phase = "Choosing game input"
            else:
                future = self.inference.submit(
                    self.models.observe_and_choose, jpg, recent, event["navigation"]
                )
                phase = "Reading frame and choosing input"
        else:
            future = self.inference.submit(self.models.observe, jpg)
            phase = "Reading frame"
        self.update(run, busy=True, phase=phase, current=event.copy(), error="")
        try:
            while True:
                with self.cv:
                    if (
                        self.closing
                        or self.run != run
                        or self.finish_requested
                        or self.pause_epoch != pause_epoch
                    ):
                        event["note"] = "Run interrupted"
                        break

                if plans:
                    plans.tick(game, jpg, memory)
                if future is not None and future.done():
                    try:
                        result = future.result()
                        now = time.monotonic()
                        ms = round((now - submitted) * 1000)
                        if self.local_player:
                            if event.get("gemma_frame_reason"):
                                result, event["gemma_sighting"] = result
                            local_action, local_cue, local_source, local_ms = result
                            event["actor_ms"] = local_ms
                            event["actor_choice"] = local_action
                            event["actor_source"] = local_source
                            result = (event["vision"], (local_action, local_cue))
                        if combined or phase == "Reading frame":
                            vision = result[0] if combined else result
                            point = vision.get("enemy")
                            if (
                                point
                                and observed_rejection
                                and observed_rejection["tick"] == event["observed_tick"]
                                and abs(point[0] - observed_rejection["point"][0]) < 5
                                and abs(point[1] - observed_rejection["point"][1]) < 5
                            ):
                                event["withheld_enemy"] = dict(
                                    observed_rejection, cloud_point=point
                                )
                                vision = dict(vision, enemy=None)
                            event.update(vision=vision, vision_tick=game.tick)
                            event["remembered_scene"] = (
                                not self.local_player
                                and visual_change(reference, jpg) < 8
                                and memory.describe(vision["scene"])
                            )
                            if event["remembered_scene"]:
                                memory.remember_passages(vision)
                            context = memory.guidance(
                                vision["route"], vision.get("landing")
                            )
                            if route_hint:
                                context["prepared_route"] = route_hint
                            if memory.skill_book and not combined:
                                context["past_traversal"] = memory.skill_book.hints(
                                    vision.get("clearance")
                                )
                            if damage:
                                damage.see_enemy(
                                    vision.get("enemy"), event["observed_tick"]
                                )
                                context["hud"] = damage.context(game.tick)
                            self.publish_map(run, memory)
                        if not combined and phase == "Reading frame":
                            if plans and plans.active():
                                offered = dict(plans.active())
                                context["strategy"] = {
                                    k: offered.get(k)
                                    for k in (
                                        "id",
                                        "objective",
                                        "evidence",
                                        "success",
                                        "next_input",
                                        "intent",
                                        "character",
                                    )
                                }
                            event.update(vision_ms=ms, navigation=context)
                            submitted = now
                            future = self.inference.submit(
                                self.models.decide, vision, recent, context
                            )
                            phase = "Choosing action"
                        else:
                            future = None
                            if combined:
                                event[
                                    "decision_ms"
                                    if self.local_player
                                    else "inference_ms"
                                ] = ms
                                if self.direct_jev:
                                    action, reason = result[1]
                                    source = "TypeSafe Jev"
                                    event["jev"] = vision["jev"]
                                else:
                                    action, reason, source = resolve_proposal(
                                        result[1], vision, recent, context
                                    )
                                event["input_source"] = (
                                    local_source
                                    if self.local_player and source == "model"
                                    else source
                                )
                                if source == "local recovery":
                                    event["proposed"] = list(result[1])
                            else:
                                event["decision_ms"] = ms
                                action, reason = result
                            supply = (
                                vision.get("pickup")
                                and damage
                                and (
                                    vision.get("item") == "health"
                                    and damage.health is not None
                                    and damage.health <= 45
                                    or vision.get("item") == "ammo"
                                    and damage.ammo is not None
                                    and damage.ammo <= 3
                                )
                            )
                            if supply and not vision.get("enemy"):
                                event["model_action"] = action
                                action, reason = (
                                    "collect_item",
                                    "Approaching a visible supply needed by the current HUD.",
                                )
                                event["input_source"] = "HUD pickup"
                            elif (
                                damage
                                and damage.ammo == 0
                                and vision.get("enemy")
                                and action in ("aim_fire", "fire", "advance_fire")
                            ):
                                event["model_action"] = action
                                action, reason = (
                                    "bypass_enemy",
                                    "The active ammunition display reads zero.",
                                )
                                event["input_source"] = "HUD reflex"
                            elif (
                                grounded
                                and not (following_guide and route_hint["suggested"] == action)
                                and grounded["kind"] in MARK_ACTION
                                and action == MARK_ACTION[grounded["kind"]][1]
                            ):
                                if not plans.ground(jpg, game):
                                    event["note"] = "Landmark left the current view"
                                    break
                            elif (
                                travel
                                and self.local_player
                                and action
                                not in ("collect_item", "bypass_enemy", "aim_fire")
                            ):
                                event["model_action"] = action
                                if action in (
                                    "advance",
                                    "follow_route",
                                    "turn_left",
                                    "turn_right",
                                ) and travel.use_lane(lanes, game):
                                    event["steering_lane"] = lanes["pick"]
                                if (
                                    action == "follow_route"
                                    and lanes
                                    and lanes["pick"] in ("left", "right")
                                ):
                                    travel.preference = (
                                        1 if lanes["pick"] == "left" else -1
                                    )
                                if action in ("turn_left", "turn_right"):
                                    travel.preference = (
                                        1 if action == "turn_left" else -1
                                    )
                                action, reason = (
                                    "follow_boundary",
                                    "Continue forward and use the local player's turn preference when the camera indicates an obstruction.",
                                )
                                event["input_source"] = "Camera navigation"
                            elif not self.direct_jev and not (route_hint and route_hint["suggested"]) and exploration and not (
                                damage and damage.strafe_after_hit(game.tick)
                            ):
                                recovery = exploration.choose(game, memory, vision, jpg)
                                if recovery:
                                    event["model_action"] = action
                                    action, branch_yaw, reason = recovery
                                    event["input_source"] = "Navigation recovery"
                                    event["exploration"] = exploration.summary(
                                        game.tick
                                    )
                            inspect = (
                                memory.checkpoints.inspect(memory, action)
                                if memory.checkpoints and not self.direct_jev
                                else None
                            )
                            if inspect:
                                action, reason = (
                                    inspect,
                                    "Inspect a different departure after the previous attempt ended.",
                                )
                                event.update(
                                    checkpoint_inspection=True,
                                    input_source="Checkpoint memory",
                                )
                            event.update(
                                action=action, reason=reason, decision_tick=game.tick
                            )
                            change = visual_change(reference, jpg)
                            # A flickering static ledge can produce two familiar views.
                            # Keep the age limit even if both images match this place and facing.
                            positional_input = (
                                action == "jump_forward"
                                and event["vision"].get("landing") is not None
                            ) or (
                                action
                                in (
                                    "back_up",
                                    "strafe_left",
                                    "strafe_right",
                                    "turn_around",
                                    "level_view",
                                )
                                and event["navigation"]["recover"]
                            )
                            if (
                                change >= 12
                                and positional_input
                                and memory.same_known_view(observed_jpeg, jpg)
                            ):
                                change = 0
                            if expired_action(
                                action, game.tick - event["observed_tick"], change
                            ):
                                event["note"] = "Expired"
                                break
                            if self.direct_jev and action == "hold":
                                remaining, forward, side, buttons, yaw, pitch = 8, 0, 0, 0, 0, 0
                            elif self.direct_jev and action == "jump_forward":
                                heading = (game.yaw + JUMP_TURN[event["jev"]["proposed"]]) % 360
                                rows = Option(heading, "jump", 72).rows(game.yaw, game.pitch)
                                stream = MotionStream(rows)
                                remaining, forward, side, buttons, yaw, pitch = sum(row[0] for row in rows), 0, 0, 0, 0, 0
                            elif action == "follow_boundary":
                                boundary = travel
                                boundary.begin(jpg)
                                remaining, forward, side, buttons, yaw, pitch = (
                                    54,
                                    0,
                                    0,
                                    0,
                                    0,
                                    0,
                                )
                            elif action in PROBES:
                                passage = exploration.survey
                                passage.begin(jpg)
                                remaining = 54 if action == "test_ledge" else 42
                                forward, side, buttons, yaw, pitch = 0, 0, 0, 0, 0
                            elif action == "branch_turn":
                                remaining, forward, side, buttons, yaw, pitch = (
                                    16,
                                    0,
                                    0,
                                    0,
                                    0,
                                    -game.pitch,
                                )
                            else:
                                remaining, forward, side, buttons, yaw, pitch = (
                                    game_input(action, event["vision"], game.pitch)
                                )
                            memory.intention = (
                                ("stalled_forward" if event["navigation"].get("movement_lesson") else
                                 event["vision"].get("clearance") or "unclear")
                                if self.local_player else event["vision"].get("clearance"),
                                action,
                            )
                            controls = (forward, side, buttons)
                            before_input = view_signature(jpg)
                            game.yaw = (game.yaw + yaw) % 360
                            game.pitch = max(-70, min(80, game.pitch + pitch))
                            event["applied_tick"] = game.tick
                            if (gemma_checks is not None and (event.get("gemma_sighting") or {}).get("sighting") == "live"
                                    and action in ("turn_left", "turn_right") and event.get("input_source") == "Modular Gemma"):
                                gemma_checks.confirm = True
                            if guide and action == "wait_door":
                                guide.door_waited = True
                            if (
                                plans
                                and grounded
                                and grounded["kind"] in MARK_ACTION
                                and action == MARK_ACTION[grounded["kind"]][1]
                                and grounded["kind"] not in ("passage", "landing")
                            ):
                                plans.landmark_attempt(grounded, game.tick)
                            if plans and offered:
                                plans.receipt(
                                    offered["id"],
                                    seq,
                                    game.tick,
                                    action,
                                    event.get("input_source", "model"),
                                )
                                event["plan_use"] = (
                                    "Model received objective"
                                    if event.get("input_source")
                                    in ("model", "Mac local model", "Modular Gemma", "TypeSafe Jev")
                                    else "Local control took priority"
                                )
                                event["plan"] = (
                                    dict(plans.active()) if plans.active() else None
                                )
                            phase = "Applying input"
                        self.update(run, phase=phase, current=event.copy())
                    except (ValueError, LookupError, TypeError, httpx.HTTPError) as exc:
                        future = None
                        event["note"] = "Inference failed"
                        self.update(
                            run,
                            phase="Waiting to retry",
                            error=str(exc) or type(exc).__name__,
                            current=event.copy(),
                        )
                        # Retry on a fresh frame. Keep the clock moving during backoff.
                        retry_at = time.monotonic() + 1
                if retry_at is not None and time.monotonic() >= retry_at:
                    break

                up = 0
                if stream:
                    chunk, forward, side, up, game.yaw, game.pitch, buttons = (
                        stream.next(FRAME_TICKS)
                    )
                    keys = (forward, side, buttons)
                elif passage:
                    chunk, keys = survey_keys(event["action"], remaining, FRAME_TICKS)
                else:
                    chunk, keys = input_chunk(
                        event["action"], remaining, controls, FRAME_TICKS
                    )
                if (
                    remaining
                    and event["action"] == "evade_and_scan"
                    and remaining <= 8
                    and "scan_tick" not in event
                ):
                    game.yaw = (game.yaw + 180) % 360
                    game.pitch = 0
                    event["scan_tick"] = game.tick + 1
                if remaining and event["action"] in (
                    "jump_forward",
                    "jump_back",
                    "evade_and_scan",
                ):
                    if keys[2] & 2:
                        event.setdefault("jump_press_tick", game.tick + 1)
                        jump_phase = (
                            "Jump + forward"
                            if event["action"] == "jump_forward"
                            else "Jumping back"
                        )
                    elif "jump_press_tick" in event:
                        event.setdefault("jump_release_tick", game.tick + 1)
                        jump_phase = (
                            "Holding forward"
                            if event["action"] == "jump_forward"
                            else (
                                "Checking behind"
                                if "scan_tick" in event
                                else "Retreating"
                            )
                        )
                    else:
                        jump_phase = (
                            "Running up"
                            if event["action"] == "jump_forward"
                            else "Backing away"
                        )
                    if phase != jump_phase:
                        phase = jump_phase
                        self.update(run, phase=phase, current=event.copy())
                if (
                    event["action"] in ("leave_locked_door", "return_to_door")
                    and remaining
                ):
                    total = 48 if event["action"] == "leave_locked_door" else 32
                    if total - remaining < 12:
                        game.yaw = (game.yaw + branch_yaw * chunk / 12) % 360
                        keys = (-160 if total == 48 else 0, 0, 0)
                if event["action"] == "branch_turn" and remaining:
                    game.yaw = (game.yaw + branch_yaw * chunk / 16) % 360
                if boundary:
                    keys = boundary.controls(game, chunk)
                if travel and future is not None and not hit:
                    if travel.previous is None:
                        travel.begin(jpg)
                    keys = travel.controls(game, chunk)
                    event.setdefault("interim_movement_tick", game.tick)
                if tracking:
                    target = memory.character
                    forward, side = combat_motion(
                        target,
                        damage.health if damage else None,
                        game.tick,
                        retreat=bool(hit),
                    )
                    jump_button = keys[2] & 2 if hit else 0
                    if target is None:
                        if (
                            memory.character_track
                            and memory.character_track.last_rejection
                        ):
                            event["note"] = "Released an unresponsive silhouette"
                            break
                        if game.tick - last_sighting > 16:
                            event["note"] = "Character left the detector view"
                            break
                        keys = (forward, side, jump_button)
                        event["reacquisition_ticks"] = (
                            event.get("reacquisition_ticks", 0) + chunk
                        )
                    else:
                        last_sighting = game.tick
                        yaw, pitch, fire = track_character(target["point"])
                        game.yaw = (game.yaw + yaw) % 360
                        game.pitch = max(-70, min(80, game.pitch + pitch))
                        keys = (forward, side, fire | jump_button)
                        event["tracking"].append(
                            dict(
                                target,
                                tick=game.tick,
                                firing=bool(fire),
                                side=side,
                                forward=forward,
                            )
                        )
                elif damage and not hit and not self.direct_jev:
                    side = damage.strafe_after_hit(game.tick)
                    if side and (
                        future is not None or event["action"] in ("fire", "aim_fire")
                    ):
                        keys = (keys[0], side, keys[2])
                        if "dodge_tick" not in event:
                            event["dodge_tick"] = game.tick
                            if future is not None:
                                self.update(
                                    run,
                                    phase="Dodging during inference",
                                    current=event.copy(),
                                )
                jpg, state, row = game.move(
                    chunk, *keys, evaluate=True, **({"up": up} if up else {})
                )
                print(row, file=trace)
                lessons = getattr(memory, "movement_lessons", None)
                ordinary_walk = event["action"] in ("walk", "explore_lane", "advance", "follow_route")
                if lessons:
                    location = (memory.here, sector(game.yaw - (memory.origin_yaw or 0)))
                    lessons.observe(jpg, game.tick, chunk, game.yaw, game.pitch, keys[0], keys[1], up, keys[2], ordinary_walk, location)
                if passage:
                    passage.sample(jpg)
                if boundary:
                    boundary.sample(jpg, chunk)
                elif travel and future is not None and not hit:
                    travel.sample(jpg, chunk)
                memory.track(jpg, game.tick, game.yaw, game.pitch, *keys)
                if memory.lane_sense:
                    memory.lane_sense.update(jpg, game.tick, game.yaw, game.pitch)
                if memory.panels:
                    memory.panels.observe(jpg, game.tick, game.yaw, game.pitch)
                if memory.character_track:
                    memory.character = memory.character_track.read(
                        jpg,
                        game.tick,
                        game.yaw,
                        game.pitch,
                        fired=bool(keys[2] & 1),
                        ammo=damage.ammo if damage else None,
                    )
                    if memory.character_track.last_rejection:
                        event["released_target"] = memory.character_track.last_rejection
                    if damage and memory.character:
                        damage.see_enemy(memory.character["point"], game.tick)
                if (
                    plans
                    and (self.plan_display or {}).get("revision") != plans.revision
                ):
                    self.update(run, plan_display=plans.snapshot())
                self.publish_frame(run, game, jpg, state, memory.character)
                deadline += chunk / TICK_RATE
                now = time.monotonic()
                if now - deadline > 3:  # Re-anchor after machine sleep.
                    deadline = now
                time.sleep(max(0, deadline - now))
                if (screen_outcome(jpg, self.health_hud) if self.health_hud else terminal_phase(state, 0, None)):
                    if event["applied_tick"] is None:
                        event["note"] = "Game ended before input"
                    break
                if damage:
                    damage.watch(jpg, game.tick)
                    if damage.notice and damage.notice_tick == game.tick:
                        evidence = {
                            "text": damage.notice,
                            "tick": game.tick,
                            "place": memory.here,
                            "heading": round(memory.yaw / 45) % 8,
                            "landmark": memory.places[memory.here].landmark,
                        }
                        if memory.mechanisms.see_notice(**evidence):
                            if preview:
                                preview.door_node = preview.book.graph.current
                            event.setdefault("door_notices", []).append(evidence)
                    if damage.pending and not hit and (not self.direct_jev or event["applied_tick"] is not None) and (not exit_move or damage.health is not None and damage.health < floor_hp):
                        event["note"] = "Interrupted by visible health loss"
                        break
                if (
                    memory.character
                    and not exit_move
                    and not (
                        same_fallen
                        and abs(memory.character["point"][0] - grounded["point"][0]) < 5
                        and abs(memory.character["point"][1] - grounded["point"][1]) < 5
                    )
                    and not (damage and damage.ammo == 0)
                    and not tracking
                    and not hit
                    and (event["action"] != "jump_forward" or remaining <= 12)
                ):
                    event["note"] = "Visible character acquired"
                    break
                if (
                    boundary
                    and memory.panels
                    and memory.panels.eligible(game.tick, game.yaw)
                ):
                    event["note"] = "New visual marking"
                    break
                if lessons and ordinary_walk and not exit_move and remaining > 16 and lessons.recovery_due(game.tick):
                    event["note"] = "Released blocked forward input after sustained visual stall"
                    if not event.get("movement_lesson"):
                        event["movement_lesson"] = dict(lessons.context(game.tick), mode=lessons.mode)
                    break
                if remaining:
                    remaining -= chunk
                    if not remaining:
                        break
        finally:
            if future is not None:
                future.cancel()
        if stream and remaining and preview:
            preview.invalidate()
            event["lookahead_interrupted"] = (
                event.get("note") or "Live input interrupted"
            )
        if plans and plans.records:
            event["planner_request"] = dict(plans.records[-1])
        if boundary:
            event["boundary_travel"] = boundary.snapshot()
        if passage:
            event["passage_test"] = passage.finish(completed=remaining == 0)
        event.update(
            end_tick=game.tick,
            ticks=game.tick - event["applied_tick"]
            if event["applied_tick"] is not None
            else 0,
            view_change_pct=visual_change(before_input, jpg),
        )
        if preview:
            preview.record_input(event)
        memory.mechanisms.tested(event, game.tick)
        if memory.mechanisms.door:
            event["mechanism"] = memory.mechanisms.context()
        self.publish_map(run, memory)
        return event, jpg, state, deadline

    def checkpoint_cycle(
        self, run, game, jpg, state, trace, seq, deadline, memory, damage, op, directory
    ):
        start = game.tick
        before = evaluator_stats(state)
        loading = op["op"] == "load"
        event = {
            "controller": "checkpoint",
            "seq": seq,
            "timing": "real-time",
            "action": "load_checkpoint" if loading else "save_checkpoint",
            "input_source": "Quake checkpoint",
            "observed_tick": start,
            "observed_stats": before,
            "decision_tick": start,
            "applied_tick": start,
            "vision": None,
            "vision_tick": None,
            "vision_ms": None,
            "decision_ms": None,
            "inference_ms": None,
            "note": "",
            "reason": (
                f"Restoring checkpoint {op['slot']} after {op.get('cause', 'death')}."
                if loading
                else f"Saving a position reached during this run at P{op['place'] + 1}."
            ),
        }
        self.update(
            run,
            busy=True,
            phase="Loading checkpoint" if loading else "Saving checkpoint",
            current=event.copy(),
            error="",
        )
        if memory.plans and memory.plans.records:
            event["plan"] = memory.plans.active()
            event["planner_request"] = dict(memory.plans.records[-1])
        op = dict(op, **checkpoint_operation(game, op))
        if getattr(memory, "route_guide", None):
            memory.route_guide.checkpoint(op["slot"], loading)
        if not loading:
            game.archive_checkpoint(op["slot"], directory / "saves")
        jpg, state, row = game.move(4, evaluate=True)
        print(row, file=trace)
        if loading:
            with self.cv:
                if self.run == run and self.gemma_checks is not None:
                    self.gemma_checks = GemmaFrameChecks()
            if getattr(memory, "movement_lessons", None):
                memory.movement_lessons.reset()
            relocate(memory, memory.checkpoints.saved[op["slot"]], jpg, game)
        else:
            memory.track(jpg, game.tick, game.yaw, game.pitch)
        if damage:
            damage.watch(jpg, game.tick)
        if memory.character_track:
            memory.character = memory.character_track.read(
                jpg, game.tick, game.yaw, game.pitch
            )
        memory.checkpoints.record(op, game.tick)
        if getattr(memory, "preview", None):
            memory.preview.checkpoint(op, game, jpg)
        event.update(
            checkpoint=op,
            end_tick=game.tick,
            ticks=game.tick - start,
            view_change_pct=0,
            checkpoint_context=memory.checkpoints.context(),
        )
        self.update(run, checkpoint_info=event["checkpoint_context"])
        self.publish_frame(run, game, jpg, state, memory.character)
        self.publish_map(run, memory)
        deadline += 4 / TICK_RATE
        time.sleep(max(0, deadline - time.monotonic()))
        return event, jpg, state, max(deadline, time.monotonic())

    def session(self, run, scenario, resume):
        record_result = "Session stopped"
        can_record = False
        game = Game(
            self.args.binary,
            self.args.media,
            self.args.gpu,
            start_map="start" if scenario == "encounter" else "e1m1",
        )
        try:
            directory = Path(tempfile.mkdtemp(prefix="session-", dir=self.args.records))
            if getattr(self.args, "movement_lessons", "off") != "off" or self.route_atlas:
                protocol = {
                    "scenario": scenario, "resume_session": bool(resume),
                    "controller": self.args.controller, "own_save_lookahead": self.args.own_save_lookahead,
                    "movement_lessons": self.args.movement_lessons,
                    "future_passages": getattr(self.args, "future_passages", False),
                    "frontier_saves": getattr(self.args, "frontier_saves", False),
                    "archive_search": getattr(self.args, "archive_search", False),
                    "visual_outcomes": self.health_hud is not None,
                    "planner_model": getattr(self.planner, "cloud_model", None),
                    "local_model": LOCAL_MODEL if isinstance(self.local_player, LocalPlayer) else None,
                    "decision_model": getattr(self.local_player, "model", None),
                    "prepared_e1m1_route": self.route_atlas is not None,
                }
                (directory / "attempt.json").write_text(json.dumps(protocol, indent=2))
            captured = directory / "frames"
            captured.mkdir()
            if self.direct_jev:
                (directory / "jev-frames").mkdir()
            with (
                (directory / "inputs.trace").open("w", buffering=1) as trace,
                (directory / "decisions.jsonl").open("w", buffering=1) as log,
            ):
                count = 0
                memory = RouteMemory()
                memory.route_guide = RouteGuide(self.route_atlas) if self.route_atlas else None
                memory.movement_lessons = MovementLessons(getattr(self.args, "movement_lessons", "off"))
                memory.preview = (
                    PreviewSearch(
                        self.health_hud,
                        directory,
                        self.planner,
                        self.local_backend,
                        self.scene_estimator,
                        future_passages=getattr(self.args, "future_passages", False),
                        archive_search=getattr(self.args, "archive_search", False),
                    )
                    if getattr(self.args, "own_save_lookahead", False)
                    and self.health_hud
                    else None
                )
                memory.lane_sense = (
                    LaneSense(self.scene_estimator) if self.scene_estimator else None
                )
                memory.panels = PanelScout(
                    self.characters.weapon_poses if self.characters else None
                )
                book = (
                    Checkpoints(explore_frontiers=getattr(self.args, "frontier_saves", False)) if getattr(self.args, "checkpoints", False) else None
                )
                if book and "native_save" not in game.pipe.capabilities:
                    raise RuntimeError(
                        "Rebuild the native game to enable agent checkpoints"
                    )
                memory.checkpoints = book
                self.configure_controller(
                    memory,
                    directory,
                    run,
                    game.tick,
                    resume[0] / "planner.jsonl" if resume else None,
                )
                self.update(
                    run,
                    active_directory=directory,
                    plan_display=memory.plans.snapshot() if memory.plans else None,
                )
                if self.characters:
                    memory.character_track = CharacterTrack(self.characters)
                memory.exploration = Exploration()
                memory.exploration.continuous = getattr(
                    self.args, "continuous_travel", False
                )
                if resume:
                    jpg, state, history = restore_session(
                        game, *resume, trace, log, captured, memory
                    )
                    count = history[-1]["seq"]
                    if not self.update(
                        run,
                        history=history,
                        current={k: v for k, v in history[-1].items() if k != "frame"},
                    ):
                        return
                else:
                    jpg, state = prepare_start(game, scenario, trace)
                    memory.track(jpg, game.tick, game.yaw, game.pitch)
                memory.skill_book = self.skills
                if memory.route_guide:
                    self.update(run, guide_display=memory.route_guide.observe(jpg, game.yaw, game.pitch))
                self.publish_map(run, memory)
                can_record = True
                damage = DamageSense(self.health_hud) if self.health_hud else None
                if damage:
                    damage.watch(jpg, game.tick)
                if memory.character_track:
                    memory.character = memory.character_track.read(
                        jpg, game.tick, game.yaw, game.pitch
                    )
                self.publish_frame(run, game, jpg, state, memory.character)
                outcome = (screen_outcome(jpg, self.health_hud, count, self.args.limit, book) if self.health_hud else session_outcome(state, count, self.args.limit, book))
                self.update(
                    run,
                    ready=True,
                    busy=False,
                    ended=outcome is not None,
                    phase=outcome or "Ready",
                    checkpoint_info=book.context() if book else None,
                )
                if outcome:
                    record_result = outcome
                    return
                deadline = time.monotonic()
                while True:
                    with self.cv:
                        if not self.auto:
                            self.cv.wait_for(
                                lambda: (
                                    self.closing
                                    or run != self.run
                                    or self.auto
                                    or self.single
                                    or self.finish_requested
                                )
                            )
                            deadline = time.monotonic()
                        if self.closing or run != self.run:
                            record_result = (
                                "Session stopped" if self.closing else "Restarted"
                            )
                            return
                        if self.finish_requested:
                            record_result = "Finished by player"
                            self.update(
                                run,
                                ended=True,
                                busy=False,
                                finish_requested=False,
                                phase="Run finished",
                            )
                            return
                        self.single = False
                        pause_epoch = self.pause_epoch
                        input_frame = self.frame
                        recent = recent_context(self.history)
                    observed_image = jpg
                    if self.requested_local != bool(self.local_player):
                        self.configure_controller(memory, directory, run, game.tick)
                    visible_hp = self.health_hud.read(jpg) if self.health_hud and book else None
                    op = (
                        book.propose(
                            game.tick,
                            (visible_hp is not None and visible_hp <= 0),
                            memory,
                            damage,
                            memory.character,
                        )
                        if book
                        else None
                    )
                    archive = getattr(getattr(memory, "preview", None), "archive", None)
                    if book and archive and archive.win:
                        requested = archive.root_request(game.tick, book.saved)
                        if requested is not None:
                            op = {"op":"load", "slot":requested, "failed_slot":book.active,
                                  "cause":"visual exit forecast", "seconds_since_checkpoint":round((game.tick-book.last_operation)/72,1)}
                        elif op and op["op"] == "save":
                            op = None
                    if op:
                        if op["op"] == "load" and memory.plans:
                            memory.plans.invalidate(
                                "Checkpoint restored. A fresh observation is required.",
                                game.tick,
                            )
                            self.update(run, plan_display=memory.plans.snapshot())
                        if op["op"] == "load" and self.health_hud:
                            damage = DamageSense(self.health_hud)
                        event, jpg, state, deadline = self.checkpoint_cycle(
                            run,
                            game,
                            jpg,
                            state,
                            trace,
                            count + 1,
                            deadline,
                            memory,
                            damage,
                            op,
                            directory,
                        )
                    else:
                        event, jpg, state, deadline = self.decision_cycle(
                            run,
                            game,
                            jpg,
                            state,
                            trace,
                            count + 1,
                            recent,
                            pause_epoch,
                            deadline,
                            memory,
                            damage,
                        )
                        if book:
                            book.observe_action(event, memory.yaw)
                    if event["end_tick"] != event["observed_tick"]:
                        count += 1
                        (captured / f"{event['observed_tick']}.jpg").write_bytes(
                            observed_image
                        )
                        metrics = evaluator_stats(state)
                        print(json.dumps(dict(event, evaluator=metrics)), file=log)
                    with self.cv:
                        if self.closing or run != self.run:
                            return
                        if event["end_tick"] != event["observed_tick"]:
                            self.history.append(dict(event, frame=input_frame))
                            self.current = event.copy()
                        self.busy = False
                        outcome = (screen_outcome(jpg, self.health_hud, count, self.args.limit, book) if self.health_hud else session_outcome(state, count, self.args.limit, book))
                        self.ended = outcome is not None
                        if self.ended:
                            self.auto = self.single = self.finish_requested = False
                        self.phase = outcome or "Ready"
                        self.changed()
                        if outcome:
                            record_result = outcome
                            return
        finally:
            try:
                if can_record and memory.preview:
                    memory.preview.close()
                if can_record and memory.lane_sense:
                    memory.lane_sense.close()
                if can_record and memory.plans:
                    memory.plans.invalidate("Run ended.", game.tick)
                    self.update(run, plan_display=memory.plans.snapshot())
                if can_record and (directory / "decisions.jsonl").stat().st_size:
                    if run != self.run:
                        record_result = "Restarted"
                    self.recordings.submit(
                        directory, scenario, record_result, self.args.gpu
                    )
            finally:
                game.close()

    def work(self):
        while not self.closing:
            with self.cv:
                run, scenario = self.run, self.scenario
                resume, self.resume = self.resume, None
            try:
                self.session(run, scenario, resume)
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as exc:
                self.update(
                    run,
                    auto=False,
                    single=False,
                    busy=False,
                    ready=False,
                    phase="Stopped",
                    error=str(exc)[:300] or type(exc).__name__,
                )
            with self.cv:
                self.cv.wait_for(
                    lambda current=run: self.closing or self.run != current
                )

    def close(self):
        with self.cv:
            self.closing = True
            self.changed()
        self.worker.join(timeout=55)
        self.inference.shutdown(wait=True, cancel_futures=True)
        if self.plan_pool:
            self.plan_pool.shutdown(wait=True, cancel_futures=True)


class Dashboard(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, data=b"", kind="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def video(self, path, download):
        parts = path.split("/")
        if len(parts) != 4 or parts[3] != "agent.mp4":
            return self.send(404)
        file = self.server.app.recordings.file(parts[2])
        if file is None or not file.is_file():
            return self.send(404)
        size = file.stat().st_size
        start, end = 0, size - 1
        byte_range = self.headers.get("Range")
        if byte_range is not None:
            import re

            match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
            if match and any(match.groups()):
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size - int(last))
            else:
                start = size
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if byte_range else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header(
                "Content-Disposition", f'attachment; filename="quake-{parts[2]}.mp4"'
            )
        self.end_headers()
        with file.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    data = stream.read(min(65536, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        if self.headers.get("Host") not in self.server.hosts:
            return self.send(403)
        from urllib.parse import parse_qs

        u = urlsplit(self.path)
        if u.path.startswith("/api/route-photo/"):
            atlas = self.server.app.route_atlas
            key = u.path.removeprefix("/api/route-photo/")
            if atlas and key.isascii() and key.isdigit() and len(key) <= 5 and int(key) in atlas.photos:
                return self.send(200, atlas.photos[int(key)], "image/jpeg")
            return self.send(404)
        if u.path.startswith(
            ("/api/planner-frame/", "/api/preview-frame/", "/api/panorama-frame/", "/api/jev-frame/")
        ):
            import re

            match = re.fullmatch(
                r"/api/(?:planner|preview|panorama|jev)-frame/(\d+)/(\d+)", u.path
            )
            if match:
                app = self.server.app
                with app.cv:
                    directory = (
                        app.active_directory if int(match[1]) == app.run else None
                    )
                if directory:
                    path = (
                        directory
                        / (
                            "previews"
                            if u.path.startswith("/api/preview")
                            else "panoramas"
                            if u.path.startswith("/api/panorama")
                            else "jev-frames" if u.path.startswith("/api/jev-frame/")
                            else "frames"
                        )
                        / f"{int(match[2])}.jpg"
                    )
                    if path.is_file():
                        return self.send(200, path.read_bytes(), "image/jpeg")
            return self.send(404)
        if u.path == "/api/navigation":
            app = self.server.app
            with app.cv:
                snapshot = {
                    "run": app.run,
                    "revision": app.navigation_revision,
                    "map": app.navigation_map,
                }
            return self.send(200, json.dumps(snapshot).encode())
        if u.path == "/api/recordings":
            return self.send(
                200, json.dumps(self.server.app.recordings.list()).encode()
            )
        if u.path.startswith("/recordings/"):
            return self.video(u.path, u.query == "download")
        if u.path in ("/", "/app.js", "/style.css"):
            name, kind = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
            }[u.path]
            return self.send(200, (HERE / name).read_bytes(), kind)
        try:
            if u.path == "/api/live":
                after = int(parse_qs(u.query).get("after", [-1])[0])
                value = self.server.app.snapshot(after)
                return (
                    self.send(204)
                    if value is None
                    else self.send(200, json.dumps(value).encode())
                )
            if u.path.startswith("/api/decision/"):
                _, _, _, run, seq = u.path.split("/")
                event = self.server.app.archived(int(run), int(seq))
                if event:
                    return self.send(200, json.dumps(event).encode())
        except ValueError:
            return self.send(400)
        return self.send(404)

    def do_POST(self):
        host = self.headers.get("Host")
        if (
            host not in self.server.hosts
            or self.headers.get("Origin") != "http://" + host
        ):
            return self.send(403)
        if self.path not in [
            "/api/" + s
            for s in (
                "play",
                "pause",
                "step",
                "finish",
                "reset",
                "entrance",
                "encounter",
                "local-planner",
                "cloud-player",
                "gemma-text",
                "gemma-screenshots",
            )
        ]:
            return self.send(404)
        return self.send(
            204 if self.server.app.command(self.path.rsplit("/", 1)[1]) else 409
        )


def main():
    import cv2

    cv2.setNumThreads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media",
        type=Path,
        default=Path.home() / "Library/Application Support/Mojo Quake/media",
        help="Directory containing id1/pak0.pak",
    )
    parser.add_argument(
        "--key-file", type=Path, help="Existing env file containing MODULAR_API_KEY"
    )
    parser.add_argument(
        "--binary", type=Path, help="Native Quake binary with -mqagent support"
    )
    parser.add_argument("--gpu", action="store_true", help="Use the OpenGL renderer")
    parser.add_argument(
        "--weapon-profile",
        type=Path,
        help="RGB weapon-pose calibration for the local character detector",
    )
    parser.add_argument(
        "--own-save-lookahead",
        action="store_true",
        help="Compare camera outcomes in a separate native game from the current player's own save in layered mode",
    )
    parser.add_argument("--archive-search", action="store_true", help="Explore an in-attempt graph of private camera previews rooted in the agent's own saves")
    parser.add_argument("--frontier-saves", action="store_true", help="Revisit an own checkpoint after prolonged familiar travel and prefer a different departure")
    parser.add_argument("--future-passages", action="store_true", help="Compare short onward routes in the agent's own private preview")
    parser.add_argument("--movement-lessons", choices=("off", "shadow", "active"), default="off",
                        help="Record camera-triggered movement lessons or apply them in the layered controller")
    parser.add_argument("--jev-key-file", type=Path, help="File containing TYPESAFE_API_KEY (or export it in the server environment)")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--decision-model", choices=("laya", "modular-gemma"), default="laya",
                        help="Decision model for the layered player")
    parser.add_argument("--e1m1-guide", action="store_true", help="Give the layered player a prepared visual route and an optional tutorial jump")
    parser.add_argument(
        "--single-life",
        dest="checkpoints",
        action="store_false",
        help="End the run at the first death instead of restoring the agent's own save",
    )
    parser.add_argument(
        "--enemy-detector",
        type=Path,
        help="Optional local Quake or COCO YOLO11n ONNX export (512 × 320); install onnxruntime",
    )
    parser.add_argument("--cloud-model", choices=tuple(CLOUD_MODELS), default="gemma")
    parser.add_argument(
        "--controller",
        choices=("single-call", "split", "layered", "jev"),
        default="single-call",
        help="Choose a Modular controller or direct TypeSafe Jev image-to-action control",
    )
    parser.add_argument(
        "--resume-session",
        type=Path,
        help="Resume a completed decision in an agent-runs directory, preserving its history",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional maximum decisions per session (default: play until exit or death)",
    )
    parser.add_argument(
        "--records", type=Path, default=HERE.parent / "build/agent-runs"
    )
    parser.add_argument(
        "--planner-model",
        choices=tuple(CLOUD_MODELS),
        help="Run a background strategy model (layered default: minimax)",
    )
    parser.add_argument(
        "--local-player-url",
        default="http://127.0.0.1:61375",
        help="Loopback Ollaya endpoint for the layered controller",
    )
    parser.add_argument(
        "--offer-layered",
        action="store_true",
        help="Allow switching between the cloud player and the local player with a background planner in the dashboard",
    )
    parser.add_argument(
        "--continuous-travel",
        action="store_true",
        help="Test continuous forward exploration from the entrance, with control and combat interrupts",
    )
    parser.add_argument(
        "--scene-model",
        type=Path,
        help="Optional local monocular RGB passage estimator (Depth Anything V2 Small ONNX)",
    )
    args = parser.parse_args()
    if args.decision_model == "modular-gemma" and args.controller != "layered" and not args.offer_layered:
        parser.error("--decision-model modular-gemma requires a layered player")
    if args.e1m1_guide and (args.controller != "layered" or args.offer_layered or args.own_save_lookahead or args.continuous_travel):
        parser.error("--e1m1-guide requires the layered player with direct local decisions")
    if args.controller == "jev" and any((args.offer_layered, args.enemy_detector, args.scene_model,
                                         args.own_save_lookahead, args.continuous_travel, args.frontier_saves,
                                         args.archive_search, args.future_passages)):
        parser.error("Jev direct mode uses its own camera, actor and jump previews. Use --planner-model for background strategy.")
    if args.offer_layered and args.controller == "split":
        parser.error(
            "--offer-layered works with the single-call and layered controllers"
        )
    args.binary = (
        args.binary
        or HERE.parent / "build/host" / ("tyr-glquake" if args.gpu else "tyr-quake")
    ).resolve()
    args.media = args.media.resolve()
    if (
        (args.limit is not None and args.limit <= 0)
        or not os.access(args.binary, os.X_OK)
        or not (args.media / "id1/pak0.pak").is_file()
    ):
        parser.error(
            "Provide a built game, valid Quake media and, if supplied, a positive step limit"
        )
    args.records.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Dashboard)
    port = server.server_port
    server.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if args.controller == "jev":
        jev_file = args.jev_key_file or (None if os.environ.get("TYPESAFE_API_KEY") else args.key_file)
        models = JevPlayer(read_key(jev_file, "TYPESAFE_API_KEY"))
    else:
        models = Models(read_key(args.key_file), single_call=args.controller != "split",
                        cloud_model=CLOUD_MODELS[args.cloud_model])
    plan_model = args.planner_model or (
        "minimax" if args.controller == "layered" or args.offer_layered else None
    )
    planner = (
        Models(read_key(args.key_file), single_call=True, cloud_model=CLOUD_MODELS[plan_model])
        if plan_model
        else None
    )
    local_player = None
    if args.controller == "layered" or args.offer_layered:
        local_player = (ModularGemmaPlayer(read_key(args.key_file)) if args.decision_model == "modular-gemma"
                        else LocalPlayer(args.local_player_url))
    app = Observatory(args, models, planner=planner, local_player=local_player)
    server.app = app
    print(f"Quake Observatory at http://127.0.0.1:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
        models.close()
        if local_player:
            local_player.close()
        if planner:
            planner.close()


if __name__ == "__main__":
    main()
