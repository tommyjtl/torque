"""Read character positions from the RGB playing area of a native Quake frame."""

import ast
import io
import math
import time

from PIL import Image


class GameCharacters:
    def __init__(self, weights, weapon_profile=None):
        import numpy as np
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 3
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(weights), options, providers=["CPUExecutionProvider"]
        )
        tensor = self.session.get_inputs()[0]
        outputs = self.session.get_outputs()[0].shape
        if tensor.shape != [1, 3, 320, 512] or outputs not in (
            [1, 84, 3360],
            [1, 5, 3360],
            [1, 6, 3360],
        ):
            raise ValueError("Expected a 512 × 320 YOLO11n character detector")
        self.quake_model = outputs[1] in (5, 6)
        self.fallen_class = outputs[1] == 6
        if self.quake_model:
            labels = ast.literal_eval(
                self.session.get_modelmeta().custom_metadata_map.get("names", "{}")
            )
            expected = (
                {0: "quake_monster", 1: "fallen_monster"}
                if self.fallen_class
                else {0: "quake_monster"}
            )
            if labels != expected:
                raise ValueError("Expected the single Quake monster class")
        self.name = "YOLO11n / Quake" if self.quake_model else "YOLO11n / COCO"
        self.input_name = tensor.name
        self.np = np
        self.weapon_poses = None
        self.foreground = None
        if weapon_profile:
            from weapon_poses import WeaponPoses

            self.weapon_poses = WeaponPoses(weapon_profile)

    def read(self, jpeg, accept=None):
        start = time.monotonic()
        with Image.open(io.BytesIO(jpeg)) as frame:
            if frame.size != (320, 240):
                raise ValueError("Expected a 320 × 240 Quake frame")
            world = frame.crop((0, 0, 320, 192)).convert("RGB")
        padded = Image.new("RGB", (512, 320), (114, 114, 114))
        padded.paste(world.resize((512, 307), Image.Resampling.BILINEAR), (0, 6))
        tensor = self.np.asarray(padded, dtype="float32").transpose(2, 0, 1)[None] / 255
        boxes = self.session.run(None, {self.input_name: tensor})[0][0]
        # The generic export uses its person and dog classes. The locally
        # trained game export has one class for active Quake monsters.
        confidence = boxes[4] if self.quake_model else boxes[[4, 20]].max(axis=0)
        if self.fallen_class:
            confidence = self.np.where(confidence > boxes[5], confidence, 0)
        self.foreground = None
        if self.weapon_poses:
            likely = self.np.flatnonzero(confidence >= 0.34)
            if likely.size:
                native = boxes[:4, likely].T.copy()
                native[:, 0] /= 1.6
                native[:, 1] = (native[:, 1] - 6) * 192 / 307
                native[:, 2] /= 1.6
                native[:, 3] *= 192 / 307
                self.foreground = self.weapon_poses.foreground(world, native[:, :2])
                if self.foreground is not None:
                    covered = self.weapon_poses.covers(self.foreground, native)
                    confidence[likely[covered]] = 0
        for _ in range(4):
            i = int(confidence.argmax())
            if confidence[i] < 0.34:
                return None
            x, y, width, height = (float(v) for v in boxes[:4, i])
            x /= 1.6
            y = (y - 6) * 192 / 307
            if not (0 <= x < 320 and 0 <= y < 192 and width >= 5 and height >= 8):
                return None
            result = {
                "point": [round(x / 3.2, 2), round(y / 2.4, 2)],
                "size_px": [round(width / 1.6, 1), round(height * 192 / 307, 1)],
                "confidence": round(float(confidence[i]), 3),
                "source": "detector",
                "model": self.name,
                "ms": round((time.monotonic() - start) * 1000, 1),
            }

            if accept is None or accept(result):
                result["ms"] = round((time.monotonic() - start) * 1000, 1)
                return result
            # Discard overlapping proposals for this body, keeping other visible characters eligible.
            center_x, center_y, box_w, box_h = boxes[:4, i]
            same = (self.np.abs(boxes[0] - center_x) < box_w * 0.45) & (
                self.np.abs(boxes[1] - center_y) < box_h * 0.45
            )
            confidence[same] = 0
        return None


class CharacterTrack:
    """Bridge short detector gaps with a verified patch from the same game camera."""

    def __init__(self, detector):
        self.detector = detector
        self.anchor = None
        self.poses = UnresponsivePoses()
        self.last_rejection = None

    @staticmethod
    def gray(jpeg):
        import cv2
        import numpy as np

        return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)[
            :192
        ]

    def remember(self, image, point, size, tick, yaw, pitch, confidence):
        cx, cy = round(point[0] * 3.2), round(point[1] * 2.4)
        rx = max(4, min(13, round(size[0] * 0.25)))
        ry = max(4, min(15, round(size[1] * 0.25)))
        if not (rx <= cx < 320 - rx and ry <= cy < 192 - ry):
            self.anchor = None
            return
        patch = image[cy - ry : cy + ry + 1, cx - rx : cx + rx + 1].copy()
        self.anchor = (
            (patch, cx, cy, tick, yaw, pitch, confidence) if patch.std() >= 7 else None
        )

    def locate(self, image, tick, yaw, pitch):
        import cv2

        if self.anchor is None:
            return None
        patch, cx, cy, stamp, ayaw, apitch, confidence = self.anchor
        if tick - stamp > 12:
            self.anchor = None
            return None
        az = math.atan((cx - 159.5) / 160) + math.radians(
            (yaw - ayaw + 180) % 360 - 180
        )
        el = math.atan((cy - 119.5) / 160) - math.radians(pitch - apitch)
        if abs(az) > 0.82 or abs(el) > 0.66:
            return None
        px, py = round(159.5 + 160 * math.tan(az)), round(119.5 + 160 * math.tan(el))
        h, w = patch.shape
        left, top = max(0, px - w // 2 - 17), max(0, py - h // 2 - 17)
        right, bottom = min(320, px + w // 2 + 18), min(192, py + h // 2 + 18)
        if right - left < w + 4 or bottom - top < h + 4:
            return None
        scores = cv2.matchTemplate(
            image[top:bottom, left:right], patch, cv2.TM_CCOEFF_NORMED
        )
        _, peak, _, (x, y) = cv2.minMaxLoc(scores)
        scores[max(0, y - 3) : y + 4, max(0, x - 3) : x + 4] = -1
        if peak < 0.76 or peak - float(scores.max()) < 0.045:
            return None
        return {
            "point": [
                round((left + x + w // 2) / 3.2, 2),
                round((top + y + h // 2) / 2.4, 2),
            ],
            "confidence": confidence,
            "source": "RGB patch",
            "match": round(peak, 3),
            "anchor_tick": stamp,
        }

    def read(self, jpeg, tick, yaw, pitch, *, fired=False, ammo=None):
        start = time.monotonic()
        gray = None
        self.last_rejection = None

        def accept(box):
            nonlocal gray
            if gray is None:
                gray = self.gray(jpeg)
            if self.poses.reject(gray, box, tick, yaw, pitch, fired, ammo):
                self.last_rejection = {
                    "tick": tick,
                    "point": box["point"],
                    "reason": "Unchanged prone silhouette after repeated attack inputs",
                }
                return False
            return True

        detection = self.detector.read(jpeg, accept=accept)
        if detection:
            self.remember(
                gray,
                detection["point"],
                detection["size_px"],
                tick,
                yaw,
                pitch,
                detection["confidence"],
            )
            return detection
        if self.last_rejection:
            self.anchor = None
        if self.anchor is None:
            return None
        result = self.locate(self.gray(jpeg), tick, yaw, pitch)
        if result and self.detector.foreground is not None:
            x, y = result["point"]
            if self.detector.foreground[
                min(47, round(y * 0.6)), min(79, round(x * 0.8))
            ]:
                self.anchor = None
                return None
        if result:
            result["ms"] = round((time.monotonic() - start) * 1000, 1)
        return result


def combat_motion(target, health, tick, *, retreat=False):
    """Ordinary Quake movement while the detector tracks or briefly reacquires a character."""
    side = 245 if tick // 52 % 2 == 0 else -245
    if retreat:
        return -270, side
    if target is None:
        return -145, side
    height = target.get("size_px", (0, 0))[1]
    return (-185 if health is not None and health < 50 or height >= 60 else 65), side


def track_character(point):
    """Bound mouse motion per four ticks. Shoot only when the new view is aligned."""
    x, y = point
    yaw = -math.degrees(math.atan((x - 50) / 50))
    pitch = math.degrees(math.atan((y - 50) * 0.015))
    turn = max(-14, min(14, yaw))
    lift = max(-10, min(10, pitch))
    aligned = abs(yaw - turn) < 5 and abs(pitch - lift) < 6
    return round(turn, 2), round(lift, 2), int(aligned)


class UnresponsivePoses:
    """Temporarily release a wide, fully visible silhouette unchanged through attack inputs."""

    def __init__(self):
        self.views = []

    def reject(self, image, detection, tick, yaw, pitch, fired, ammo):
        import cv2

        x, y = detection["point"][0] * 3.2, detection["point"][1] * 2.4
        w, h = detection["size_px"]
        if (
            w < 1.32 * h
            or h < 10
            or x - w / 2 < 2
            or x + w / 2 > 318
            or y - h / 2 < 2
            or y + h / 2 >= 190
        ):
            return False
        x0, x1 = max(0, int(x - 0.65 * w)), min(320, int(x + 0.65 * w))
        y0, y1 = max(0, int(y - 0.65 * h)), min(192, int(y + 0.65 * h))
        tile = cv2.resize(image[y0:y1, x0:x1], (60, 36), interpolation=cv2.INTER_AREA)
        patch = tile[6:30, 7:53]
        if patch.std() < 5:
            return False
        az = (yaw - math.degrees(math.atan((x - 159.5) / 160))) % 360
        el = pitch + math.degrees(math.atan((y - 119.5) / 160))
        self.views[:] = [
            v for v in self.views if tick - v["last"] < (432 if v["released"] else 90)
        ]
        best = None
        best_score = 0
        for view in self.views:
            if (
                abs((az - view["az"] + 180) % 360 - 180) > 15
                or abs(el - view["el"]) > 15
                or not 0.68 < w / view["width"] < 1.44
            ):
                continue
            score = float(
                cv2.matchTemplate(tile, view["patch"], cv2.TM_CCOEFF_NORMED).max()
            )
            if score >= (0.75 if view["released"] else 0.84) and score > best_score:
                best, best_score = view, score
        if best is None:
            self.views.append(
                {
                    "patch": patch.copy(),
                    "first": tick,
                    "last": tick,
                    "held": 0,
                    "ammo": ammo,
                    "az": az,
                    "el": el,
                    "width": w,
                    "matches": 1,
                    "released": False,
                }
            )
            if len(self.views) > 12:
                self.views.pop(0)
            return False
        if fired:
            best["held"] += min(4, tick - best["last"])
        best["last"] = tick
        best["matches"] += 1
        spent = (
            max(0, best["ammo"] - ammo)
            if best["ammo"] is not None and ammo is not None
            else 0
        )
        if (
            tick - best["first"] >= 58
            and best["matches"] >= 4
            and (spent >= 2 or best["held"] >= 32)
        ):
            best["released"] = True
        return best["released"]
