"""Estimate short horizontal camera translations from the visible ground texture."""

import math

import cv2
import numpy as np
from survey import camera_gray


class FloorMotion:
    def __init__(self):
        # Rectify a downward view to a small floor patch. Scale assumes ordinary standing eye height.
        rows, cols = np.indices((95, 143), dtype=np.float32)
        x = (51 - rows) / 2.05
        y = (71 - cols) / 2.05
        pitch = math.radians(80)
        depth = x * math.cos(pitch) + 46 * math.sin(pitch)
        self.px = (159.5 - 160 * y / depth).astype("float32")
        self.py = (
            119.5 + 160 * (-math.sin(pitch) * x + 46 * math.cos(pitch)) / depth
        ).astype("float32")

    def patch(self, camera):
        return cv2.remap(
            camera_gray(camera.glance(0, 80)), self.px, self.py, cv2.INTER_LINEAR
        )

    def shift(self, old, new, expected):
        estimates = []
        for cx, cy in ((38, 39), (71, 39), (104, 39), (39, 59), (103, 59)):
            patch = old[cy - 8 : cy + 9, cx - 10 : cx + 11]
            if patch.std() < 4:
                continue
            x0, y0 = max(0, cx - 41), max(0, cy - 39)
            area = new[y0 : min(95, cy + 40), x0 : min(143, cx + 42)]
            corr = cv2.matchTemplate(area, patch, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.indices(corr.shape)
            dx, dy = (ys + y0 + 8 - cy) / 2.05, (xs + x0 + 10 - cx) / 2.05
            # The last command disambiguates periodic tiles. Only matching pixels contribute.
            score = corr - 0.006 * np.minimum(
                21, np.hypot(dx - expected[0], dy - expected[1])
            )
            v, u = np.unravel_index(np.argmax(score), score.shape)
            if corr[v, u] > 0.65:
                estimates.append((dx[v, u], dy[v, u], corr[v, u]))
        if not estimates:
            return None
        values = np.array(estimates)
        positions = values[:, :2]
        near = np.linalg.norm(positions[:, None] - positions, axis=2) < 2.5
        group = near[np.argmax(near @ values[:, 2])]
        return np.median(positions[group], axis=0) if group.sum() >= 2 else None

    def traverse(self, camera, option, yaw, pitch):
        rows = option.rows(yaw, pitch)
        measured = np.zeros(2)
        supported = moving = 0
        last_speed = None
        driving = [i for i, row in enumerate(rows) if row[1] and row[0] >= 6]
        samples = (
            {
                driving[min(len(driving) - 1, int(q * len(driving)))]
                for q in (0.18, 0.55, 0.94)
            }
            if driving
            else set()
        )
        sampled = 0
        for index, (n, f, side, up, angle, tilt, buttons) in enumerate(rows):
            if index in samples:
                previous = fingerprint_small(
                    camera.frame(n - 3, f, side, up, angle, tilt, buttons)
                )
                old = self.patch(camera)
                frame = camera.frame(3, f, side, up, angle, tilt, buttons)
                new = self.patch(camera)
                direction = np.array(
                    [math.cos(math.radians(angle)), math.sin(math.radians(angle))]
                )
                shift = self.shift(old, new, direction * 3 * f / 72)
                sampled += n
                if shift is not None:
                    measured += shift * (n / 3)
                    supported += n
                    last_speed = float(shift @ direction / 3)
                elif float(np.abs(previous - fingerprint_small(frame)).mean()) < 0.8:
                    supported += n
                    last_speed = 0.0
            else:
                frame = camera.frame(n, f, side, up, angle, tilt, buttons)
            if f:
                moving += n
        return (
            frame,
            measured * moving / max(1, supported),
            supported / max(1, sampled),
            last_speed,
        )


def fingerprint_small(frame):
    return cv2.resize(
        camera_gray(frame)[12:151], (36, 22), interpolation=cv2.INTER_AREA
    ).astype(np.float32)
