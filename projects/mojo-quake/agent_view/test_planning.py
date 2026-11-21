import io
import json
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import httpx
from navigation import RouteMemory
from PIL import Image
from planning import LocalPlayer, ModularGemmaPlayer, PlanFeed, read_plan
from recordings import PlanTimeline


class Pool:
    def submit(self, *_args):
        self.job = Future()
        self.job.set_running_or_notify_cancel()
        return self.job


class Provider:
    cloud_model = "MiniMaxAI/MiniMax-M3.1-Flash"

    def _read_frame(self, *_):
        return {
            "intent": "disengage",
            "next_input": "back_up",
            "character": "fallen",
            "objective": "Move past the body.",
            "evidence": "A prone figure lies beside the wall.",
            "success": "A different passage comes into view.",
            "reasoning_content": "private provider field",
        }


class PlannerTests(unittest.TestCase):
    def test_gemma_game_frame_turn_is_available_on_a_guided_step(self):
        player = ModularGemmaPlayer("test")
        player.close()
        bodies = []
        def respond(request):
            bodies.append(json.loads(request.content))
            answer = {"action": "turn_right", "sighting": "live", "region": "right"}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})
        player.http = httpx.Client(base_url="https://localhost", transport=httpx.MockTransport(respond))
        self.addCleanup(player.close)
        nav = {"prepared_route": {"objective": "Follow the corridor.", "suggested": "follow_route"}}
        decision, sighting = player.choose_with_frame([], nav, b"frame")
        self.assertEqual(decision[:3], ("turn_right", "untried", "Modular Gemma"))
        self.assertEqual(sighting, {"sighting": "live", "region": "right"})
        content = bodies[0]["messages"][-1]["content"]
        self.assertEqual(content[1]["image_url"]["url"], "data:image/jpeg;base64,ZnJhbWU=")
        self.assertIn("turn_right", json.loads(content[0]["text"])["choices"])
        decision, sighting = player.choose_with_frame([], dict(nav, blocked_inputs=["turn_right"]), b"frame")
        self.assertEqual(decision[2], "Local fallback")
        self.assertIsNone(sighting)

    def test_gemma_on_demand_frame_timing(self):
        from observatory import GemmaFrameChecks
        checks = GemmaFrameChecks()
        self.assertTrue(checks.request(24, None))
        self.assertIsNone(checks.request(40, None))
        self.assertTrue(checks.request(48, 4))
        self.assertIsNone(checks.request(52, 1))
        checks.confirm = True
        self.assertEqual(checks.request(58, None), "After a camera turn")
        self.assertIsNone(checks.request(75, None))
        self.assertTrue(checks.request(130, None))

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        (self.dir / "frames").mkdir()
        self.pool = Pool()
        self.plan = PlanFeed(Provider(), self.pool, self.dir)
        self.game = SimpleNamespace(tick=24, yaw=90, pitch=0)
        self.memory = RouteMemory()
        out = io.BytesIO()
        Image.new("RGB", (320, 240), (46, 38, 32)).save(out, "JPEG")
        self.frame = out.getvalue()
        self.plan.tick(self.game, self.frame, self.memory)
        self.plan.request_if_needed(self.game, self.frame, 1, self.memory, None, [])
        self.response = read_plan(Provider(), self.frame, {})

    def test_source_receipt_and_replay_follow_real_ticks(self):
        self.assertIsNone(self.plan.active())
        self.assertNotIn("reasoning_content", self.response)
        self.assertEqual((self.dir / "frames/24.jpg").read_bytes(), self.frame)
        self.pool.job.set_result(self.response)
        self.game.tick = 104
        self.plan.tick(self.game, self.frame, self.memory)
        self.assertEqual(self.plan.active()["status"], "Available")
        self.plan.receipt(24, 4, 108, "back_up", "Mac local model")
        self.assertEqual(self.plan.active()["applied_step"], 4)
        timeline = PlanTimeline(self.dir / "planner.jsonl")
        self.assertEqual(timeline.at(23), {})
        self.assertEqual(timeline.at(24)["status"], "Reviewing")
        self.assertEqual(timeline.at(104)["status"], "Available")
        self.assertEqual(timeline.at(108)["status"], "Input matched")
        self.game.tick = 110
        self.game.yaw = 270
        self.plan.tick(self.game, self.frame, self.memory)
        self.assertIsNone(self.plan.active())

    def test_late_scene_specific_advice_and_reloaded_world_are_rejected(self):
        self.pool.job.set_result(self.response)
        self.game.yaw = 220
        self.plan.tick(self.game, self.frame, self.memory)
        self.assertEqual(self.plan.records[-1]["status"], "Discarded")
        self.game.tick = 1200
        self.plan.request_if_needed(self.game, self.frame, 5, self.memory, None, [])
        self.plan.invalidate("Loaded", 1203)
        self.pool.job.set_result(self.response)
        self.plan.tick(self.game, self.frame, self.memory)
        self.assertIsNone(self.plan.active())
        self.assertEqual(self.plan.records[-1]["status"], "Expired")

    def test_failed_provider_releases_the_worker_for_retry(self):
        self.pool.job.set_exception(httpx.ReadTimeout("timeout"))
        self.plan.tick(self.game, self.frame, self.memory)
        self.assertEqual(self.plan.records[-1]["status"], "Failed")
        self.assertIsNone(self.plan.job)

    def test_local_model_receives_the_objective_and_has_a_labelled_fallback(self):
        captured = []
        player = LocalPlayer("http://127.0.0.1:61375")
        player.close()

        def choose(request):
            captured.append(json.loads(request.content))
            return httpx.Response(
                200, json={"answers": {"action": {"choice": "turn_left"}}}
            )

        player.http = httpx.Client(
            base_url="http://127.0.0.1:61375", transport=httpx.MockTransport(choose)
        )
        nav = self.memory.guidance(None)
        nav["strategy"] = self.response
        self.assertEqual(
            player.choose([], nav)[:3], ("turn_left", "untried", "Mac local model")
        )
        self.assertIn(self.response["objective"], captured[0]["state"])
        player.close()
        player.http = httpx.Client(
            base_url="http://127.0.0.1:61375",
            transport=httpx.MockTransport(lambda _: httpx.Response(503)),
        )
        self.addCleanup(player.close)
        self.assertEqual(player.choose([], nav)[2], "Local fallback")

    def test_wall_feedback_constrains_model_and_fallback_even_with_a_planner_marker(self):
        player = LocalPlayer("http://127.0.0.1:61375")
        player.close()
        payloads = []

        def respond(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"answers": {"action": {"choice": "advance"}}})

        player.http = httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(respond))
        self.addCleanup(player.close)
        nav = {
            "blocked_inputs": ["advance", "follow_route", "back_up"],
            "grounded": {"kind": "passage"}, "camera_lanes": "center",
            "movement_lesson": {"advice": "Two forward walks at this place stalled."},
            "past_traversal": ["stalled_forward: strafe_left changed the settled view in 4/5 trials"],
            "strategy": {"objective": "Take the passage.", "next_input": "advance"}
        }
        action, _, source, _ = player.choose([], nav)
        offered = payloads[0]["questions"]["action"]["criteria"]
        self.assertTrue(set(nav["blocked_inputs"]).isdisjoint(offered))
        self.assertIn("strafe_left", offered)
        self.assertIn(nav["movement_lesson"]["advice"], payloads[0]["state"])
        self.assertIn(nav["past_traversal"][0], payloads[0]["state"])
        self.assertEqual(source, "Local fallback")
        self.assertIn(action, offered)

    def test_modular_gemma_receives_planner_memory_and_validates_its_move(self):
        player = ModularGemmaPlayer("test")
        player.close()
        calls = []
        def respond(request):
            calls.append(json.loads(request.content))
            action = "turn_left" if len(calls) == 1 else "advance"
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"action": action})}}]})
        player.http = httpx.Client(base_url="https://api.modular.com", transport=httpx.MockTransport(respond))
        self.addCleanup(player.close)
        nav = {"blocked_inputs": ["advance"], "strategy": self.response, "past_traversal": ["Forward stalled twice."]}
        self.assertEqual(player.choose([], nav)[:3], ("turn_left", "untried", "Modular Gemma"))
        self.assertEqual(calls[0]["model"], "google/gemma-4-31b-it")
        state = json.loads(calls[0]["messages"][-1]["content"])["state"]
        self.assertIn(self.response["objective"], state)
        self.assertIn("Forward stalled twice.", state)
        self.assertNotIn("advance", calls[0]["response_format"]["json_schema"]["schema"]["properties"]["action"]["enum"])
        self.assertEqual(player.choose([], nav)[2], "Local fallback")
