import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
from hud import NoticeFont
from models import candidate_inputs, game_input, resolve_proposal
from navigation import RouteMemory
from PIL import Image
from weapon_poses import WeaponPoses


class VisibleHudTests(unittest.TestCase):
    def test_ammo_empty_cannot_choose_a_ranged_attack(self):
        nav = RouteMemory().guidance(None)
        nav["hud"] = {"active_ammo": 0}
        vision = {"enemy": [48, 55], "route": None}
        for action in ("fire", "aim_fire", "advance_fire", "shoot_switch"):
            self.assertNotIn(action, candidate_inputs([], nav))
            op, _, _ = resolve_proposal((action, "opponent"), vision, [], nav)
            if action != "shoot_switch":
                self.assertEqual(op, "bypass_enemy")
            self.assertEqual(game_input(op, vision)[3], 0)

    def test_legible_centered_message_and_plain_background(self):
        rng = np.random.default_rng(83)
        atlas = np.zeros((128, 128), dtype=np.uint8)
        for char in range(33, 127):
            stamp = rng.choice([0, 0, 0, 50, 100, 140, 175], (8, 8)).astype(np.uint8)
            atlas[
                char // 16 * 8 : char // 16 * 8 + 8, char % 16 * 8 : char % 16 * 8 + 8
            ] = stamp
        palette = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, axis=1)
        font = NoticeFont(atlas.tobytes(), palette.tobytes())
        screen = np.full((240, 320), 24, np.uint8)

        def encoded():
            stream = io.BytesIO()
            Image.fromarray(screen).save(stream, "JPEG", quality=85)
            return stream.getvalue()

        self.assertEqual(font.read(encoded()), "")
        text = "This door opens elsewhere"
        for i, char in enumerate(text):
            c = ord(char)
            x = (320 - 8 * len(text)) // 2 + 8 * i
            stamp = atlas[c // 16 * 8 : c // 16 * 8 + 8, c % 16 * 8 : c % 16 * 8 + 8]
            patch = screen[84:92, x : x + 8]
            patch[stamp != 0] = stamp[stamp != 0]
        self.assertEqual(font.read(encoded()), text)

    def test_foreground_requires_matching_appearance(self):
        rng = np.random.default_rng(124)
        mask = np.zeros((1, 48, 80), bool)
        mask[0, 25:44, 36:51] = True
        texture = rng.integers(5, 190, (1, 48, 80), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "poses.npz"
            np.savez_compressed(archive, masks=mask, gray=texture)
            poses = WeaponPoses(archive)
        world = (
            Image.fromarray(texture[0])
            .convert("RGB")
            .resize((320, 192), Image.Resampling.NEAREST)
        )
        boxes = np.array([[169, 139, 32, 32], [35, 139, 32, 32]])
        seen = poses.foreground(world, boxes[:, :2])
        self.assertIsNotNone(seen)
        self.assertEqual(poses.covers(seen, boxes).tolist(), [True, False])
        self.assertIsNone(poses.foreground(Image.new("RGB", (320, 192)), boxes[:, :2]))


class ScoreboardTests(unittest.TestCase):
    def test_solo_scoreboard_requires_both_fixed_display_labels(self):
        rng = np.random.default_rng(415)
        sheet = rng.choice([0, 0, 0, 70, 125, 170], (128, 128)).astype(np.uint8)
        sheet[16:24, :8] = 0
        palette = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, axis=1)
        font = NoticeFont(sheet.tobytes(), palette.tobytes())
        frame = np.full((240, 320), 18, dtype=np.uint8)
        for row, line in enumerate(("Monsters:", "Secrets :")):
            for i, char in enumerate(line):
                y, x = divmod(ord(char), 16)
                stamp = sheet[y*8:y*8+8, x*8:x*8+8]
                patch = frame[220+8*row:228+8*row, 8+8*i:16+8*i]
                patch[stamp > 0] = stamp[stamp > 0]
            self.assertEqual(font.solo_scoreboard(Image.fromarray(frame)), row == 1)
        self.assertFalse(font.solo_scoreboard(Image.fromarray(np.roll(frame, 12, axis=0))))
