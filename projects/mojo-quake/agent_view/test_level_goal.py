"""A kill, an unrelated intermission or a decision count must not count as an E1M1 win."""

import unittest

from observatory import terminal_phase


class LevelGoalTests(unittest.TestCase):
    def test_only_the_exit_or_destination_completes_the_level(self):
        state = {"map": "e1m1", "hp": "88", "intermission": "0", "kills": "1/23"}
        self.assertIsNone(terminal_phase(state, 121, None))
        self.assertEqual(terminal_phase(state, 120, 120), "Step limit reached")
        self.assertEqual(terminal_phase(dict(state, hp="0"), 22, None), "Player died")
        self.assertIsNone(
            terminal_phase(dict(state, map="start", intermission="1"), 1, None)
        )
        self.assertEqual(
            terminal_phase(dict(state, intermission="1"), 120, 120), "Level complete"
        )
        self.assertEqual(
            terminal_phase(dict(state, map="e1m2"), 131, None), "Level complete"
        )


class ScreenTerminationTests(unittest.TestCase):
    def test_saved_player_reloads_from_visible_death_and_stops_on_results_screen(self):
        from types import SimpleNamespace
        from observatory import screen_outcome
        live = SimpleNamespace(completed=lambda image: image == b"results", read=lambda image: -7)
        self.assertEqual(screen_outcome(b"game", live), "Player died")
        self.assertIsNone(screen_outcome(b"game", live, book=SimpleNamespace(saved={1: True})))
        self.assertEqual(screen_outcome(b"results", live, book=SimpleNamespace(saved={1: True})), "Level complete")


class HandoffTests(unittest.TestCase):
    def test_camera_wait_advances_the_engine_without_drifting_off_the_forecast(self):
        from lookahead import Option
        rows = Option(80, "watch_passage", 12).rows(80, -4)
        self.assertEqual(sum(r[0] for r in rows), 12)
        self.assertTrue(all(r[1:4] == (0, 0, 0) and r[4:6] == (80, -4) for r in rows))
