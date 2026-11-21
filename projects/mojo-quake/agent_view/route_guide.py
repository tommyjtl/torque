"""A visual E1M1 route atlas, prepared in a separate replay before live play."""

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from game import Game
from landmarks import Landmark
from models import game_input, input_chunk
from route_features import VisualFeatures

PROJECT = Path(__file__).resolve().parents[1]
GUIDE_VERSION = 2
# Each boundary is a frame on the successful Normal recording, not a live timer.
STAGES = (
    (
        690,
        488,
        "Entrance corridor",
        "Walk through the lit opening and follow the passage beside the windows.",
    ),
    (
        943,
        768,
        "Descending lift",
        "Turn left at the jump-across message and ride the lift down to the courtyard.",
    ),
    (
        1248,
        1123,
        "Lightning door",
        "Cross the courtyard and approach the door with the lightning emblem.",
    ),
    (
        1760,
        1518,
        "Industrial lift",
        "Cross the machinery room and ride the platform up before stepping off.",
    ),
    (
        2210,
        2055,
        "Wall control",
        "Follow the upper walkway and approach the illuminated diamond control.",
    ),
    (
        2720,
        2523,
        "Lower corridor",
        "Pass through the opened corridor and descend to the sequence controls.",
    ),
    (
        3010,
        2824,
        "Sequence controls",
        "Follow the wall controls until the sequence-complete message appears.",
    ),
    (
        3430,
        3299,
        "Exit tunnel",
        "Descend through the opened passage and follow the low tunnel to the ramp.",
    ),
    (
        3629,
        3539,
        "Exit slipgate",
        "Go up the ramp and enter the slipgate at the end of the passage.",
    ),
)

# Sample rays in a narrow vertical band above the weapon and below console notices.
AZ = np.arange(-32, 33, 2)
EL = np.arange(-12, 15, 2)
RAYS = np.arange(-44, 46, 2)


def patch(jpeg, azimuth, pitch=0):
    gray = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    gray = cv2.GaussianBlur(gray, (7, 7), 2.5)
    az, el = np.meshgrid(np.radians(azimuth), np.radians(EL))
    p = math.radians(pitch)
    x, y, z = np.cos(az), -np.sin(az), np.tan(el)
    forward = x * math.cos(p) - z * math.sin(p)
    down = -z * math.cos(p) - x * math.sin(p)
    u = (159.5 + 160 * y / forward).astype("float32")
    v = (119.5 + 160 * down / forward).astype("float32")
    return cv2.remap(gray, u, v, cv2.INTER_LINEAR).astype("float32")


def trace(game, filename):
    for line in filename.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        n, f, s, up, yaw, pitch, buttons, impulse = line.split()
        game.yaw, game.pitch = float(yaw), float(pitch)
        image, state, _ = game.move(
            int(n),
            int(f),
            int(s),
            int(buttons),
            up=int(up),
            impulse=int(impulse),
            evaluate=True,
        )
        yield image, state, int(buttons)


@dataclass
class Sample:
    tick: int
    position: np.ndarray


class RouteAtlas:
    """The reference process can read its own positions. The live matcher receives only camera and angles."""

    def __init__(self, binary, media):
        self.samples, self.photos = [], {}
        self.features = VisualFeatures()
        rings = []
        game = Game(binary, media, start_map="start", reference_camera=True)
        try:
            for image, state, buttons in trace(
                game, PROJECT / "replays/normal-hub-to-e1m2.trace"
            ):
                if state["map"] != "e1m1":
                    continue
                if int(state["intermission"]):
                    break
                if buttons & 2:
                    raise ValueError(
                        "The reference route now includes a jump. Review its annotations."
                    )
                pos = np.array([float(v) for v in state["pos"].split(",")])
                if (
                    not self.samples
                    or np.linalg.norm(pos - self.samples[-1].position) >= 30
                    or game.tick - self.samples[-1].tick >= 90
                ):
                    self.samples.append(Sample(game.tick, pos))
                    rings.append(self.capture_view(game, len(self.samples) - 1, pos))
                for _, frame_tick, _, _ in STAGES:
                    if game.tick >= frame_tick and frame_tick not in self.photos:
                        self.photos[frame_tick] = image
            else:
                raise ValueError(
                    "The reference inputs did not reach E1M1 intermission."
                )
        finally:
            game.close()
        if len(self.photos) != len(STAGES):
            raise ValueError("The reference is missing route landmarks.")
        self.positions = np.stack([s.position for s in self.samples])
        indexes = list(range(len(rings)))
        view_positions = list(self.positions)
        # The demonstration enters the sliding door along its left jamb. Sample
        # the center approach too, since the live game starts at rest facing it.
        self.features.previous.clear()
        game = Game(binary, media, reference_camera=True)
        try:
            game.move(24)
            last_sample = None
            entrance = next(
                i for i, sample in enumerate(self.samples) if sample.tick > STAGES[0][0]
            )
            for _ in range(48):
                _, state, _ = game.move(8, 290, evaluate=True)
                pos = np.array([float(v) for v in state["pos"].split(",")])
                if last_sample is None or np.linalg.norm(pos - last_sample) >= 20:
                    index = int(
                        np.linalg.norm(self.positions[:entrance] - pos, axis=1).argmin()
                    )
                    rings.append(self.capture_view(game, index, pos))
                    indexes.append(index)
                    view_positions.append(pos)
                    last_sample = pos
                if pos[1] >= 550:
                    break
            else:
                raise ValueError(
                    "The centered reference approach did not clear the entrance."
                )
        finally:
            game.close()
        self.rings = np.stack(rings)
        self.view_indexes = np.asarray(indexes)
        self.view_positions = np.stack(view_positions)

        game = Game(binary, media)
        try:
            for image, state, _ in trace(
                game, PROJECT / "experiments/ledge-start.trace"
            ):
                pass
            self.photos[0] = image
            self.ledge_view = patch(image, AZ, game.pitch)
            self.ledge_yaw, self.ledge_pitch = game.yaw, game.pitch
            self.lip = Landmark(
                image, {"kind": "landing", "point": [50, 42]}, game.yaw, game.pitch
            )
            self.ledge_point = [50, 42]
            height = float(state["pos"].split(",")[2])
            remaining, forward, side, buttons, yaw, pitch = game_input(
                "jump_forward", {"landing": self.ledge_point}, game.pitch
            )
            game.yaw += yaw
            game.pitch += pitch
            while remaining:
                n, keys = input_chunk(
                    "jump_forward", remaining, (forward, side, buttons), 4
                )
                image, state, _ = game.move(n, *keys, evaluate=True)
                remaining -= n
            if (
                float(state["pos"].split(",")[2]) - height < 24
                or not int(state["flags"]) & 512
            ):
                raise ValueError("Tutorial jump did not land on the upper ledge.")
            self.photos[1] = image
        finally:
            game.close()

    def capture_view(self, game, index, pos):
        ring = np.empty((len(EL), 180), dtype="float32")
        for angle in (0, 90, 180, 270):
            game.pipe.send(f"glance {angle} 0")
            _, glance = game.pipe.expect("frame")
            self.features.add(index, pos, angle, glance)
            ring[:, ((angle + RAYS) // 2) % 180] = patch(glance, RAYS)
        return ring


class RouteGuide:
    def __init__(self, atlas):
        self.atlas = atlas
        self.index = 0
        self.context = {}
        self.misses = 0
        self.saved = {}
        self.door_waited = False

    def restore_observation(self, event):
        hint = event.get("route_guide")
        if hint and hint.get("version") == GUIDE_VERSION:
            self.index = min(
                range(len(self.atlas.samples)),
                key=lambda i: abs(self.atlas.samples[i].tick - hint["reference_tick"]),
            )
            self.context = hint
        if event.get("action") == "wait_door" and event.get("applied_tick") is not None:
            self.door_waited = True

    def checkpoint(self, slot, loading):
        if loading:
            self.index = self.saved.get(slot, 0)
            self.context = {}
            self.misses = 0
            self.door_waited = False
        else:
            self.saved[slot] = self.index

    def observe(self, jpeg, yaw, pitch):
        atlas = self.atlas
        # Search the neighboring section in either direction so a retreat or a failed
        # push cannot advance the guide just because time passed.
        radius = min(20, 8 + self.misses * 2)
        lo, hi = max(0, self.index - radius), min(
            len(atlas.samples), self.index + radius + 1
        )
        match = False
        position = None
        if abs(pitch) <= 22:
            pose = atlas.features.locate(jpeg, yaw, lo, hi, atlas.positions)
            if pose is not None:
                self.index, position = pose
                match = True
        if not match and abs(pitch) <= 22:
            query = patch(jpeg, AZ, pitch)
            # A repeated wall texture at the entrance also appears near the exit.
            # A single panorama can re-establish our place only on the nearby route.
            radius = min(10, radius)
            ids = np.flatnonzero(abs(atlas.view_indexes - self.index) <= radius)
            cols = (np.rint((yaw + AZ) / 2).astype(int)) % 180
            candidates = atlas.rings[ids][:, :, cols]
            centered = candidates - candidates.mean(axis=(1, 2), keepdims=True)
            signal = query - query.mean()
            scores = (centered * signal).mean(axis=(1, 2)) / np.maximum(
                1, candidates.std(axis=(1, 2)) * query.std()
            )
            winner = int(scores.argmax())
            far = (
                np.linalg.norm(
                    atlas.view_positions[ids] - atlas.view_positions[ids[winner]],
                    axis=1,
                )
                > 125
            )
            threshold = 0.80 if self.misses >= 3 else 0.66
            match = (
                query.std() >= 7
                and scores[winner] >= threshold
                and (not far.any() or scores[winner] >= scores[far].max() + 0.04)
            )
            if match:
                self.index = int(atlas.view_indexes[ids[winner]])
                position = atlas.view_positions[ids[winner]]
        self.misses = 0 if match else self.misses + 1
        anchor = atlas.samples[self.index]
        stage = next(
            (i for i, s in enumerate(STAGES) if anchor.tick <= s[0]), len(STAGES) - 1
        )
        _, photo, name, objective = STAGES[stage]
        info = dict(
            version=GUIDE_VERSION,
            stage=stage + 1,
            total=len(STAGES),
            name=name,
            objective=objective,
            photo=photo,
            matched=bool(match),
            reference_tick=anchor.tick,
            suggested=None,
        )
        # The alternate ledge is close to the entrance. Require the actual lip in
        # the live image before admitting the demonstrated running jump.
        if (
            stage < 2
            and abs((yaw - atlas.ledge_yaw + 180) % 360 - 180) < 18
            and abs(pitch - atlas.ledge_pitch) < 12
        ):
            mark = atlas.lip.locate(jpeg, yaw, pitch)
            sample = patch(jpeg, AZ, pitch)
            similarity = cv2.matchTemplate(
                sample, atlas.ledge_view, cv2.TM_CCOEFF_NORMED
            )[0, 0]
            if mark and similarity > 0.80:
                info.update(
                    suggested="jump_forward",
                    landing=mark["point"],
                    photo=0,
                    matched=True,
                    name="Optional tutorial ledge",
                    objective="Aim at the top lip, take a run-up and jump onto the shelf.",
                )
                self.context = info
                return info
        if match:
            # Look a short distance along the demonstrated path. Use the route's
            # direction of travel even when the demonstrator was looking sideways.
            end = self.index
            for j in range(self.index + 1, min(len(atlas.samples), self.index + 7)):
                end = j
                if np.linalg.norm(atlas.positions[j] - anchor.position) >= 90:
                    break
            delta = atlas.positions[end] - (
                anchor.position if position is None else position
            )
            if anchor.tick <= 523:
                # Aim through the center of the spawn doorway before rejoining
                # the demonstrated line farther down the ramp.
                delta = np.array([480.0, -68.0, 40.0]) - position
            if (
                435 <= anchor.tick <= 490
                and abs(position[1] + 240) < 18
                and self.context.get("reference_tick") == anchor.tick
                and not self.door_waited
            ):
                info.update(
                    suggested="wait_door",
                    objective="Hold at the entrance while the metal door slides open.",
                )
            elif math.hypot(*delta[:2]) < 35 and abs(delta[2]) > 35:
                info.update(suggested="ride_lift")
            elif end > self.index or stage == len(STAGES) - 1:
                bearing = (
                    math.degrees(math.atan2(delta[1], delta[0]))
                    if end > self.index
                    else -90
                )
                turn = (bearing - yaw + 180) % 360 - 180
                if abs(turn) > 36:
                    info["suggested"] = "turn_left" if turn > 0 else "turn_right"
                else:
                    info.update(
                        suggested="follow_route",
                        route=[round(50 - 50 * math.tan(math.radians(turn)), 1), 55],
                    )
        self.context = info
        return info
