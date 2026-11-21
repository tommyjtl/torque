"""Recognize familiar surroundings using RGB frames and the camera angles we issued."""

import io
import math
from collections import Counter, deque
from dataclasses import dataclass

import numpy as np
from PIL import Image
from survey import BoundaryTravel, PassageSurvey

HZ = 72
WINDOW = 30 * HZ
NO_PROGRESS = 45 * HZ
# The same bearing lands in the same column even after turning the camera.
AZIMUTH = np.radians(np.arange(64) * 360 / 64)
ELEVATION = np.radians(np.arange(-20, 31, 5))[:, None]


@dataclass
class View:
    image: np.ndarray
    mask: np.ndarray
    tick: int
    place: int


def project_view(jpeg, yaw, pitch, tick, place):
    with Image.open(io.BytesIO(jpeg)) as image:
        rgb = np.asarray(image.convert("RGB").resize((64, 48), Image.Resampling.BOX))
    angle = AZIMUTH - math.radians(yaw)
    tilt = math.radians(pitch)
    plane = np.cos(ELEVATION) * np.cos(angle)
    forward = np.cos(tilt) * plane - np.sin(tilt) * np.sin(ELEVATION)
    up = np.sin(tilt) * plane + np.cos(tilt) * np.sin(ELEVATION)
    safe = np.maximum(forward, 0.001)
    x = np.rint(31.5 - 32 * np.cos(ELEVATION) * np.sin(angle) / safe).astype(int)
    y = np.rint(23.5 - 32 * up / safe).astype(int)
    visible = (forward > 0) & (x >= 1) & (x < 63) & (y >= 2) & (y < 36)
    visible &= ~((y >= 25) & (x >= 27) & (x <= 37))
    return View(
        rgb[y.clip(0, 47), x.clip(0, 63)].astype(np.int16), visible, tick, place
    )


class VisualAtlas:
    """An approximate area match; a second, stricter score can merge nearby views."""

    def __init__(self):
        self.frames = []
        self.buckets = [[] for _ in range(16)]

    def match(self, view, yaw, min_age=0):
        bucket = round(yaw / 22.5) % 16
        best, distance = None, 100
        for prior in self.buckets[bucket]:
            if view.tick - prior.tick < min_age:
                continue
            overlap = view.mask & prior.mask
            if overlap.sum() < 65:
                continue
            a, b = view.image[overlap], prior.image[overlap]
            if min(a.std(), b.std()) < 11:
                continue
            delta = (a - b).mean(axis=1)
            # Mild light flicker can shift exposure without changing spatial structure.
            error = np.abs(delta - np.median(delta)).mean() + 0.3 * abs(delta.mean())
            if error < distance:
                best, distance = prior, float(error)
                if error < 1.4:
                    break
        return best, distance

    def add(self, view, yaw):
        if len(self.frames) >= 800:
            # Retain the first, equally spaced observations as the memory grows.
            index = len(self.frames) // 2
            for b in self.buckets:
                b[:] = [v for v in b if v is not self.frames[index]]
            self.frames.pop(index)
        self.frames.append(view)
        center = round(yaw / 22.5)
        for offset in (-1, 0, 1):
            self.buckets[(center + offset) % 16].append(view)


class Exploration:
    def __init__(self):
        self.atlas = VisualAtlas()
        self.samples = deque()
        self.last_tick = None
        self.last_novel = 0
        self.last_sample = -HZ
        self.last_move = -HZ
        self.last_recovery = -3 * NO_PROGRESS
        self.last_trigger = ""
        self.recoveries = 0
        self.fresh_streak = 0
        self.active = False
        self.stage = 0
        self.heading = None
        self.entered = 0
        self.after_recovery = False
        self.attempted = Counter()
        self.last_match = None
        self.survey = None
        self.failed_departures = 0
        self.boundary = None
        self.continuous = False
        self.recent_views = deque(maxlen=90)
        self.departure_reference = None
        self.departure_views = deque(maxlen=12)

    def observe(self, jpeg, tick, yaw, pitch, place, moved=False):
        if self.last_tick is None:
            self.last_novel = tick
        self.last_tick = tick
        if moved:
            self.last_move = tick
        if tick - self.last_sample < HZ // 2:
            return
        self.last_sample = tick
        view = project_view(jpeg, yaw, pitch, tick, place)
        if view.mask.sum() < 65 or view.image[view.mask].std() < 11:
            self.fresh_streak = 0
            self.last_match = None
            return
        self.recent_views.append((view, yaw))
        if self.boundary and self.departure_reference and moved:
            prior_area, distance = self.departure_reference.match(view, yaw)
            if prior_area is not None:
                self.departure_views.append((tick, distance > 16))
        prior, error = self.atlas.match(view, yaw, min_age=12 * HZ)
        familiar = prior is not None and error <= 13.0
        self.last_match = prior.place if familiar else None
        moving_view = tick - self.last_move <= 12
        if moving_view:
            self.samples.append((tick, familiar))
            if familiar:
                self.fresh_streak = 0
            else:
                self.fresh_streak += 1
                if self.fresh_streak >= 3:
                    self.last_novel = tick
                    if self.after_recovery:
                        self.after_recovery = False
        while self.samples and self.samples[0][0] < tick - WINDOW:
            self.samples.popleft()
        _, nearest = self.atlas.match(view, yaw)
        if nearest > 6:
            self.atlas.add(view, yaw)

    def summary(self, tick):
        repeated = sum(flag for _, flag in self.samples)
        return {
            "seconds_since_new_views": round((tick - self.last_novel) / HZ, 1),
            "familiar_moving_views": repeated,
            "sampled_moving_views": len(self.samples),
            "last_familiar_place": None
            if self.last_match is None
            else f"P{self.last_match + 1}",
            "recoveries": self.recoveries,
            "failed_departures": self.failed_departures,
            **(
                {
                    "tested_steps": self.survey.steps,
                    "survey_places": len(self.survey.visits),
                }
                if self.survey
                else {}
            ),
            "state": "following boundary"
            if self.boundary
            else "testing passages"
            if self.survey
            else "changing route"
            if self.active
            else "checking departure"
            if self.after_recovery
            else "exploring",
        }

    def check(self, tick):
        if self.boundary or self.active or tick - self.last_recovery < WINDOW:
            return
        count = len(self.samples)
        repeated = sum(flag for _, flag in self.samples)
        revisiting = (
            count >= 12
            and self.samples[-1][0] - self.samples[0][0] >= 20 * HZ
            and repeated >= 0.88 * count
            and tick - self.last_novel >= 12 * HZ
        )
        aged = tick - self.last_novel >= NO_PROGRESS
        if not (revisiting or aged):
            return
        self.last_trigger = (
            "Most moving views in the last 30 seconds were familiar."
            if revisiting
            else "45 seconds without sustained new moving views."
        )
        if (
            self.after_recovery
            or self.last_recovery >= 0
            and tick - self.last_novel >= WINDOW
        ):
            self.failed_departures += 1
        self.active = self.after_recovery = True
        self.last_recovery = self.entered = tick
        self.recoveries += 1
        self.stage = 0
        self.heading = None
        self.fresh_streak = 0

    def boundary_for(self, game):
        if self.continuous:
            if self.boundary is None:
                self.boundary = BoundaryTravel(game.tick, game.yaw, self.recoveries)
            return self.boundary
        if self.boundary:
            enough_views = (
                len(self.departure_views) >= 8
                and self.departure_views[-1][0] - self.departure_views[0][0] >= 3 * HZ
                and sum(new for _, new in self.departure_views)
                >= 0.75 * len(self.departure_views)
            )
            if (
                game.tick - self.boundary.started >= 20 * HZ
                and self.boundary.moving >= 6 * HZ
                and enough_views
            ):
                self.boundary = self.survey = self.departure_reference = None
                self.departure_views.clear()
                self.active = self.after_recovery = False
                self.failed_departures = self.fresh_streak = 0
                self.last_novel = self.last_recovery = game.tick
        elif (
            self.survey
            and self.survey.steps >= 20
            and game.tick - self.last_novel >= 60 * HZ
            and self.survey.pending is None
        ):
            self.boundary = BoundaryTravel(game.tick, game.yaw, self.recoveries)
            self.departure_reference = VisualAtlas()
            for view, yaw in self.recent_views:
                self.departure_reference.add(view, yaw)
            self.departure_views.clear()
        return self.boundary

    def restore(self, event, origin_yaw):
        progress = event.get("exploration") or {}
        if event.get("boundary_travel"):
            if self.boundary is None:
                self.departure_reference = VisualAtlas()
                for view, yaw in self.recent_views:
                    self.departure_reference.add(view, yaw)
            self.boundary = BoundaryTravel.restore(event["boundary_travel"])
        elif progress.get("state") == "exploring":
            self.boundary = self.departure_reference = None
            self.departure_views.clear()
        count = progress.get("recoveries", 0)
        if count > self.recoveries:
            if self.recoveries and progress.get("seconds_since_new_views", 0) >= 30:
                self.failed_departures += 1
            self.last_recovery = self.entered = event["observed_tick"]
            self.recoveries = count
        if "failed_departures" in progress:
            self.failed_departures = progress["failed_departures"]
        self.active = progress.get("state") in (
            "changing route",
            "testing passages",
            "following boundary",
        )
        self.after_recovery = (
            self.active or progress.get("state") == "checking departure"
        )
        move = event.get("passage_test")
        if move and move.get("result") != "interrupted":
            if self.survey is None:
                self.survey = PassageSurvey(origin_yaw)
            survey = self.survey
            start, end = tuple(move["from"]), tuple(move["to"])
            heading = move["heading"]
            crossed = move["result"] == "crossed"
            survey.attempts[start, heading] += 1
            survey.edges[start, heading] = crossed
            survey.steps += 1
            survey.cell = end
            if crossed:
                survey.visits[end] += 1
                survey.edges[end, (heading + 2) % 4] = True
                survey.facing = heading
            survey.last = move
        elif progress.get("state") == "exploring":
            self.survey = None

    def choose(self, game, memory, vision, jpeg=None):
        """Reposition, select an untried branch and commit ordinary forward input to it."""
        if vision.get("enemy") or vision.get("switch"):
            return None
        if self.survey is None and self.failed_departures >= 1 and self.recoveries >= 2:
            self.survey = PassageSurvey(memory.origin_yaw or 0)
        if self.survey:
            if (
                self.survey.steps >= 8
                and len(self.survey.visits) >= 4
                and game.tick - self.last_novel < 4 * HZ
                and self.fresh_streak >= 5
            ):
                self.survey = None
                self.failed_departures = 0
                self.active = self.after_recovery = False
                return None
            return self.survey.choose(game, vision, jpeg)
        if not self.active:
            return None
        if vision.get("platform"):
            self.active = False
            return (
                "board_platform",
                0,
                "Testing the visible platform for an onward connection.",
            )
        if self.stage == 0:
            self.stage = 1
            return "back_up", 0, self.last_trigger
        if self.stage == 1:
            # Directions are compared in the player's issued camera coordinate system.
            origin = memory.origin_yaw or 0
            relative = (game.yaw - origin) % 360
            here = memory.places[memory.here]
            anchor = self.last_match if self.last_match is not None else memory.here
            frontier = memory.frontier()
            if frontier:
                dest, direction = frontier
                if not self.attempted[anchor, direction]:
                    self.attempted[anchor, direction] += 1
                    turn = (direction * 45 - relative + 180) % 360 - 180
                    self.stage = 2
                    self.heading = (game.yaw + turn) % 360
                    return (
                        "branch_turn",
                        turn,
                        f"Following a recorded connection toward an untried opening at P{dest + 1}.",
                    )
            candidates = []
            for offset in (90, -90, 135, -135, 180, 45, -45):
                sector = round(((relative + offset) % 360) / 45) % 8
                failure = here.failures[sector, "walk"]
                dest = here.exits.get(sector)
                visits = memory.places[dest].visits if dest is not None else 0
                candidates.append(
                    (
                        self.attempted[anchor, sector] * 6 + failure * 5 + visits,
                        abs(abs(offset) - 90),
                        offset,
                        sector,
                    )
                )
            _, _, turn, sector = min(candidates)
            self.attempted[anchor, sector] += 1
            self.heading = (game.yaw + turn) % 360
            self.stage = 2
            return "branch_turn", turn, "Looking for a less explored branch."
        if self.stage >= 5 or game.tick - self.entered > 12 * HZ:
            self.active = False
            return None
        self.stage += 1
        if vision.get("landing") and vision.get("clearance") in (
            "jump_up",
            "jump_across",
        ):
            action = "jump_forward"
        elif vision.get("route") and vision.get("clearance") not in (
            "too_low",
            "too_high",
        ):
            action = "follow_route"
        elif vision.get("clearance") in ("too_low", "too_high") and not vision.get(
            "route"
        ):
            if self.stage == 3:
                self.stage = 1
                return (
                    "back_up",
                    0,
                    "This branch faces an obstruction. Inspect the next direction.",
                )
            self.active = False
            return None
        else:
            action = "advance"
        return action, 0, "Testing the new branch across successive moving views."
