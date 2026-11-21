import json
import unittest
from pathlib import Path

import cv2
import httpx
import numpy as np

from game import Game
from models import CLOUD_MODELS, Models
from route_guide import PROJECT, STAGES, RouteAtlas, RouteGuide


class PlannerReferenceTests(unittest.TestCase):
    def test_reference_image_is_separate_from_live_marker_coordinates(self):
        provider = Models("mock", single_call=True, cloud_model=CLOUD_MODELS["minimax"])
        provider.close()
        bodies = []

        def respond(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "{}"}}]}
            )

        provider.cloud = httpx.Client(
            base_url="https://localhost", transport=httpx.MockTransport(respond)
        )
        self.addCleanup(provider.close)
        provider._read_frame(b"live", "test", 100, reference=b"reference")
        provider._read_frame(b"live", "test", 100)
        parts = bodies[0]["messages"][0]["content"]
        self.assertIn("first image", parts[2]["text"])
        self.assertNotEqual(parts[1]["image_url"], parts[3]["image_url"])
        self.assertEqual(len(bodies[1]["messages"][0]["content"]), 2)


class NativeGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = PROJECT / "build/host/tyr-quake"
        cls.media = Path.home() / "Library/Application Support/Mojo Quake/media"
        if not (cls.binary.exists() and (cls.media / "id1/pak0.pak").exists()):
            raise unittest.SkipTest("Native Quake and local shareware media required")
        cls.atlas = RouteAtlas(cls.binary, cls.media)

    def test_entrance_ledge_and_unrecognized_view(self):
        guide = RouteGuide(self.atlas)
        game = Game(self.binary, self.media)
        try:
            frame, _, _ = game.move(24)
            first = guide.observe(frame, game.yaw, game.pitch)
        finally:
            game.close()
        self.assertEqual(
            (first["stage"], first["matched"], first["suggested"]),
            (1, True, "follow_route"),
        )
        self.assertAlmostEqual(first["route"][0], 50, delta=3)
        self.assertEqual(len(self.atlas.photos), len(STAGES) + 2)
        ledge = guide.observe(
            self.atlas.photos[0], self.atlas.ledge_yaw, self.atlas.ledge_pitch
        )
        self.assertEqual(ledge["suggested"], "jump_forward")
        self.assertAlmostEqual(ledge["landing"][1], 42, delta=1)
        image = cv2.imencode(".jpg", np.zeros((240, 320), dtype=np.uint8))[1].tobytes()
        for _ in range(6):
            unclear = guide.observe(image, 90, 0)
            self.assertFalse(unclear["matched"])
            self.assertIsNone(unclear["suggested"])
        self.assertEqual(first["reference_tick"], unclear["reference_tick"])

    def test_reload_returns_to_own_checkpoint_section(self):
        guide = RouteGuide(self.atlas)
        guide.index = 5
        guide.checkpoint(1, False)
        guide.index = 55
        guide.checkpoint(1, True)
        self.assertEqual(guide.index, 5)
        self.assertFalse(guide.context)

    def test_distant_panorama_cannot_move_entrance_to_exit_after_lost_frames(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from route_guide import AZ, EL, Sample, patch

        unknown = cv2.imencode(".jpg", np.zeros((240, 320), dtype=np.uint8))[
            1
        ].tobytes()
        distant = self.atlas.photos[3539]
        rings = np.zeros((80, len(EL), 180), dtype=np.float32)
        heading = 90
        cols = ((heading + AZ) // 2) % 180
        rings[-1][:, cols] = patch(distant, AZ)
        positions = np.array([[i * 40, 0, 0] for i in range(80)])
        atlas = SimpleNamespace(
            samples=[Sample(403 + 40 * i, pos) for i, pos in enumerate(positions)],
            positions=positions,
            view_indexes=np.arange(80),
            view_positions=positions,
            rings=rings,
            features=Mock(locate=Mock(return_value=None)),
            ledge_yaw=0,
        )
        guide = RouteGuide(atlas)
        for frame in [unknown] * 4 + [distant]:
            hint = guide.observe(frame, heading, 0)
            self.assertFalse(hint["matched"])
            self.assertEqual(hint["stage"], 1)
