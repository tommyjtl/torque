"""Recognize visible first-person weapon art in the current RGB image."""

import cv2
import numpy as np

SIZE = (80, 48)


def small_gray(world):
    gray = cv2.cvtColor(np.asarray(world), cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, SIZE, interpolation=cv2.INTER_AREA).astype(np.float32)


class WeaponPoses:
    def __init__(self, path):
        with np.load(path, allow_pickle=False) as data:
            masks = data["masks"].astype(bool)
            gray = data["gray"].astype(np.float32)
        if (
            masks.ndim != 3
            or masks.shape[1:] != SIZE[::-1]
            or gray.shape != masks.shape
            or not len(gray)
        ):
            raise ValueError("Invalid Quake weapon calibration")
        self.masks = masks
        coordinates = []
        for mask in masks:
            pixels = np.flatnonzero(mask)
            if len(pixels) < 15:
                raise ValueError("Insufficient weapon pixels in calibration")
            # Sample inside each observed silhouette. Full-frame matrix
            # products repeatedly score thousands of irrelevant scenery pixels.
            positions = np.linspace(0, len(pixels) - 1, 96).round().astype(int)
            coordinates.append(pixels[positions])
        self.coordinates = np.asarray(coordinates)
        values = np.take_along_axis(
            gray.reshape(len(gray), -1), self.coordinates, axis=1
        )
        centered = values - values.mean(axis=1, keepdims=True)
        self.normalized = centered / np.maximum(
            0.01, np.linalg.norm(centered, axis=1)[:, None]
        )

    def foreground(self, world, centers):
        # Only poses that could cover a proposed character could invalidate it.
        columns = np.clip(np.rint(centers[:, 0] / 4).astype(int), 0, SIZE[0] - 1)
        rows = np.clip(np.rint(centers[:, 1] / 4).astype(int), 0, SIZE[1] - 1)
        possible = self.masks[:, rows, columns].any(axis=1)
        if not possible.any():
            return None
        image = small_gray(world).ravel()
        candidates = np.flatnonzero(possible)
        samples = image[self.coordinates[candidates]]
        samples -= samples.mean(axis=1, keepdims=True)
        correlation = (self.normalized[candidates] * samples).sum(axis=1) / np.maximum(
            1, np.linalg.norm(samples, axis=1)
        )
        strongest = float(correlation.max())
        if strongest < 0.86:
            return None
        similar = correlation >= max(0.86, strongest - 0.035)
        return self.masks[candidates[similar]].any(axis=0)

    @staticmethod
    def covers(mask, boxes):
        """Return one flag per native-pixel (center x, center y, width, height) box."""
        x, y, width, height = boxes.T
        cols = np.clip(np.rint(x / 4).astype(int), 0, 79)
        rows = np.clip(np.rint(y / 4).astype(int), 0, 47)
        x0 = np.clip(np.floor((x - width / 2) / 4).astype(int), 0, 79)
        x1 = np.clip(np.ceil((x + width / 2) / 4).astype(int), 1, 80)
        y0 = np.clip(np.floor((y - height / 2) / 4).astype(int), 0, 47)
        y1 = np.clip(np.ceil((y + height / 2) / 4).astype(int), 1, 48)
        summed = cv2.integral(mask.astype(np.uint8))
        covered = summed[y1, x1] - summed[y0, x1] - summed[y1, x0] + summed[y0, x0]
        return mask[rows, cols] | (
            covered >= 0.45 * np.maximum(1, (x1 - x0) * (y1 - y0))
        )
