import json
from pathlib import Path
from queue import Queue
import subprocess
import sys
import io
from threading import Thread
import unittest
from PIL import Image

from encounter_memory import EncounterMemory
from navigation import RouteMemory
from unoq_bridge import turn_duration
from unoq_observatory import (
    BoardGuide,
    camera_steer,
    choose,
    limit_blind_turns,
    move_choices,
    Pilot,
)


class BoardLinkTests(unittest.TestCase):
    def test_camera_correction_scales_with_visible_offset(self):
        nav = {"prepared_route": {}}
        near = camera_steer({"action": "face_left", "opponent_x": 45}, nav)
        edge = camera_steer({"action": "face_left", "opponent_x": 2}, nav)
        self.assertAlmostEqual(near, 5.71, places=2)
        self.assertGreater(edge, 40)
        self.assertEqual(turn_duration(near), 2)
        self.assertGreater(turn_duration(edge), turn_duration(near))
        self.assertEqual(
            camera_steer({"action": "face_right", "opponent_x": 2}, nav), 0
        )
        self.assertEqual(camera_steer({"action": "fire", "opponent_x": 2}, nav), 0)

    def test_repeated_blind_camera_turns_yield_to_repositioning(self):
        history = [
            {
                "action": "turn_right",
                "status": "applied",
                "end_tick": tick,
                "opponent": "none",
            }
            for tick in (2389, 2426, 2464)
        ]
        blind = {"action": "turn_right", "opponent": "none"}
        nav = {"exploration": {"blocked_inputs": []}}
        self.assertEqual(
            limit_blind_turns(blind, 2480, history, nav)["action"], "back_up"
        )
        self.assertEqual(
            limit_blind_turns(blind, 2480, history[:2], nav)["action"], "turn_right"
        )
        reverse = dict(blind, action="face_left")
        self.assertEqual(
            limit_blind_turns(reverse, 2480, history[-1:], nav)["action"], "back_up"
        )
        self.assertEqual(
            limit_blind_turns(dict(reverse, opponent="live_left"), 2480, history, nav)[
                "action"
            ],
            "face_left",
        )
        blocked = {"exploration": {"blocked_inputs": ["back_up"]}}
        self.assertEqual(
            limit_blind_turns(blind, 2480, history, blocked)["action"], "check_view"
        )

    def test_encounter_tracks_hit_and_rechecks_the_wounded_guard(self):
        encounter = EncounterMemory()
        encounter.observe_health(100, 700)
        encounter.observe_health(92, 734)
        context = encounter.context(734, 65)
        self.assertEqual(context["recent_hit"]["hp_lost"], 8)
        scan = encounter.react(
            {"action": "face_right", "opponent": "none"}, 734, 65, context
        )
        self.assertEqual(scan["action"], "turn_right")
        encounter.applied(scan, 759, 0)
        context = encounter.context(766, 33)
        still_scanning = encounter.react(
            {"action": "face_left", "opponent": "none"}, 766, 33, context
        )
        self.assertEqual(still_scanning["action"], "turn_right")
        self.assertEqual(encounter.context(900, 33), {})
        encounter.observe_health(80, 901)
        self.assertIsNone(encounter.context(901, 33)["recent_hit"]["search_side"])

        sight = {"action": "face_left", "opponent": "live_left"}
        encounter.react(sight, 1260, 141, encounter.context(1260, 141))
        missed = {"action": "advance", "opponent": "none"}
        self.assertEqual(
            encounter.react(missed, 1305, 161, encounter.context(1305, 161))["action"],
            "face_left",
        )

        shot = {"action": "fire", "opponent": "live_ahead"}
        encounter.react(shot, 1494, 161, encounter.context(1494, 161))
        encounter.applied(shot, 1514, 0)
        self.assertFalse(encounter.confirm_kills(0))
        fallen = {"action": "advance", "opponent": "fallen"}
        check = encounter.react(fallen, 1537, 161, encounter.context(1537, 161))
        self.assertEqual(check["action"], "check_view")
        self.assertEqual(check["opponent"], "fallen")
        encounter.applied(check, 1561, 0)
        self.assertEqual(encounter.context(1568, 161)["last_shot"]["checks_left"], 1)
        self.assertTrue(encounter.confirm_kills(1))
        self.assertEqual(
            encounter.react(fallen, 1570, 161, encounter.context(1570, 161))["action"],
            "advance",
        )

    def test_lost_corner_can_rotate_toward_next_landmark_without_claiming_match(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        import numpy as np

        atlas = SimpleNamespace(
            samples=[
                SimpleNamespace(tick=658, position=np.array([350, 460, 56])),
                SimpleNamespace(tick=768, position=np.array([48, 600, 24])),
            ]
        )
        guide = BoardGuide(atlas)
        guide.last_match_tick = 100
        guide.observe = Mock(
            return_value={
                "matched": False,
                "stage": 1,
                "reference_tick": 658,
                "suggested": None,
            }
        )
        lost = guide.board_view(b"frame", 90, 120)
        self.assertFalse(lost["matched"])
        self.assertEqual(lost["search_turn"], "turn_left")
        self.assertNotIn("advance", move_choices(lost, {}))
        self.assertNotIn("search_turn", guide.board_view(b"frame", 90, 500))

    def test_lift_exit_cue_survives_a_brief_camera_mismatch(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        import numpy as np

        atlas = SimpleNamespace(
            samples=[
                SimpleNamespace(tick=948, position=np.array([-54, 576, -187])),
                SimpleNamespace(tick=978, position=np.array([-32, 686, -208])),
            ]
        )
        guide = BoardGuide(atlas)
        hint = {"stage": 3, "reference_tick": 948, "matched": True}
        guide.observe = Mock(return_value=hint)
        start = guide.board_view(b"frame", 90, 100)
        self.assertEqual(start["lift_exit_input"], "follow_route")
        hint["matched"] = False
        lost = guide.board_view(b"frame", 150, 170)
        self.assertFalse(lost["matched"])
        self.assertEqual(lost["lift_exit_input"], "turn_right")
        self.assertNotIn("back_up", move_choices(lost, {}))
        self.assertEqual(
            camera_steer({"action": "turn_right"}, {"prepared_route": lost}), -45
        )
        self.assertNotIn("lift_exit_input", guide.board_view(b"frame", 150, 540))

    def test_step_receipt_and_neutral_clock_with_no_mac_input(self):
        fake = """
from unoq_bridge import serve
class Game:
    tick = 0
    yaw = 90
    pitch = 0
    p = type('Child', (), {'pid': 1})()
    attack_ticks = 0
    forward_yaws = []
    def move(self, count, forward=0, side=0, *, attack=False):
        self.tick += count
        if attack: self.attack_ticks += count
        if forward: self.forward_yaws.append(self.yaw)
        return bytes(768+320*240)
    def stats(self):
        return {'yaw': str(self.yaw), 'hp':'100','intermission':'0', 'attack_ticks': self.attack_ticks, 'forward_yaws': self.forward_yaws}
serve(Game())
"""
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", fake],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=Path(__file__).parent,
            text=True,
        )
        events = Queue()

        def read():
            for line in proc.stdout:
                events.put(json.loads(line))

        reader = Thread(target=read, daemon=True)
        reader.start()

        def send(**msg):
            print(json.dumps(msg), file=proc.stdin, flush=True)

        def wait(kind, **expected):
            while True:
                msg = events.get(timeout=4)
                if msg["type"] == "frame":
                    send(op="ack", sequence=msg["sequence"])
                if msg["type"] == kind and all(
                    msg.get(k) == v for k, v in expected.items()
                ):
                    return msg

        try:
            wait("frame", mode="paused", tick=24)
            send(op="step", token=1)
            wait("mode", mode="step", token=1)
            frame = wait("frame", mode="step")
            self.assertGreater(frame["tick"], 24)
            send(op="input", id=1, source=-1, action="turn_left")
            wait("reject", reason="stale observation")
            send(
                op="input", id=2, source=frame["tick"], action="follow_route", steer=90
            )
            wait("reject", reason="invalid route direction")
            send(
                op="input", id=3, source=frame["tick"], action="follow_route", steer=36
            )
            started = wait("applied", id=3)
            intermediate = wait("frame", mode="step")
            self.assertGreater(intermediate["yaw"], 90)
            self.assertLess(intermediate["yaw"], 126)
            ended = wait("end", id=3, status="applied")
            self.assertEqual(ended["tick"] - started["tick"] + 1, 24)
            self.assertEqual(float(ended["stats"]["yaw"]), 126)
            wait("mode", mode="paused", token=1)
            send(op="input", id=2, source=frame["tick"], action="turn_right")
            wait("reject", reason="invalid input")
            send(op="input", id=4, source=frame["tick"], action="turn_left")
            wait("reject", reason="board not accepting input")
            send(op="step", token=2)
            frame = wait("frame", mode="step")
            send(op="input", id=5, source=frame["tick"], action="fire")
            fired = wait("end", id=5, status="applied")
            self.assertEqual(fired["stats"]["attack_ticks"], 24)
            wait("mode", mode="paused", token=2)
            for token, angle, final_yaw in ((3, 6, 132), (4, 42, 174)):
                send(op="step", token=token)
                sample = wait("frame", mode="step")
                send(
                    op="input",
                    id=token + 3,
                    source=sample["tick"],
                    action="face_left",
                    steer=angle,
                )
                applied = wait("applied", id=token + 3)
                ended = wait("end", id=token + 3, status="applied")
                self.assertEqual(
                    ended["tick"] - applied["tick"] + 1, turn_duration(angle)
                )
                self.assertEqual(applied["turn_degrees"], angle)
                self.assertEqual(float(ended["stats"]["yaw"]), final_yaw)
                wait("mode", mode="paused", token=token)
            send(op="step", token=5)
            sample = wait("frame", mode="step")
            send(
                op="input", id=8, source=sample["tick"], action="touch_switch", steer=27
            )
            applied = wait("applied", id=8)
            contacted = wait("end", id=8, status="applied")
            self.assertEqual(applied["duration_ticks"], 30)
            self.assertEqual(contacted["stats"]["attack_ticks"], 24)
            previous = len(ended["stats"]["forward_yaws"])
            self.assertEqual(set(contacted["stats"]["forward_yaws"][previous:]), {201})
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            reader.join(timeout=1)
            proc.stdout.close()

    def test_entrance_survey_accepts_only_a_game_camera_turn(self):
        class Model:
            def _read_frame(self, *args, **kwargs):
                return {"action": "advance", "scene": "A passage lies ahead."}

        with self.assertRaises(ValueError):
            choose(Model(), b"picture", None, [], True)
        self.assertEqual(
            choose(Model(), b"picture", None, [], False)["action"], "advance"
        )

    def test_quake_shot_requires_live_opponent_and_an_available_input(self):
        class Model:
            def _read_frame(self, *args, **kwargs):
                return {
                    "action": "fire",
                    "scene": "Quake guard in the corridor.",
                    "opponent": self.label,
                }

        m = Model()
        nav = {
            "prepared_route": {"matched": True, "suggested": "follow_route"},
            "visible_ammo": 9,
        }
        m.label = "live_ahead"
        self.assertEqual(choose(m, b"frame", None, [], False, nav)["action"], "fire")
        for m.label in ("fallen", "none", "unclear", "live_right"):
            with self.assertRaises(ValueError):
                choose(m, b"frame", None, [], False, nav)
        m.label = "live_ahead"
        with self.assertRaises(ValueError):
            choose(m, b"frame", None, [], False, dict(nav, visible_ammo=0))

    def test_lift_touch_requires_a_visible_diamond_and_prefers_current_map(self):
        class Model:
            def _read_frame(self, image, prompt, max_tokens, *, schema):
                self.context = json.loads(prompt[prompt.index('{"objective"'):])
                return self.reply

        model = Model()
        nav = {
            "prepared_route": {
                "matched": False,
                "search_turn": "turn_left",
                "control": "Walk into the red diamond wall button to lower the lift.",
            },
            "visible_ammo": 22,
        }
        plan = {"next_input": "shoot_switch", "objective": "Shoot the red diamond."}
        model.reply = {
            "action": "touch_switch",
            "scene": "A clear path leads to the red diamond button.",
            "opponent": "none",
            "switch_point": [54, 47],
        }
        choice = choose(model, b"frame", plan, [], False, nav)
        self.assertEqual(choice["action"], "touch_switch")
        self.assertAlmostEqual(camera_steer(choice, nav), -4.574, places=2)
        self.assertEqual(model.context["map_input"], "turn_left")
        self.assertIsNone(model.context["planner"])
        self.assertNotIn("ride_lift", model.context["allowed"])
        self.assertNotIn("touch_switch", move_choices({}, {}))

        nav["recent_switch_attempt"] = True
        nav["prepared_route"].update(matched=True, suggested="follow_route")
        choose(model, b"frame", plan, [], False, nav)
        self.assertEqual(model.context["map_input"], "follow_route")
        self.assertIn("ride_lift", model.context["allowed"])

        for point in (None, [53, 99], [99, 47]):
            model.reply["switch_point"] = point
            choice = choose(model, b"frame", plan, [], False, nav)
            self.assertEqual(choice["action"], "check_view")
        model.reply["action"] = "fire"
        self.assertEqual(
            choose(model, b"frame", plan, [], False, nav)["action"], "check_view"
        )
        model.reply["opponent"] = "live_ahead"
        self.assertEqual(choose(model, b"frame", plan, [], False, nav)["action"], "fire")

    def test_blocked_lift_hides_the_switch_from_the_prompt_and_recovers(self):
        class Model:
            def _read_frame(self, image, prompt, max_tokens, *, schema):
                self.context = json.loads(prompt[prompt.index('{"objective"'):])
                self.properties = schema["properties"]
                return {"action": "touch_switch", "opponent": "none", "scene": "A button."}

        model = Model()
        nav = {
            "prepared_route": {
                "control": "Walk into the red diamond wall button to lower the lift.",
                "matched": True,
                "suggested": "follow_route",
            },
            "exploration": {"blocked_inputs": ["advance", "follow_route", "strafe_left"]},
        }
        plan = {"next_input": "touch_switch", "objective": "Touch the red lift button."}
        choice = choose(model, b"frame", plan, [], False, nav)
        self.assertIsNone(model.context["planner"])
        self.assertNotIn("touch_switch", model.properties["action"]["enum"])
        self.assertNotIn("switch_point", model.properties)
        self.assertEqual(choice["action"], "strafe_right")

    def test_identical_board_views_after_two_forward_receipts_block_the_heading(self):
        pilot = Pilot.__new__(Pilot)
        pilot.memory = RouteMemory()
        pilot.motion = None
        out = io.BytesIO()
        Image.new("L", (320, 240), 40).save(out, "JPEG")
        view = out.getvalue()
        pilot.track_frame(view, 24, 90)
        for start in (30, 100):
            pilot.motion = (start, start + 23, 290, 0)
            # All previews from inside the move were dropped in transit.
            pilot.track_frame(view, start + 40, 90)
        memory = pilot.memory.guidance([50, 55])
        self.assertIn("ahead: walk x2", memory["unsuccessful"])
        hint = {"matched": True, "suggested": "follow_route", "route": [50, 55]}
        self.assertNotIn("advance", move_choices(hint, memory))
        self.assertNotIn("follow_route", move_choices(hint, memory))
        self.assertIn("turn_left", move_choices(hint, memory))
        pilot.track_frame(view, 150, 180)
        self.assertIn("advance", move_choices({}, pilot.memory.guidance(None)))
