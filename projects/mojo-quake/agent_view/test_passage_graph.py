import io
import unittest

import cv2
import numpy as np
from landmarks import aim_angles
from lift_camera import classify
from lookahead import Option, PreviewSearch, untested_lanes
from PIL import Image
from place_recognition import PlaceCamera
from targets import combat_motion


class PlaceRecognitionTests(unittest.TestCase):
    @staticmethod
    def camera_sample(camera, seed, shifted=False):
        rng = np.random.default_rng(seed)
        images = []
        tiles = []
        for _ in range(4):
            pixels = rng.integers(0, 255, (240, 320), dtype=np.uint8)
            if shifted:
                pixels = np.roll(pixels, (4, 6), axis=(0, 1))
            buf = io.BytesIO()
            Image.fromarray(pixels).save(buf, "JPEG", quality=88)
            images.append(buf.getvalue())
            tiles.append(
                cv2.resize(
                    pixels[12:161, 8:312], (24, 15), interpolation=cv2.INTER_AREA
                ).astype(np.float32)
            )
        return camera.landmark(tiles, images)

    def test_similar_brightness_requires_corresponding_landmarks(self):
        camera = PlaceCamera()
        source = self.camera_sample(camera, 79)
        actual_return = self.camera_sample(camera, 79, shifted=True)
        similar_tone = self.camera_sample(camera, 120)
        known = [source]
        self.assertEqual(camera.locate(actual_return, known, expected=0), 0)
        self.assertEqual(camera.locate(similar_tone, known, expected=0), 1)

    def test_aiming_above_or_below_center_includes_vertical_angle(self):
        yaw, up = aim_angles([73, 31], 270)
        _, down = aim_angles([73, 64], 270)
        self.assertLess(yaw, 270)
        self.assertLess(up, -10)
        self.assertGreater(down, 8)
        rows = Option(yaw, "test_control", pitch=up).rows(270, 0)
        pressing = [row for row in rows if row[-1] & 1]
        self.assertTrue(pressing)
        self.assertTrue(all(row[1] == 0 and row[5] == up for row in pressing))

    def test_progressive_trials_cover_unsampled_sector_and_change_stride(self):
        basis = [Option(angle) for angle in (0, 90, 180, 270)]
        seen = {0: (2, True), 18: (1, False)}
        first = untested_lanes(seen, basis, 7)
        for opt in first:
            seen[round(opt.heading / 5) % 72] = (1, True)
        second = untested_lanes(seen, basis, 8)
        self.assertEqual(len({opt.heading for opt in first + second}), 4)
        self.assertNotEqual(first[0].duration, first[1].duration)

    def test_matched_runup_keeps_walking_through_landing(self):
        for launch in (6, 18, 36):
            rows = Option(90, "jump", 100, launch_tick=launch).rows(90, 0)
            elapsed = 0
            pressed = []
            for n, forward, _, _, _, _, buttons in rows:
                self.assertGreater(forward, 0)
                if buttons & 2:
                    pressed.extend(range(elapsed, elapsed + n))
                elapsed += n
            self.assertEqual(pressed, list(range(launch, launch + 4)))
            self.assertEqual(elapsed, 100)

    def test_motion_continues_when_a_visual_detection_is_briefly_lost(self):
        self.assertEqual(combat_motion(None, 85, 0), (-145, 245))
        self.assertEqual(combat_motion({"size_px": (15, 20)}, 85, 52), (65, -245))
        self.assertEqual(combat_motion({"size_px": (15, 20)}, 17, 0), (-185, 245))
        self.assertEqual(
            combat_motion({"size_px": (15, 20)}, 85, 0, retreat=True), (-270, 245)
        )

    def test_a_rising_platform_is_held_before_the_turn_to_exit(self):
        self.assertEqual(classify([[5, 8, None, 0]] * 6)["direction"], "rising")
        self.assertEqual(classify([[5, None, None, 0]] * 6)["direction"], "unconfirmed")
        rows = Option(90, "ride_to_landing", 136).rows(0, 0)
        self.assertEqual(sum(r[0] for r in rows if r[4] == 0 and r[1] == 0), 96)
        self.assertEqual(sum(r[0] for r in rows if r[1] > 0), 40)
        self.assertTrue(all(r[4] == 90 for r in rows if r[1] > 0))
        wait = Option(90, "hold_for_lift", 96).rows(0, 0)
        self.assertTrue(all(r[1:4] == (0, 0, 0) for r in wait))
        self.assertEqual(sum(r[0] for r in wait), 96)

    def test_interrupted_marked_input_remains_available(self):
        search = PreviewSearch(None)
        self.addCleanup(search.close)
        guide = {"source_tick": 36, "landmark_id": 29, "kind": "shoot_button"}
        event = {
            "input_source": "Own-save lookahead",
            "ticks": 8,
            "action": "test_control",
            "lookahead": {
                "panorama_plan": guide,
                "alternatives": [{"marked_input": True}],
            },
        }
        search.record_input(
            dict(event, lookahead_interrupted="Visible character acquired")
        )
        self.assertFalse(search.book.interactions)
        search.record_input(event)
        self.assertEqual(
            search.book.interactions[((29, "shoot_button"), "test_control")], 1
        )
