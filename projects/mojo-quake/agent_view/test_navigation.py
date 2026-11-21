"""Perceptual place memory and its effects on the local action vocabulary."""

import io
import random
import unittest

from models import allowed_inputs, game_input
from movement_lessons import MovementLessons
from navigation import RouteMemory
from PIL import Image


def scene(seed):
    rng = random.Random(seed)
    data = bytes(rng.randrange(40, 230) for _ in range(20 * 16))
    image = Image.frombytes("L", (20, 16), data).resize(
        (320, 240), Image.Resampling.NEAREST
    )
    buf = io.BytesIO()
    image.save(buf, "JPEG")
    return buf.getvalue()


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = scene(1), scene(2)
        self.m = RouteMemory()
        self.m.track(self.a, 24, 90, 0)
        self.tick = 24

    def move(self, finish, forward=320, jump=False):
        for _ in range(8):
            self.tick += 4
            self.m.track(self.b, self.tick, 90, 0, forward, 0, 2 if jump else 0)
        for _ in range(9):
            self.tick += 4
            self.m.track(finish, self.tick, 90, 0)

    def test_jump_bob_does_not_create_places_and_repeated_failure_changes_choices(self):
        self.move(self.a, jump=True)
        self.move(self.a, jump=True)
        guidance = self.m.guidance(None)
        self.assertEqual(self.m.here, 0)
        self.assertEqual(self.m.places[0].failures[0, "jump"], 2)
        choices = allowed_inputs({"enemy": None, "route": None}, [], guidance)
        self.assertNotIn("jump_forward", choices)
        self.assertIn("back_up", choices)
        self.assertTrue(guidance["recover"])

    def test_travel_return_and_directional_memory(self):
        self.move(self.a, jump=True)
        self.move(self.a, jump=True)
        self.move(self.b)
        self.assertEqual(self.m.here, 1)
        self.assertNotIn("jump_forward", self.m.guidance(None)["blocked_inputs"])
        self.move(self.a, forward=-250)
        self.assertEqual((self.m.here, self.m.places[0].visits), (0, 2))
        self.assertIn("jump_forward", self.m.guidance(None)["blocked_inputs"])
        self.assertEqual(self.m.diagram()["links"], [[1, 2]])
        self.m.track(self.b, self.tick + 8, 180, -40)
        guidance = self.m.guidance(None)
        self.assertNotIn("jump_forward", guidance["blocked_inputs"])
        self.assertIn("right: jump x2", guidance["unsuccessful"])
        self.assertEqual(game_input("level_view", {}, -40)[-1], 40)

    def test_idle_turns_and_uncertain_airborne_frame(self):
        for yaw in (122, 154, 186):
            self.tick += 12
            self.m.track(self.b, self.tick, yaw, -10)
        self.assertEqual(len(self.m.places), 1)
        self.m.track(self.b, self.tick + 4, 186, -10, 320, 0, 2)
        self.assertIn("jump_forward", self.m.guidance(None)["blocked_inputs"])
        self.assertFalse(self.m.places[0].failures)

    def test_failed_walk_blocks_only_matching_route_and_releases_after_turn(self):
        self.m.movement_lessons = MovementLessons("active")
        self.move(self.a)
        self.move(self.a)
        g = self.m.guidance([50, 55])
        self.assertIn("2 walks", g["movement_lesson"]["advice"])
        self.assertIn("advance", g["blocked_inputs"])
        self.assertIn("follow_route", g["blocked_inputs"])
        self.assertNotIn("follow_route", self.m.guidance([85, 55])["blocked_inputs"])
        self.m.track(self.b, self.tick + 4, 135, 0)
        self.assertNotIn("movement_lesson", self.m.guidance(None))
        self.assertNotIn("advance", self.m.guidance(None)["blocked_inputs"])
