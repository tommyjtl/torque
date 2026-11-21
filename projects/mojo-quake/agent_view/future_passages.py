"""Bounded private movement comparisons learned from turns in human demonstrations."""

from dataclasses import dataclass

import cv2
import numpy as np

from floor_motion import FloorMotion


def describe_views(photos):
    tiles = []
    for photo in photos:
        gray = cv2.imdecode(np.frombuffer(photo, np.uint8), cv2.IMREAD_GRAYSCALE)
        tile = cv2.resize(
            gray[31:156, 6:314], (12, 8), interpolation=cv2.INTER_AREA
        ).astype(np.float32)
        tiles.append(
            np.clip((tile - tile.mean()) / max(12, tile.std()), -2.5, 2.5).ravel()
        )
    return np.asarray(tiles, dtype=np.float32)


def nearest_view(archive, view):
    if len(archive) == 0:
        return 1.0
    errors = np.abs(archive - view).mean(axis=2)
    return float(np.sort(errors, axis=1)[:, :3].mean(axis=1).min())


@dataclass
class Branch:
    snapshot: object
    bearing: float
    moves: tuple
    scenes: tuple
    delta: np.ndarray
    score: float


class FuturePassages:
    def __init__(self, hud):
        self.hud = hud
        self.floor = FloorMotion()
        self.history = np.empty((256, 4, 96), dtype=np.float32)
        self.count = 0
        self.camera = None
        self.last_search = -10000

    def close(self):
        if self.camera is not None:
            self.camera.__exit__(None, None, None)
            self.camera = None

    def remember(self, photos):
        self.history[self.count % len(self.history)] = describe_views(photos)
        self.count += 1

    def search(self, source, option_type, cancelled=None):
        if self.camera is None:
            self.camera = source.open_camera()
        else:
            self.camera.rebase(source)
        try:
            return self._search(source, self.camera, option_type, cancelled)
        except Exception:
            self.close()
            raise

    def _search(self, source, camera, option_type, cancelled):
        def scene():
            return describe_views([camera.glance(h, 0) for h in (0, 90, 180, 270)])

        initial = scene()
        start_hp = self.hud.read(camera.glance(source.yaw, 0))
        if start_hp is None or start_hp <= 0:
            return None
        archive = self.history[: min(self.count, len(self.history))]
        roots = [Branch(source, source.yaw, (), (initial,), np.zeros(2), 0.0)]
        best = None
        trials = 0
        for depth in range(1, 4):
            children = []
            for node in roots:
                if node.moves:
                    turns = [
                        (0, "walk"),
                        (80, "walk"),
                        (-80, "walk"),
                        (40 if self.count % 2 else -40, "jump"),
                    ]
                else:
                    turns = [(v, "walk") for v in (0, 80, -80, 160, -160)] + [
                        (v, "jump") for v in (0, 80, -80)
                    ]
                for turn, kind in turns:
                    if cancelled and cancelled():
                        return None
                    camera.rebase(node.snapshot)
                    option = option_type(
                        (node.bearing + turn) % 360, kind, 54 if depth == 1 else 70
                    )
                    _, delta, support, _ = self.floor.traverse(
                        camera, option, node.bearing, 0
                    )
                    frame = camera.frame(12, 0, 0, 0, option.heading, 0)
                    trials += 1
                    hp = self.hud.read(frame)
                    complete = self.hud.completed(frame)
                    if not complete and (hp is None or hp <= 0):
                        continue
                    view = scene()
                    change = nearest_view(np.array([node.scenes[-1]]), view)
                    if not complete and (
                        nearest_view(np.asarray(node.scenes), view) < 0.16
                        or (support >= 0.45 and np.linalg.norm(delta) < 38)
                        or (support < 0.45 and change < 0.35)
                    ):
                        continue
                    moves = node.moves + (option,)
                    net = node.delta + delta if support >= 0.45 else node.delta
                    score = (
                        nearest_view(archive, view)
                        + min(1.2, np.linalg.norm(net) / 280)
                        + 0.32 * depth
                        + 0.3 * min(0.9, change)
                        + 0.13 * node.score
                        - max(0, start_hp - (hp or start_hp)) / 13
                    )
                    if complete:
                        score += 100
                    record = {
                        "score": float(score),
                        "moves": moves,
                        "visible_complete": complete,
                    }
                    if (len(moves) >= 2 or complete) and (
                        best is None or score > best["score"]
                    ):
                        best = record
                    if depth < 3 and not complete:
                        snapshot = camera.snapshot(option.heading, 0)
                        if snapshot:
                            children.append(
                                Branch(
                                    snapshot,
                                    option.heading,
                                    moves,
                                    node.scenes + (view,),
                                    net,
                                    score,
                                )
                            )
            if not children:
                break
            roots = []
            directions = set()
            for child in sorted(children, key=lambda b: b.score, reverse=True):
                first = round(child.moves[0].heading / 20)
                if first in directions or any(
                    nearest_view(np.array([b.scenes[-1]]), child.scenes[-1]) < 0.18
                    for b in roots
                ):
                    continue
                directions.add(first)
                roots.append(child)
                if len(roots) == 3:
                    break
        if best:
            best["trials"] = trials
        return best
