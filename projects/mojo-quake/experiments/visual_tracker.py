"""A short-lived image patch anchored by a model's point on a Quake frame."""

from collections import deque

import cv2
import numpy as np


def gray(jpeg):
    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


class PatchTrack:
    # At 320 x 240 this search covers a roughly 15-degree change in facing per sample.
    RADIUS = 9
    SEARCH = 48

    def __init__(self, frame, point):
        h, w = frame.shape
        self.x = round(point[0] * w / 100)
        self.y = round(point[1] * h / 100)
        r = self.RADIUS
        self.alive = r <= self.x < w - r and r <= self.y < int(0.80 * h) - r
        if self.alive:
            self.patch = frame[
                self.y - r : self.y + r + 1, self.x - r : self.x + r + 1
            ].copy()
            self.alive = self.patch.std() >= 5

    def update(self, frame):
        if not self.alive:
            return
        h, w = frame.shape
        r = self.RADIUS
        left = max(0, self.x - self.SEARCH - r)
        right = min(w, self.x + self.SEARCH + r + 1)
        top = max(0, self.y - self.SEARCH - r)
        bottom = min(int(0.8 * h), self.y + self.SEARCH + r + 1)
        scores = cv2.matchTemplate(
            frame[top:bottom, left:right], self.patch, cv2.TM_CCOEFF_NORMED
        )
        _, peak, _, (x, y) = cv2.minMaxLoc(scores)
        scores[max(0, y - 4) : y + 5, max(0, x - 4) : x + 5] = -1
        if peak < 0.67 or peak - float(scores.max()) < 0.035:
            self.alive = False
            return
        self.x, self.y = left + x + r, top + y + r

    def point(self):
        if self.alive:
            return [100 * self.x / 320, 100 * self.y / 240]
        return None


class FrameBuffer:
    def __init__(self):
        self.frames = deque(maxlen=56)

    def add(self, tick, jpeg):
        self.frames.append((tick, gray(jpeg)))

    def anchor(self, tick, point, kind=None):
        """Catch up a delayed cloud observation using only actual intervening images."""
        frames = iter(self.frames)
        for stamp, frame in frames:
            if stamp == tick:
                track = PatchTrack(frame, point)
                for _, later in frames:
                    track.update(later)
                return track
        return None


class MotionFrame:
    """Inter-frame camera warp verified by matched features on the playing area."""

    def __init__(self, jpg, previous, detector):
        self.gray = gray(jpg)
        world = self.gray[:184]
        self.image = cv2.equalizeHist(world)
        mask = np.full(world.shape, 255, dtype=np.uint8)
        mask[117:, 135:185] = 0  # first-person weapon
        points, descriptors = detector.detectAndCompute(self.image, mask)
        self.xy = np.array([p.pt for p in points], dtype=np.float32).reshape(-1, 2)
        self.descriptors = descriptors
        self.H = None
        self.local = np.empty((0, 2), dtype=np.float32)
        if (
            previous is None
            or descriptors is None
            or previous.descriptors is None
            or len(descriptors) < 2
        ):
            return
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(
            previous.descriptors, descriptors, k=2
        )
        good = [
            pair[0]
            for pair in matches
            if len(pair) == 2 and pair[0].distance < 0.78 * pair[1].distance
        ]
        if len(good) < 10:
            return
        a = previous.xy[[m.queryIdx for m in good]]
        b = self.xy[[m.trainIdx for m in good]]
        H, inliers = cv2.findHomography(a, b, cv2.RANSAC, 2.5, maxIters=300)
        if H is None or inliers is None:
            return
        valid = inliers.ravel().astype(bool)
        local = a[valid]
        if (
            len(local) < 10
            or valid.mean() < 0.48
            or np.ptp(local[:, 0]) < 60
            or np.ptp(local[:, 1]) < 30
        ):
            return
        self.H, self.local = H, local


class FeatureTrack:
    def __init__(self, frame, point, kind):
        self.pos = np.asarray([point[0] * 3.2, point[1] * 2.4], dtype=np.float32)
        self.kind = kind
        self.previous = frame
        self.alive = 8 <= self.pos[0] < 312 and 8 <= self.pos[1] < 176

    def update(self, frame):
        if not self.alive:
            return
        p = self.pos
        if frame.H is None:
            pred = p
        else:
            proj = frame.H @ np.array([*p, 1.0])
            pred = proj[:2] / proj[2]
        if (
            not np.isfinite(pred).all()
            or np.linalg.norm(pred - p) > 85
            or not (7 <= pred[0] < 313 and 7 <= pred[1] < 177)
        ):
            self.alive = False
            return
        # Static landmarks may span repetitive floor panels: spatial consensus
        # from neighboring features disambiguates the patch. An enemy must also
        # match its own local pixels or the lock is released.
        support = (
            frame.H is not None
            and np.count_nonzero(np.linalg.norm(frame.local - p, axis=1) < 55) >= 3
        )
        x, y = np.rint(p).astype(int)
        cx, cy = np.rint(pred).astype(int)
        r = 7
        patch = self.previous.image[y - r : y + r + 1, x - r : x + r + 1]
        margin = 9 if frame.H is not None else 18
        x0 = max(0, cx - r - margin)
        y0 = max(0, cy - r - margin)
        search = frame.image[
            y0 : min(184, cy + r + margin + 1), x0 : min(320, cx + r + margin + 1)
        ]
        if patch.shape != (15, 15):
            self.alive = False
            return
        scores = cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED)
        _, peak, _, (mx, my) = cv2.minMaxLoc(scores)
        scores[max(0, my - 3) : my + 4, max(0, mx - 3) : mx + 4] = -1
        hit = np.array([x0 + mx + r, y0 + my + r], dtype=np.float32)
        unique = peak - float(scores.max()) > 0.035
        if (
            patch.std() >= 4
            and peak > 0.61
            and (unique or (support and np.linalg.norm(hit - pred) < 4))
        ):
            self.pos = hit
        elif self.kind != "enemy" and support:
            self.pos = pred
        else:
            self.alive = False
        self.previous = frame

    def point(self):
        if self.alive:
            return [float(self.pos[0] / 3.2), float(self.pos[1] / 2.4)]
        return None


class FeatureBuffer(FrameBuffer):
    def __init__(self):
        super().__init__()
        self.detector = cv2.ORB_create(
            nfeatures=400, edgeThreshold=8, patchSize=21, fastThreshold=8
        )

    def add(self, tick, jpeg):
        previous = self.frames[-1][1] if self.frames else None
        self.frames.append((tick, MotionFrame(jpeg, previous, self.detector)))

    def anchor(self, tick, point, kind=None):
        frames = iter(self.frames)
        for stamp, frame in frames:
            if stamp == tick:
                track = FeatureTrack(frame, point, kind)
                for _, later in frames:
                    track.update(later)
                return track
        return None
