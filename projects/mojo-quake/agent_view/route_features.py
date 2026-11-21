"""Locate a live RGB view against features triangulated between recorded route cameras."""

import math

import cv2
import numpy as np


K = np.array([[160.0, 0.0, 159.5], [0.0, 160.0, 119.5], [0.0, 0.0, 1.0]])
CONTRAST = cv2.createCLAHE(2.0, (6, 4))
DETECTOR = cv2.SIFT_create(nfeatures=350, contrastThreshold=0.008, edgeThreshold=10)


def features(jpeg):
    gray = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    # Mask the HUD, first-person weapon and central game messages.
    mask = np.zeros_like(gray)
    mask[14:182, 6:-6] = 255
    mask[91:113, 40:280] = 0
    mask[137:, 103:217] = 0
    keys, descriptors = DETECTOR.detectAndCompute(CONTRAST.apply(gray), mask)
    return np.float32([k.pt for k in keys]).reshape(-1, 2), descriptors


def rotation(yaw):
    a = math.radians(yaw)
    return np.array(
        [
            [math.sin(a), -math.cos(a), 0.0],
            [0.0, 0.0, -1.0],
            [math.cos(a), math.sin(a), 0.0],
        ]
    )


def pairs(first, second):
    if first is None or second is None or min(len(first), len(second)) < 2:
        return []
    return [
        (a.queryIdx, a.trainIdx)
        for a, b in cv2.BFMatcher().knnMatch(first, second, k=2)
        if a.distance < 0.76 * b.distance
    ]


def triangulate(first, second, yaw):
    pa, da, xyz_a = first
    pb, db, xyz_b = second
    matches = pairs(da, db)
    if len(matches) < 4:
        return None
    ia, ib = np.array(matches).T
    r = rotation(yaw)
    p1 = K @ np.column_stack((r, -r @ xyz_a))
    p2 = K @ np.column_stack((r, -r @ xyz_b))
    points = cv2.triangulatePoints(p1, p2, pa[ia].T, pb[ib].T).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        h = points / points[3]
        u, v = p1 @ h, p2 @ h
        error = np.maximum(
            np.linalg.norm(u[:2] / u[2] - pa[ia].T, axis=0),
            np.linalg.norm(v[:2] / v[2] - pb[ib].T, axis=0),
        )
    valid = (error < 1.8) & (u[2] > 24) & (v[2] > 24) & (u[2] < 1200) & (v[2] < 1200)
    if valid.sum() < 4:
        return None
    return np.float32(h[:3, valid].T), db[ib[valid]]


class VisualFeatures:
    def __init__(self):
        self.previous = {}
        self.clouds = []

    def add(self, index, position, yaw, jpeg):
        points, descriptors = features(jpeg)
        current = points, descriptors, position
        previous = self.previous.get(yaw)
        if previous and np.linalg.norm(position - previous[2]) >= 15:
            cloud = triangulate(previous, current, yaw)
            if cloud is not None:
                self.clouds.append((index, yaw, *cloud))
        self.previous[yaw] = current

    def locate(self, jpeg, yaw, lo, hi, origins):
        points, descriptors = features(jpeg)
        if descriptors is None:
            return None
        # Independent references may describe the same feature. Keep one vote per live pixel.
        observations = {}
        for index, angle, xyz, reference in self.clouds:
            if not lo <= index < hi or abs((angle - yaw + 180) % 360 - 180) > 68:
                continue
            for j, i in pairs(reference, descriptors):
                distance = np.linalg.norm(descriptors[i] - reference[j])
                if distance < 235 and (
                    i not in observations or distance < observations[i][0]
                ):
                    observations[i] = distance, xyz[j]
        if len(observations) < 10:
            return None
        xy = np.float32([points[i] for i in observations])
        xyz = np.float32([v[1] for v in observations.values()])
        ok, rvec, t, inliers = cv2.solvePnPRansac(
            xyz,
            xy,
            K,
            None,
            iterationsCount=180,
            reprojectionError=4.0,
            flags=cv2.SOLVEPNP_EPNP,
        )
        if (
            not ok
            or inliers is None
            or len(inliers) < 9
            or len(inliers) < len(xy) * 0.32
        ):
            return None
        used = inliers.ravel()
        if np.ptp(xy[used, 0]) < 45 or np.ptp(xy[used, 1]) < 20:
            return None
        ok, rvec, t = cv2.solvePnP(
            xyz[used], xy[used], K, None, rvec, t, True, cv2.SOLVEPNP_ITERATIVE
        )
        if not ok:
            return None
        r = cv2.Rodrigues(rvec)[0]
        estimated_yaw = math.degrees(math.atan2(r[2, 1], r[2, 0]))
        position = (-r.T @ t).ravel()
        if (
            abs((estimated_yaw - yaw + 180) % 360 - 180) > 14
            or not np.isfinite(position).all()
        ):
            return None
        nearby = np.linalg.norm(origins[lo:hi] - position, axis=1)
        best = int(nearby.argmin())
        if nearby[best] > 200:
            return None
        return lo + best, position
