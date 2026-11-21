import unittest

import numpy as np
from hud import DamageSense
from targets import CharacterTrack


class CharacterTrackTests(unittest.TestCase):
    def setUp(self):
        self.track = CharacterTrack(None)
        self.patch = np.random.default_rng(21).integers(
            10, 245, (25, 25), dtype=np.uint8
        )
        self.image = np.full((192, 320), 15, dtype=np.uint8)
        self.image[84:109, 68:93] = self.patch
        self.track.remember(self.image, [25, 40], [32, 36], 100, 0, 0, 0.82)

    def test_verified_image_bridges_a_missed_sample(self):
        second = np.roll(self.image, 4, axis=1)
        hit = self.track.locate(second, 104, 0, 0)
        self.assertEqual(hit["source"], "RGB patch")
        self.assertAlmostEqual(hit["point"][0], 26.25, places=1)
        self.assertIsNone(self.track.locate(second, 117, 0, 0))

    def test_occluded_or_offscreen_target_releases_lock(self):
        self.assertIsNone(self.track.locate(np.zeros_like(self.image), 104, 0, 0))
        self.assertIsNone(self.track.locate(self.image, 104, 120, 0))

    def test_sideways_motion_expires_after_a_hit(self):
        sense = DamageSense(None)
        self.assertEqual(sense.strafe_after_hit(200), 0)
        sense.last_hit = 200
        self.assertEqual(abs(sense.strafe_after_hit(204)), 235)
        self.assertNotEqual(sense.strafe_after_hit(204), sense.strafe_after_hit(246))
        self.assertEqual(sense.strafe_after_hit(311), 0)
