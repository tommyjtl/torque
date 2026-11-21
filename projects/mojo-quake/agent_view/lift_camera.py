"""Observe whether a released player keeps rising, using only fixed-heading game images."""

import cv2
import numpy as np
from swim_probe import gray


def wall_shift(before, after):
    mask = np.zeros_like(before, dtype=np.uint8)
    mask[8:-8, 8:-8] = 255
    corners = cv2.goodFeaturesToTrack(before, 60, 0.018, 7, mask=mask)
    if corners is None or len(corners) < 6:
        return None
    settings = {"winSize": (17, 17), "maxLevel": 2}
    found, ok, errors = cv2.calcOpticalFlowPyrLK(
        before, after, corners, None, **settings
    )
    back, returned, _ = cv2.calcOpticalFlowPyrLK(
        after,
        before,
        found,
        corners.copy(),
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW,
        **settings,
    )
    shift = (found - corners).reshape(-1, 2)
    pixels = corners.reshape(-1, 2)
    good = (
        ok.ravel().astype(bool)
        & returned.ravel().astype(bool)
        & (errors.ravel() < 17)
        & (np.linalg.norm(back.reshape(-1, 2) - pixels, axis=1) < 1.1)
        & (np.abs(shift[:, 0]) < 1.6 + 0.3 * np.abs(shift[:, 1]))
    )
    if good.sum() < 6 or np.ptp(pixels[good, 0]) < 50:
        return None
    return float(np.median(shift[good, 1]))


def classify(shifts):
    vertical = []
    for sector in zip(*shifts):
        measured = [x for x in sector if x is not None]
        vertical.append(
            round(float(np.median(measured)), 2) if len(measured) >= 3 else None
        )
    rising = sum(x is not None and x > 2.2 for x in vertical)
    falling = sum(x is not None and x < -2.2 for x in vertical)
    direction = (
        "rising"
        if rising >= 2 and rising > falling
        else "descending"
        if falling >= 3 and falling > rising
        else "unconfirmed"
    )
    return {"direction": direction, "vertical_pixels_per_sample": vertical}


def released_camera(camera, yaw, *, follow=False):
    def views():
        return [gray(camera.glance(angle, 0)) for angle in (0, 90, 180, 270)]

    camera.rewind()
    for _ in range(4):
        camera.frame(4, 0, 0, 0, yaw, 0)
    before = views()

    def sample(count):
        nonlocal before
        shifts = []
        for _ in range(count):
            camera.frame(4, 0, 0, 0, yaw, 0)
            after = views()
            shifts.append([wall_shift(a, b) for a, b in zip(before, after)])
            before = after
        return classify(shifts)

    first = sample(6)
    first["elapsed_ticks"] = 40
    first["still_rising"] = first["direction"] == "rising"
    if first["still_rising"] and follow:
        # Sample through the ride. A long ascent can continue across multiple live decisions.
        for _ in range(4):
            later = sample(5)
            first["elapsed_ticks"] += 20
            first["still_rising"] = later["direction"] == "rising"
            if not first["still_rising"]:
                break
    return first
