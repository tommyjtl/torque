import io
import unittest
from types import SimpleNamespace

import numpy as np
from exploration import HZ, Exploration
from models import allowed_inputs, game_input, input_chunk
from navigation import Place, RouteMemory
from observatory import recent_context
from PIL import Image
from survey import PassageSurvey, survey_keys
from targets import track_character


def game_frame(seed=None):
    if seed is None:
        image = Image.new("RGB", (320, 240), (3, 3, 3))
    else:
        rng = np.random.default_rng(seed)
        image = Image.fromarray(rng.integers(0, 220, (24, 32, 3), dtype=np.uint8))
        image = image.resize((320, 240), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    image.save(buf, "JPEG")
    return buf.getvalue()


class ExplorationTests(unittest.TestCase):
    def test_familiar_travel_starts_recovery_and_visually_novel_travel_does_not(self):
        same = game_frame(87)
        loop, new = Exploration(), Exploration()
        for half in range(101):
            tick = half * HZ // 2
            loop.observe(same, tick, 0, 0, 0, moved=True)
            new.observe(game_frame(half), tick, 0, 0, half, moved=True)
            loop.check(tick)
            new.check(tick)
        self.assertTrue(loop.active)
        self.assertFalse(new.active)
        self.assertLessEqual(loop.last_recovery, 45 * HZ)

    def test_blank_and_rotation_dont_reset_progress_clock(self):
        for frame, moving in ((game_frame(), True), (game_frame(1), False)):
            w = Exploration()
            for t in range(0, 45 * HZ + 1, HZ):
                w.observe(frame, t, (t // HZ) * 15, 0, 0, moved=moving)
                w.check(t)
            self.assertTrue(w.active)
            self.assertEqual(w.last_recovery, 45 * HZ)

    def test_recovery_prioritizes_character_and_then_known_junction(self):
        m = RouteMemory()
        m.places.append(Place(1, 0))
        m.places[0].exits[2] = 1
        m.places[1].openings.add(4)
        explorer = Exploration()
        explorer.active = True
        g = SimpleNamespace(yaw=0, tick=24)
        self.assertIsNone(explorer.choose(g, m, {"enemy": [40, 50]}))
        self.assertEqual(explorer.choose(g, m, {})[0], "back_up")
        result = explorer.choose(g, m, {})
        self.assertEqual(result[:2], ("branch_turn", 90))
        self.assertIn("P2", result[2])

    def test_mechanism_inputs_require_an_observed_target(self):
        nav = RouteMemory().guidance(None)
        vis = {"route": None, "enemy": None, "clearance": "unclear"}
        for a in ("touch_switch", "shoot_switch", "board_platform", "ride_lift"):
            self.assertNotIn(a, allowed_inputs(vis, [], nav))
        vis.update(platform=[60, 70], switch=[80, 52], blocker="moving_platform")
        for a in ("touch_switch", "shoot_switch", "board_platform", "ride_lift"):
            self.assertIn(a, allowed_inputs(vis, [], nav))
        self.assertLess(game_input("touch_switch", vis)[4], 0)
        self.assertEqual(
            input_chunk("board_platform", 20, (270, 0, 0), 4)[1], (0, 0, 0)
        )

    def test_recent_context_has_only_observed_clues(self):
        event = {
            "action": "touch_switch",
            "ticks": 16,
            "view_change_pct": 7,
            "evaluator": {"pos": "hidden"},
            "vision": {
                "blocker": "closed_door",
                "clearance": "unclear",
                "switch": [50, 52],
            },
        }
        self.assertEqual(
            recent_context([event]),
            [
                {
                    "action": "touch_switch",
                    "view_change_pct": 7,
                    "blocker": "closed_door",
                    "clearance": "unclear",
                    "saw_switch": True,
                }
            ],
        )

    def test_camera_aim_turns_before_firing(self):
        self.assertEqual(track_character([0, 50]), (14, 0, 0))
        self.assertEqual(track_character([50, 50]), (0, 0, 1))


class PassageTests(unittest.TestCase):
    def test_camera_failure_records_edge_and_next_choice_changes(self):
        search = PassageSurvey(0)
        search.pending = (0, False)
        search.flow = [0.001] * 7
        e = search.finish(completed=True)
        self.assertEqual(e["result"], "no confirmed travel")
        self.assertEqual(search.cell, (0, 0))
        self.assertNotEqual(search.next_edge(0), (0, False))

    def test_turn_commits_to_a_probe_even_if_the_arrival_view_matches_another_place(
        self,
    ):
        search = PassageSurvey(0)
        frame = game_frame(49)
        search.cell = (4, 0)
        search.register_view(frame, 90, 0)
        search.cell = (0, 0)
        search.pending = (1, False)
        game = SimpleNamespace(yaw=0, pitch=0)
        self.assertEqual(search.choose(game, {}, frame)[:2], ("branch_turn", 90))
        game.yaw = 90
        self.assertEqual(search.ready_probe(game.yaw, game.pitch), "test_passage")
        self.assertEqual(
            search.choose(game, {"platform": [50, 75]}, frame)[0], "test_passage"
        )
        self.assertEqual(search.cell, (0, 0))
        search.flow = [0.05] * 6
        self.assertEqual(search.finish(True)["to"], [0, 1])

    def test_cancelled_input_cannot_create_a_connection(self):
        search = PassageSurvey(0)
        search.pending = (1, False)
        search.flow = [0.08] * 4
        self.assertEqual(search.finish(False)["result"], "interrupted")
        self.assertFalse(search.edges)
        self.assertEqual(search.cell, (0, 0))

    def test_same_settled_view_recovers_previously_tested_junction(self):
        search = PassageSurvey(90)
        frame = game_frame(43)
        search.register_view(frame, 90, 0)
        search.edges[(0, 0), 0] = False
        search.cell = (3, 0)
        search.pending = (0, False)
        search.register_view(frame, 90, 0)
        self.assertEqual(search.cell, (0, 0))
        self.assertIsNone(search.pending)
        self.assertNotEqual(search.next_edge(0), (0, False))
        self.assertEqual(search.revisits, 1)

    def test_walk_has_fixed_heading_and_coasts_without_reversing(self):
        for name, duration in [("test_passage", 42), ("test_ledge", 54)]:
            left = duration
            forward = jumped = 0
            while left:
                n, keys = survey_keys(name, left, 4)
                self.assertGreater(n, 0)
                self.assertGreaterEqual(keys[0], 0)
                forward += n if keys[0] else 0
                jumped += n if keys[2] else 0
                left -= n
            self.assertEqual(forward, 46 if name == "test_ledge" else 14)
            self.assertEqual(jumped, 4 if name == "test_ledge" else 0)
