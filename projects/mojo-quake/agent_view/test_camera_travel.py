import io
import unittest
from types import SimpleNamespace

import numpy as np
from landmarks import Landmark, PanelScout, ground_vision, validated_marker
from mechanisms import MechanismMemory
from navigation import Place, RouteMemory
from PIL import Image
from scene_lanes import SceneEstimator
from survey import BoundaryTravel
from targets import UnresponsivePoses


def encoded(image):
    file = io.BytesIO()
    Image.fromarray(image).save(file, "JPEG", quality=94)
    return file.getvalue()


class CameraTravelTests(unittest.TestCase):
    def test_prone_pose_requires_evidence_and_releases_on_change(self):
        rng = np.random.default_rng(62)
        image = rng.integers(0, 150, (192, 320), dtype=np.uint8)
        det = {"point": [50, 50], "size_px": [100, 44]}
        guard = UnresponsivePoses()
        self.assertFalse(guard.reject(image, det, 0, 20, 0, False, 15))
        for tick in range(4, 56, 4):
            self.assertFalse(guard.reject(image, det, tick, 20, 0, True, 14))
        self.assertTrue(guard.reject(image, det, 64, 20, 0, True, 13))
        self.assertFalse(
            guard.reject(
                rng.integers(0, 150, (192, 320), dtype=np.uint8),
                det,
                68,
                20,
                0,
                False,
                13,
            )
        )
        clipped = {"point": [50, 73], "size_px": [100, 44]}
        self.assertFalse(guard.reject(image, clipped, 72, 20, 0, True, 12))

    def test_marker_must_match_current_pixels(self):
        rng = np.random.default_rng(2)
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        image[62:99, 100:137, 0] = rng.integers(10, 210, (37, 37), dtype=np.uint8)
        marker = validated_marker({"kind": "touch_button", "point": [37, 33]})
        anchor = Landmark(encoded(image), marker, 90, 0)
        shifted = np.roll(image, 8, axis=1)
        found = anchor.locate(encoded(shifted), 90, 0)
        self.assertAlmostEqual(found["point"][0], 39.5, delta=0.5)
        vision = {}
        ground_vision(vision, found)
        self.assertEqual(vision["switch"], found["point"])
        self.assertIsNone(anchor.locate(encoded(np.zeros_like(image)), 90, 0))
        self.assertIsNone(anchor.locate(encoded(image), 240, 0))
        self.assertIsNone(validated_marker({"kind": "landing", "point": [30, 99]}))

    def test_isolated_visual_mark_needs_two_samples_and_has_a_retry_delay(self):
        image = np.full((240, 320, 3), 16, dtype=np.uint8)
        yy, xx = np.mgrid[:240, :320]
        image[abs(yy - 98) + abs(xx - 132) <= 8] = [155, 4, 5]
        scout = PanelScout()
        jpg = encoded(image)
        scout.observe(jpg, 8, 0, 0)
        self.assertIsNone(scout.eligible(8, 0))
        scout.observe(jpg, 16, 0, 0)
        self.assertIsNotNone(scout.eligible(16, 0))
        scout.commit(16)
        self.assertIsNone(scout.eligible(16, 0))
        scout.observe(encoded(np.full_like(image, 16)), 24, 0, 0)
        self.assertIsNone(scout.candidate)

    def test_steering_uses_the_clear_lane_without_reversing_every_sample(self):
        travel = BoundaryTravel(0, 0, 1)
        g = SimpleNamespace(yaw=0, pitch=0, tick=80)
        lanes = {
            "pick": "left",
            "source_yaw": 0,
            "lanes": {
                "center": {"range_estimate": 60},
                "left": {"range_estimate": 190},
                "right": {"range_estimate": 120},
            },
        }
        self.assertTrue(travel.use_lane(lanes, g))
        self.assertEqual(travel.controls(g, 4)[0], 320)
        self.assertGreater(g.yaw, 0)
        self.assertFalse(travel.use_lane(dict(lanes, pick="right"), g))

    def test_monocular_route_uses_camera_data_and_reports_insufficient_view(self):
        surface = np.ones((192, 320), dtype=np.float32)
        surface[:, 220:290] = 0.3
        self.assertEqual(SceneEstimator.directions(surface, 0)["pick"], "right")
        self.assertEqual(SceneEstimator.directions(surface, 65)["pick"], "scan")


class DoorTaskTests(unittest.TestCase):
    def test_unrelated_mark_does_not_send_player_back_to_a_locked_door(self):
        memory = MechanismMemory()
        memory.see_notice("This door opens elsewhere...", 40, 0, 1, "")
        receipt = {
            "panorama_plan": {"kind": "shoot_button"},
            "alternatives": [{"marked_input": False}],
        }
        memory.tested(
            {"action": "test_control", "ticks": 96, "seq": 4, "lookahead": receipt}, 400
        )
        self.assertEqual(memory.tests, 0)
        self.assertEqual(memory.status, "find_control")

    def test_notice_survives_a_view_change_and_control_needs_a_return_test(self):
        task = MechanismMemory()
        self.assertFalse(task.see_notice("You found a secret area!", 40, 0, 2, ""))
        self.assertTrue(
            task.see_notice("This door opens elsewhere...", 80, 0, 2, "stone doorway")
        )
        self.assertTrue(task.departure(84))
        self.assertFalse(task.departure(88))
        self.assertFalse(task.see_notice("This door opens elsewhere...", 92, 1, 3, ""))
        m = RouteMemory()
        m.places.append(Place(1, 0))
        m.places[0].exits[2] = 1
        m.here = 1
        self.assertIsNone(task.direction(m, 100))
        task.tested(
            {"action": "inspect_panel", "note": "", "ticks": 96, "seq": 20}, 260
        )
        self.assertEqual(task.direction(m, 265), 6)
        m.here = 0
        self.assertEqual(task.direction(m, 270), 2)
        task.after_load()
        self.assertIsNone(task.direction(m, 280))
        self.assertIn("Explore", task.context()["objective"])
