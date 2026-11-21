"""Recognize a visited camera location from landmarks shared by compass-aligned views."""

import cv2
import numpy as np


class PlaceCamera:
    def __init__(self):
        self.orb = cv2.ORB_create(
            nfeatures=240, edgeThreshold=8, patchSize=21, fastThreshold=8
        )
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.mask = np.zeros((192, 320), np.uint8)
        self.mask[9:182, 7:313] = 255
        self.mask[120:, 118:202] = 0

    def landmark(self, panorama, views):
        small = np.stack(
            [
                cv2.resize(tile, (12, 8), interpolation=cv2.INTER_AREA)
                for tile in panorama
            ]
        )
        marks = []
        for frame in views:
            gray = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_GRAYSCALE)[
                :192
            ]
            keypoints, descriptors = self.orb.detectAndCompute(
                cv2.equalizeHist(gray), self.mask
            )
            pixels = np.float32([k.pt for k in keypoints]).reshape(-1, 2)
            marks.append((pixels, descriptors))
        return small, marks

    def support(self, first, second):
        pixel_a, da = first
        pixel_b, db = second
        if da is None or db is None or min(len(da), len(db)) < 4:
            return 0
        unique = {}
        for best, other in self.matcher.knnMatch(da, db, k=2):
            if best.distance > 48 or best.distance >= 0.76 * other.distance:
                continue
            previous = unique.get(best.trainIdx)
            if previous is None or previous.distance > best.distance:
                unique[best.trainIdx] = best
        matches = list(unique.values())
        if len(matches) < 4:
            return 0
        points = pixel_a[[m.queryIdx for m in matches]]
        shifts = pixel_b[[m.trainIdx for m in matches]] - points
        consistent = np.linalg.norm(shifts - np.median(shifts, axis=0), axis=1) < 12
        count = int(consistent.sum())
        if (
            count < 4
            or np.ptp(points[consistent, 0]) <= 38
            or np.ptp(points[consistent, 1]) <= 12
        ):
            return 0
        return (
            count if np.median(np.linalg.norm(shifts[consistent], axis=1)) < 40 else 0
        )

    def agrees(self, query, reference, error=None):
        if error is None:
            error = np.abs(query[0] - reference[0]).mean(axis=(1, 2))
        ordered = np.sort(error)
        if ordered[2] >= 25:
            return False
        counts = [self.support(a, b) for a, b in zip(query[1], reference[1])]
        return np.count_nonzero(counts) >= 2 and sum(counts) >= 20

    def locate(self, sample, known, expected=None):
        if known:
            errors = np.abs(np.asarray([v[0] for v in known]) - sample[0]).mean(
                axis=(2, 3)
            )
            costs = np.sort(errors, axis=1)[:, :3].mean(axis=1)
            shortlist = list(np.argsort(costs)[:8])
            if expected is not None:
                shortlist.insert(0, expected)
            for i in dict.fromkeys(shortlist):
                if self.agrees(sample, known[i], errors[i]):
                    return int(i)
        known.append(sample)
        return len(known) - 1
