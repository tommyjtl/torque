"""Traversal and reactions use the visible status bar and qualitative clearance."""

import unittest

from hud import DamageSense
from models import allowed_inputs, input_chunk, resolve_proposal


class Pixels:
    def read(self, sample):
        return sample


class ClearanceAndDamageTests(unittest.TestCase):
    def test_slit_or_high_face_has_a_legal_same_frame_recovery(self):
        nav = {
            "pitch": 0,
            "blocked_inputs": [],
            "recover": True,
            "escape_options": ["back_up", "turn_right"],
        }
        for height in ("too_low", "too_high"):
            view = {
                "enemy": None,
                "route": [50, 65],
                "landing": None,
                "clearance": height,
            }
            legal = allowed_inputs(view, [], nav)
            self.assertNotIn("follow_route", legal)
            self.assertNotIn("jump_forward", legal)
            action, _reason, source = resolve_proposal(
                ("follow_route", "passage"), view, [], nav
            )
            self.assertIn(action, legal)
            self.assertEqual(source, "local recovery")

    def test_confirmed_hit_and_scan_debounce(self):
        sense = DamageSense(Pixels())
        for hp, tick in [(100, 0), (None, 4), (100, 8), (110, 12), (92, 16)]:
            sense.watch(hp, tick)
        self.assertEqual(
            sense.take_pending(),
            {
                "action": "evade_and_scan",
                "detected_tick": 16,
                "from_hp": 110,
                "to_hp": 92,
            },
        )
        sense.watch(88, 24)
        self.assertIsNone(sense.take_pending())
        sense.watch(76, 96)
        self.assertEqual(sense.take_pending()["action"], "jump_back")
        sense.see_enemy([50, 60], 380)
        sense.watch(68, 392)
        self.assertEqual(sense.take_pending()["action"], "jump_back")
        sense.watch(0, 400)
        self.assertIsNone(sense.take_pending())

    def test_regular_overhealth_decay_does_not_cause_a_retreat_every_second(self):
        sense = DamageSense(Pixels())
        for hp, tick in ((100, 0), (150, 4), (149, 400)):
            sense.watch(hp, tick)
        sense.take_pending()
        previous = sense.last_hit
        for hp, tick in ((148, 472), (147, 544), (146, 616)):
            sense.watch(hp, tick)
            self.assertIsNone(sense.take_pending())
            self.assertEqual(sense.last_hit, previous)
        sense.watch(132, 620)
        self.assertEqual(sense.take_pending()["to_hp"], 132)

    def test_retreat_has_backward_motion_with_a_released_jump(self):
        ticks = 36
        keys = []
        while ticks:
            n, held = input_chunk("evade_and_scan", ticks, (-280, 0, 0), 4)
            keys.extend([held] * n)
            ticks -= n
        self.assertEqual(
            keys,
            [(-280, 0, 0)] * 8
            + [(-280, 0, 2)] * 4
            + [(-280, 0, 0)] * 16
            + [(0, 0, 0)] * 8,
        )
