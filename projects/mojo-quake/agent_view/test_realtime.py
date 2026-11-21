"""Exercise the game clock while inference is blocked or returns too late."""

import io
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from observatory import Observatory, expired_action
from PIL import Image


class ClockGame:
    """Deterministic replacement for the native movement pipe."""

    def __init__(self, *_args, **_kwargs):
        self.tick = self.yaw = self.pitch = 0
        buffer = io.BytesIO()
        Image.new("RGB", (320, 240)).save(buffer, "JPEG")
        self.image = buffer.getvalue()

    def move(self, ticks, forward=0, side=0, buttons=0, *, evaluate=False):
        self.tick += ticks
        state = {
            "map": "e1m1",
            "hp": "100",
            "kills": "0/23",
            "intermission": "0",
            "pos": "0,0,0",
            "hash": str(self.tick),
        }
        return self.image, state, f"{ticks} {forward} {side} 0 0 0 {buttons} 0"

    def close(self):
        pass


class GatedModels:
    def __init__(self):
        self.vision = threading.Event()
        self.decision = threading.Event()

    def observe(self, _frame):
        if not self.vision.wait(8):
            raise AssertionError("Vision gate timed out")
        return {"scene": "Hallway", "enemy": None, "route": None}

    def decide(self, _vision, _recent, _navigation):
        if not self.decision.wait(8):
            raise AssertionError("Decision gate timed out")
        return "advance", "Open passage"


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(tmp)
        self.enterContext(patch("observatory.Game", ClockGame))
        self.enterContext(patch("observatory.Recordings"))
        self.models = GatedModels()
        args = SimpleNamespace(
            records=self.root,
            media=self.root,
            binary=self.root / "game",
            gpu=False,
            limit=1,
            resume_session=None,
        )
        self.app = Observatory(args, self.models)
        self.addCleanup(self.app.close)
        self.addCleanup(self.models.decision.set)
        self.addCleanup(self.models.vision.set)
        self.wait(lambda: self.app.ready)

    def wait(self, predicate, timeout=4):
        with self.app.cv:
            self.assertTrue(self.app.cv.wait_for(predicate, timeout), self.app.phase)

    def test_clock_runs_in_both_stages_and_inputs_expire_at_end_of_hold(self):
        start = self.app.tick
        self.app.command("play")
        self.wait(lambda: self.app.tick >= start + 12)
        self.assertEqual(self.app.phase, "Reading frame")
        self.models.vision.set()
        self.wait(lambda: self.app.phase == "Choosing action")
        observed = self.app.tick
        self.wait(lambda: self.app.tick >= observed + 12)
        self.models.decision.set()
        self.wait(lambda: self.app.ended)
        e = self.app.history[-1]
        self.assertEqual(e["observed_tick"], start)
        self.assertGreater(e["applied_tick"], e["vision_tick"])
        self.assertEqual(e["end_tick"] - e["applied_tick"], 27)
        rows = [
            line.split()
            for line in next(self.root.glob("session-*/inputs.trace"))
            .read_text()
            .splitlines()
        ]
        self.assertEqual(sum(int(r[0]) for r in rows if r[1] == "0"), e["applied_tick"])
        self.assertEqual(sum(int(r[0]) for r in rows if r[1] == "320"), 27)

    def test_single_call_applies_immediately_after_the_combined_reply(self):
        calls = []

        def combined(_jpeg, recent, navigation):
            calls.append((recent, navigation["place"]))
            self.models.vision.wait(4)
            return {"scene": "Clear corridor", "enemy": None, "route": None}, (
                "advance",
                "passage",
            )

        self.models.single_call = True
        self.models.observe_and_choose = combined
        self.app.command("play")
        self.wait(lambda: self.app.tick >= 36)
        self.assertEqual(self.app.phase, "Reading frame and choosing input")
        self.models.vision.set()
        self.wait(lambda: self.app.ended)
        event = self.app.history[-1]
        self.assertEqual(calls, [([], "P1")])
        self.assertEqual(event["controller"], "single-call")
        self.assertEqual(event["vision_tick"], event["applied_tick"])
        self.assertEqual(event["action"], "advance")
        self.assertGreater(event["inference_ms"], 0)
        self.assertIsNone(event["decision_ms"])

    def test_user_pause_cancels_an_outstanding_decision(self):
        self.app.command("play")
        self.models.vision.set()
        self.wait(lambda: self.app.phase == "Choosing action" and self.app.tick >= 40)
        self.app.command("pause")
        self.wait(lambda: not self.app.busy)
        event = self.app.history[-1]
        self.assertEqual(event["note"], "Run interrupted")
        self.assertIsNone(event["applied_tick"])
        tick = self.app.tick
        self.models.decision.set()
        with self.app.cv:
            self.assertFalse(self.app.cv.wait_for(lambda: self.app.tick != tick, 0.2))

    def test_death_ends_game_while_vision_is_pending(self):
        original = ClockGame.move

        def hit(game, *args, **kwargs):
            frame, state, row = original(game, *args, **kwargs)
            if game.tick >= 44:
                state["hp"] = "0"
            return frame, state, row

        with patch.object(ClockGame, "move", hit):
            self.app.command("play")
            self.wait(lambda: self.app.ended)
        self.assertEqual(self.app.phase, "Player died")
        self.assertEqual(self.app.tick, 44)
        self.assertIsNone(self.app.history[-1]["action"])
        self.assertIsNone(self.app.history[-1]["vision"])
        self.assertEqual(self.app.history[-1]["note"], "Game ended before input")

    def test_stale_decision_sends_no_input(self):
        with patch("observatory.expired_action", return_value=True):
            self.models.vision.set()
            self.app.command("step")
            self.wait(
                lambda: self.app.phase == "Choosing action" and self.app.tick >= 40
            )
            self.models.decision.set()
            self.wait(lambda: self.app.ended)
        event = self.app.history[-1]
        self.assertEqual(event["note"], "Expired")
        self.assertEqual(event["ticks"], 0)
        self.assertIsNone(event["applied_tick"])
        self.assertTrue(expired_action("aim_fire", 216, 0))
        self.assertTrue(expired_action("advance", 75, 14))
        self.assertFalse(expired_action("advance", 75, 2))
