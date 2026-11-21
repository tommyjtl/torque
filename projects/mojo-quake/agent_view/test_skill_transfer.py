import tempfile
import unittest
from pathlib import Path

from skills import SkillBook


class TransferTests(unittest.TestCase):
    def test_only_generic_repeated_movement_evidence_survives_a_new_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = SkillBook(root)
            first.record("too_low", "back_up", True)
            first.record("too_low", "back_up", False)
            self.assertEqual(first.hints(), [])
            first.record("too_low", "back_up", True)
            first.record("secret place name", "back_up", True)
            first.record("too_low", "map coordinate", True)
            second = SkillBook(root)
            self.assertEqual(
                second.hints("too_low"),
                ["too_low: back_up changed the settled view in 2/3 trials"],
            )
            self.assertEqual(second.hints("jump_up"), [])


class MovementLessonTests(unittest.TestCase):
    @staticmethod
    def scene():
        import io
        import numpy as np
        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(np.random.default_rng(15).integers(0, 180, (240, 320), dtype=np.uint8)).save(buf, "JPEG")
        return buf.getvalue()

    def test_shadow_observes_without_interrupting_and_waiting_is_not_a_stall(self):
        from movement_lessons import MovementLessons
        image = self.scene()
        state = MovementLessons("shadow")
        for tick in range(4, 40, 4):
            state.observe(image, tick, 4, 20, 0, 320, 0, 0, 0, True)
        self.assertTrue(state.pending)
        self.assertFalse(state.recovery_due(40))
        self.assertAlmostEqual(state.recovery(40, 20, "right"), 300)
        state.reset()
        for tick in range(4, 120, 4):
            state.observe(image, tick, 4, 20, 0, 0, 0, 0, 0, False)
        self.assertIsNone(state.context(120))

    def test_backstep_precedes_turn_and_expires_after_relocation(self):
        from lookahead import Option
        from movement_lessons import MovementLessons
        image = self.scene()
        state = MovementLessons("active")
        for tick in range(4, 33, 4):
            state.observe(image, tick, 4, 90, 0, 320, 0, 0, 0, True)
        self.assertTrue(state.recovery_due(32))
        heading = state.recovery(32, 90, "left")
        rows = Option(heading, "clear_corner", 42).rows(90, 0)
        self.assertLess(rows[0][1], 0)
        self.assertEqual(rows[-1][4], 170)
        self.assertFalse(state.recovery_due(32))
        state.reset()
        self.assertIsNone(state.context(32))
