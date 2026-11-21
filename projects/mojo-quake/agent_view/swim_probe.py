"""Test vertical controls in a private game by comparing their camera images with idle."""

import cv2
import numpy as np


def gray(jpeg):
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)[
        10:151, 6:314
    ]


def vertical_shift(reference, changed):
    corners = cv2.goodFeaturesToTrack(reference, 85, 0.015, 5)
    if corners is None or len(corners) < 8:
        return 0.0
    moved, valid, error = cv2.calcOpticalFlowPyrLK(reference, changed, corners, None)
    if moved is None:
        return 0.0
    delta = (moved - corners).reshape(-1, 2)
    usable = (
        valid.ravel().astype(bool)
        & (error.ravel() < 22)
        & (np.abs(delta[:, 0]) < 4 + 0.3 * np.abs(delta[:, 1]))
    )
    return float(np.median(delta[usable, 1])) if usable.sum() >= 8 else 0.0


def vertical_control(camera, heading):
    def sample(up):
        camera.rewind()
        forward = camera.frame(20, 0, 0, up, heading, 0)
        return [
            gray(forward),
            gray(camera.glance((heading + 90) % 360, 0)),
            gray(camera.glance(heading, 48)),
        ]

    def errors(a, b):
        return np.array([float(cv2.absdiff(x, y).mean()) for x, y in zip(a, b)])

    idle = sample(0)
    up, down, repeat = sample(280), sample(-280), sample(0)
    camera.rewind()
    noise = errors(idle, repeat)
    upward = float(np.median([vertical_shift(a, b) for a, b in zip(idle, up)]))
    downward = float(np.median([vertical_shift(a, b) for a, b in zip(idle, down)]))
    difference = np.maximum(errors(idle, up), errors(idle, down))
    strength = float(np.median(difference - noise))
    return {
        "up_pixels": round(upward, 2),
        "down_pixels": round(downward, 2),
        "change_above_idle": round(strength, 2),
        "responds": bool(
            strength > 2.5 and ((difference > 1.35 * noise + 0.8).sum() >= 2)
        ),
    }
