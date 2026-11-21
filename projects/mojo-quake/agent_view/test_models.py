"""Regression tests for optional locations returned by cloud vision."""

import json
import unittest

import httpx
from models import Models, parse_observation, validate_choice


class ObservationTests(unittest.TestCase):
    def observation(self, **markers):
        return parse_observation(json.dumps({"scene": "A wall and a gap.", **markers}))

    def test_out_of_range_frame_remains_usable(self):
        result = self.observation(enemy=[105, 465], route=[315, 400])
        self.assertEqual(
            result,
            {
                "scene": "A wall and a gap.",
                "enemy": None,
                "route": None,
                "unlocated": ["enemy", "route"],
            },
        )

    def test_independent_marker_validation(self):
        for point in ([True, 1], [None, 50], [50], "null", [0, -2], [50, float("nan")]):
            with self.subTest(point=point):
                result = self.observation(enemy=point, route=[0, 100])
                self.assertEqual(result["route"], [0, 100])
                self.assertIsNone(result["enemy"])
                self.assertEqual(result["unlocated"], ["enemy"])

    def test_absent_and_explicit_null(self):
        self.assertEqual(self.observation(enemy=None)["unlocated"], ["route"])
        self.assertNotIn("unlocated", self.observation(enemy=[50, 50.25], route=None))
        with self.assertRaises(ValueError):
            parse_observation('{"scene": "", "enemy": null, "route": null}')


class SingleCallTests(unittest.TestCase):
    def test_one_request_uses_only_eligible_prior_inputs_and_rechecks_returned_targets(
        self,
    ):
        model = Models("test", single_call=True)
        self.addCleanup(model.close)
        model.cloud.close()
        sent = []

        def reply(request):
            sent.append(json.loads(request.content))
            text = json.dumps(
                {
                    "scene": "Doorway",
                    "enemy": None,
                    "route": [45, 50],
                    "action": "turn_left",
                    "cue": "explore",
                }
            )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": text}}]}
            )

        model.cloud = httpx.Client(
            base_url="https://example.invalid", transport=httpx.MockTransport(reply)
        )
        nav = {
            "pitch": 0,
            "blocked_inputs": ["back_up"],
            "recover": False,
            "escape_options": [],
        }
        recent = [{"action": "advance", "view_change_pct": 0}]
        frame, choice = model.observe_and_choose(b"frame", recent, nav)
        self.assertEqual(len(sent), 1)
        text, image = sent[0]["messages"][0]["content"]
        inputs = json.loads(text["text"].rsplit("\n", 1)[1])["actions"]
        self.assertNotIn("follow_route", inputs)
        self.assertNotIn("back_up", inputs)
        self.assertIn("turn_left", inputs)
        self.assertEqual(image["type"], "image_url")
        self.assertIsNone(model.mac)
        self.assertEqual(validate_choice(*choice, frame, recent, nav)[0], "turn_left")
        with self.assertRaises(ValueError):
            validate_choice("aim_fire", "opponent", frame, recent, nav)
