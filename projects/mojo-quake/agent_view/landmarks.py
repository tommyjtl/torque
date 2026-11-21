"""Re-find a proposed static landmark in the player's current game image."""

import math

import cv2
import numpy as np

MARK_ACTION = {
    "passage": ("route", "follow_route", "passage"),
    "exit_opening": ("route", "follow_route", "passage"),
    "landing": ("landing", "jump_forward", "landing"),
    "touch_button": ("switch", "touch_switch", "switch"),
    "shoot_button": ("switch", "shoot_switch", "switch"),
    "platform": ("platform", "board_platform", "landing"),
    "health": ("pickup", "collect_item", "supply"),
    "ammo": ("pickup", "collect_item", "supply"),
    "armor": ("pickup", "collect_item", "supply"),
}


def aim_angles(point, yaw, pitch=0):
    """Aim along a screen ray in the game's 320 × 240, 90-degree view."""
    x = (point[0] * 3.2 - 159.5) / 160
    y = (point[1] * 2.4 - 119.5) / 160
    tilt = math.radians(pitch)
    forward = math.cos(tilt) - y * math.sin(tilt)
    down = math.sin(tilt) + y * math.cos(tilt)
    bearing = (yaw - math.degrees(math.atan2(x, forward))) % 360
    elevation = math.degrees(math.atan2(down, math.hypot(forward, x)))
    return round(bearing, 3) % 360, round(max(-70, min(80, elevation)), 3)


def validated_marker(value):
    if not isinstance(value, dict) or value.get("kind") not in (
        *MARK_ACTION,
        "fallen_character",
    ):
        return None
    point = value.get("point")
    if (
        not isinstance(point, list)
        or len(point) != 2
        or not all(type(n) in (float, int) and math.isfinite(n) for n in point)
    ):
        return None
    if not (0 <= point[0] <= 100 and 0 <= point[1] < 80):
        return None
    return {"kind": value["kind"], "point": point}


class Landmark:
    def __init__(self, jpeg, marker, yaw, pitch):
        self.kind = marker["kind"]
        self.x, self.y = marker["point"][0] * 3.2, marker["point"][1] * 2.4
        self.yaw, self.pitch = yaw, pitch
        color = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)[:192]
        x, y = round(self.x), round(self.y)
        radius = min(18, x, 319 - x, y, 191 - y)
        self.patch = None
        self.channel = None
        if radius >= 6:
            region = color[y - radius : y + radius + 1, x - radius : x + radius + 1]
            channels = [cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), *cv2.split(region)]
            best = max(range(4), key=lambda k: channels[k].std())
            if channels[best].std() >= 5:
                self.channel = best
                self.patch = channels[best].copy()

    def locate(self, jpeg, yaw, pitch):
        if self.patch is None:
            return None
        az = math.atan((self.x - 159.5) / 160) + math.radians(
            (yaw - self.yaw + 180) % 360 - 180
        )
        el = math.atan((self.y - 119.5) / 160) - math.radians(pitch - self.pitch)
        if abs(az) > 0.94 or abs(el) > 0.8:
            return None
        x = round(159.5 + 160 * math.tan(az))
        y = round(119.5 + 160 * math.tan(el))
        x0, x1 = max(0, x - 55), min(320, x + 56)
        y0, y1 = max(0, y - 43), min(192, y + 44)
        if x1 - x0 < 14 or y1 - y0 < 14:
            return None
        color = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)[
            y0:y1, x0:x1
        ]
        crop = (
            cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
            if self.channel == 0
            else color[:, :, self.channel - 1]
        )
        best = None
        for scale in (0.76, 1.0, 1.3):
            side = round(len(self.patch) * scale)
            if min(crop.shape) < side + 6:
                continue
            patch = cv2.resize(self.patch, (side, side))
            scores = cv2.matchTemplate(crop, patch, cv2.TM_CCOEFF_NORMED)
            _, peak, _, (cx, cy) = cv2.minMaxLoc(scores)
            if peak < 0.82 or best and peak <= best[0]:
                continue
            scores[max(0, cy - 4) : cy + 5, max(0, cx - 4) : cx + 5] = -1
            if peak - float(scores.max()) >= 0.055:
                best = (peak, x0 + cx + (side - 1) / 2, y0 + cy + (side - 1) / 2)
        if not best:
            return None
        return {
            "kind": self.kind,
            "point": [round(best[1] / 3.2, 2), round(best[2] / 2.4, 2)],
            "match": round(best[0], 3),
        }


def ground_vision(vision, marker):
    if not marker or marker["kind"] not in MARK_ACTION:
        return
    kind = marker["kind"]
    key, _, _ = MARK_ACTION[kind]
    vision[key] = marker["point"]
    if key == "pickup":
        vision["item"] = kind
    if key == "landing":
        vision["clearance"] = "jump_up"


class PanelScout:
    """Find and physically test a distinctive wall marking from the current camera."""

    def __init__(self, weapon_poses=None):
        self.weapon_poses = weapon_poses
        self.candidate = None
        self.bearing = None
        self.first_seen = self.last_seen = -1000
        self.attempts = []
        self.next_read = 0

    @staticmethod
    def candidates(image):
        red, green, blue = np.moveaxis(image.astype(np.int16), 2, 0)
        vivid = ((red > 38) & (red > 2.25 * green + 5) & (red > 1.9 * blue + 8)).astype(
            np.uint8
        )
        _, labels, stats, centers = cv2.connectedComponentsWithStats(vivid)
        found = []
        for index, (x, y, w, h, area) in enumerate(stats[1:], 1):
            if not (
                4 <= w <= 85
                and 4 <= h <= 85
                and 0.55 < w / h < 1.65
                and 0.35 <= area / (w * h) <= 0.82
            ):
                continue
            cx, cy = centers[index]
            if not (3 < cx < 317 and 15 < cy < 178):
                continue
            dx, dy = np.meshgrid(
                (np.arange(x, x + w) - cx) / (w / 2),
                (np.arange(y, y + h) - cy) / (h / 2),
            )
            diamond = abs(dx) + abs(dy) <= 1.08
            mask = labels[y : y + h, x : x + w] == index
            quality = np.count_nonzero(mask & diamond) / max(
                1, np.count_nonzero(mask | diamond)
            )
            if quality < 0.71:
                continue
            surround = vivid[
                max(0, y - h) : min(192, y + 2 * h), max(0, x - w) : min(320, x + 2 * w)
            ]
            if surround.sum() > area * 1.26 + 3:
                continue
            found.append(
                {
                    "point": [round(cx / 3.2, 2), round(cy / 2.4, 2)],
                    "size_px": [int(w), int(h)],
                    "shape_match": round(quality, 3),
                }
            )
        return sorted(found, key=lambda v: v["shape_match"], reverse=True)

    def observe(self, jpeg, tick, yaw, pitch):
        if tick < self.next_read:
            return
        self.next_read = tick + 8
        world = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)[:192],
            cv2.COLOR_BGR2RGB,
        )
        found = self.candidates(world)
        if found and self.weapon_poses:
            boxes = np.array(
                [
                    [v["point"][0] * 3.2, v["point"][1] * 2.4, *v["size_px"]]
                    for v in found
                ]
            )
            mask = self.weapon_poses.foreground(world, boxes[:, :2])
            if mask is not None:
                found = [
                    v
                    for v, covered in zip(found, self.weapon_poses.covers(mask, boxes))
                    if not covered
                ]
        if not found:
            self.candidate = None
            return
        v = found[0]
        bearing = (yaw - math.degrees(math.atan((v["point"][0] - 50) / 50))) % 360
        if (
            self.bearing is None
            or tick - self.last_seen > 16
            or abs((bearing - self.bearing + 180) % 360 - 180) > 7
        ):
            self.first_seen = tick
        self.bearing = bearing
        self.last_seen = tick
        self.candidate = v if tick - self.first_seen >= 8 else None

    def eligible(self, tick, yaw):
        if not self.candidate or tick - self.last_seen > 10:
            return None
        if abs((yaw - self.bearing + 180) % 360 - 180) > 43:
            return None
        self.attempts[:] = [
            (when, d) for when, d in self.attempts if tick - when < 25 * 72
        ]
        if any(
            abs((self.bearing - d + 180) % 360 - 180) < 20 for _, d in self.attempts
        ):
            return None
        return self.candidate

    def commit(self, tick):
        self.attempts.append((tick, self.bearing))
