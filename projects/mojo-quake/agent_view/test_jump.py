"""Check a running jump as keys on the wire and as one navigation attempt."""

import unittest

from models import allowed_inputs, game_input, input_chunk, parse_observation
from navigation import RouteMemory
from test_navigation import scene


class RunningJumpTests(unittest.TestCase):
    def test_jump_builds_speed_pulses_and_holds_forward_even_with_uneven_chunks(self):
        vision = {"landing": [25, 60]}
        ticks, f, side, buttons, yaw, pitch = game_input("jump_forward", vision, -10)
        self.assertGreater(yaw, 0)
        self.assertEqual(pitch, 0)
        keys = []
        remaining = ticks
        while remaining:
            chunk, held = input_chunk("jump_forward", remaining, (f, side, buttons), 7)
            keys.extend([held] * chunk)
            remaining -= chunk
        self.assertEqual(
            keys, [(320, 0, 0)] * 8 + [(320, 0, 2)] * 4 + [(320, 0, 0)] * 48
        )
        self.assertEqual(input_chunk(None, 0, (0, 0, 0), 4), (4, (0, 0, 0)))

    def test_pulsed_jump_is_one_directional_failure(self):
        memory = RouteMemory()
        pic, air = scene(1), scene(3)
        t = 24
        memory.track(pic, t, 90, 0)
        for _ in range(2):
            for elapsed in range(0, 60, 4):
                t += 4
                memory.track(
                    air if 8 <= elapsed < 44 else pic,
                    t,
                    90,
                    0,
                    320,
                    0,
                    2 if elapsed == 8 else 0,
                )
            for _ in range(4):
                t += 4
                memory.track(pic, t, 90, 0)
        self.assertEqual(memory.places[0].failures, {(0, "jump"): 2})
        vision = {"route": None, "enemy": None, "landing": [50, 62]}
        self.assertNotIn(
            "jump_forward",
            allowed_inputs(vision, [], memory.guidance(None, vision["landing"])),
        )
        # The map's escape filter allows an untried landing in a different sector.
        vision["landing"] = [95, 63]
        self.assertIn(
            "jump_forward",
            allowed_inputs(vision, [], memory.guidance(None, vision["landing"])),
        )

    def test_unreliable_landing_never_turns_the_player(self):
        vision = parse_observation(
            '{"scene":"Metal lip","enemy":null,"route":[15,20],"landing":[500,700]}'
        )
        self.assertIsNone(vision["landing"])
        self.assertEqual(vision["route"], [15, 20])
        self.assertEqual(game_input("jump_forward", vision)[4], 0)
