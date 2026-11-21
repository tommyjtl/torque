"""A per-run graph of visited views, driven only by pixels and issued controls."""

import math
from collections import Counter, deque
from dataclasses import dataclass, field

from game import view_signature
from mechanisms import MechanismMemory
from PIL import ImageChops, ImageOps, ImageStat

# Heading is relative to the first observed facing. A sector is one eighth-turn.
RELATIVE = (
    "ahead",
    "ahead-left",
    "left",
    "back-left",
    "behind",
    "back-right",
    "right",
    "ahead-right",
)


def sector(yaw):
    return math.floor(yaw / 45 + 0.5) % 8


def angle_delta(a, b):
    return abs((a - b + 180) % 360 - 180)


def appearance(jpeg):
    gray = view_signature(jpeg).resize((24, 14))
    # Lifts, flickering light styles and muzzle flashes can change brightness at rest.
    normalized = ImageOps.autocontrast(gray, cutoff=2)
    return gray, normalized, ImageStat.Stat(gray).stddev[0]


def similar(a, b, *, revisit=False):
    raw = ImageStat.Stat(ImageChops.difference(a[0], b[0])).mean[0]
    if revisit and min(a[2], b[2]) < 8:
        return False
    if raw <= (3 if revisit else 6):
        return True
    if min(a[2], b[2]) < 3:
        return False
    scaled = ImageStat.Stat(ImageChops.difference(a[1], b[1])).mean[0]
    return scaled < (6 if revisit else 12)


@dataclass
class Place:
    x: float
    y: float
    visits: int = 1
    landmark: str = ""
    views: dict = field(default_factory=dict)
    failures: Counter = field(default_factory=Counter)
    exits: dict = field(default_factory=dict)
    openings: set = field(default_factory=set)

    def remember(self, signature, yaw, pitch):
        key = (round(yaw / 12) % 30, round(pitch / 12))
        views = self.views.setdefault(key, [])
        if any(similar(v, signature) for v in views):
            return
        views.append(signature)
        del views[:-3]

    def matches(self, signature, yaw, pitch, *, revisit=False):
        key = (round(yaw / 12) % 30, round(pitch / 12))
        return any(
            similar(v, signature, revisit=revisit) for v in self.views.get(key, ())
        )


@dataclass
class Move:
    direction: int
    kind: str
    yaw: float
    pitch: float
    before: tuple
    first_tick: int
    last_tick: int
    intention: tuple = (None, None)


class RouteMemory:
    def __init__(self):
        self.places = [Place(0, 0)]
        self.here = 0
        self.origin_yaw = None
        self.yaw = self.pitch = self.tick = 0
        self.last_img = None
        self.last_sample = -100
        self.driving = False
        self.pending = None
        self.skill_book = None
        self.character = None
        self.character_track = None
        self.panels = None
        self.mechanisms = MechanismMemory()
        self.lane_sense = None
        self.exploration = None
        self.checkpoints = None
        self.plans = None
        self.intention = (None, None)
        self.last_outcome = "Exploration started."
        self.turns = self.stalls = 0
        self.entry = None
        self.trail = [0]
        self.path = deque([0], maxlen=6)
        self.visited_edges = set()

    def _finish(self, jpeg, tick, force=False):
        move = self.pending
        # Short or interrupted jump inputs can end while still airborne.
        ready = tick >= move.last_tick + 12 and (
            move.kind != "jump" or tick >= move.first_tick + 60
        )
        if not ready and not force:
            return
        self.pending = None
        place = self.places[self.here]
        sig = appearance(jpeg)
        key = (move.direction, move.kind)
        if (
            (not ready and move.kind == "jump")
            or angle_delta(self.yaw, move.yaw) > 8
            or abs(self.pitch - move.pitch) > 8
        ):
            self.last_outcome = (
                "Movement uncertain; the comparison view changed before settling."
            )
            return
        stalled = (
            similar(move.before, sig)
            or place.matches(sig, move.yaw, move.pitch)
            or sig[2] < 3
        )
        if (
            self.skill_book
            and ready
            and sig[2] >= 3
            and move.last_tick - move.first_tick >= 8
        ):
            self.skill_book.record(*move.intention, moved=not stalled)
        if stalled:
            place.failures[key] += 1
            self.stalls += 1
            self.last_outcome = f"{move.kind.title()} from P{self.here + 1} had no confirmed horizontal progress."
        else:
            # Require a distinctive view, the same facing, and a substantially tighter match for loop closure.
            dest = next(
                (
                    n
                    for n in reversed(self.trail)
                    if n != self.here
                    and self.places[n].matches(sig, move.yaw, move.pitch, revisit=True)
                ),
                None,
            )
            if dest is None:
                dest = len(self.places)
                angle = math.radians(move.direction * 45)
                self.places.append(
                    Place(place.x - math.sin(angle), place.y - math.cos(angle))
                )
                verb = "Reached a new view"
            else:
                self.places[dest].visits += 1
                verb = "Recognized a previously visited view"
            place.failures.pop(key, None)
            place.exits[move.direction] = dest
            self.entry = ((move.direction + 4) % 8, self.here)
            self.visited_edges.add(tuple(sorted((self.here, dest))))
            self.here = dest
            # Most recently seen first when matching similar, previously visited views.
            if dest in self.trail:
                self.trail.remove(dest)
            self.trail.append(dest)
            self.path.append(dest)
            self.turns = self.stalls = 0
            self.last_outcome = f"{verb} at P{dest + 1}."
        self.places[self.here].remember(sig, move.yaw, move.pitch)
        self.last_sample = tick

    def track(self, jpeg, tick, yaw, pitch, forward=0, side=0, buttons=0):
        """Observe an executed input chunk. No entity, position or map data is accepted."""
        if self.origin_yaw is None:
            self.origin_yaw = yaw
        yaw = (yaw - self.origin_yaw) % 360
        rotated = angle_delta(yaw, self.yaw) > 5 or abs(pitch - self.pitch) > 5
        moving = bool(forward or side)
        direction = (
            sector(yaw - math.degrees(math.atan2(side, forward))) if moving else None
        )
        kind = "jump" if buttons & 2 else "walk"
        if (
            self.driving
            and moving
            and not rotated
            and self.pending
            and direction == self.pending.direction
        ):
            # The run-up, jump pulse and continued forward hold are one attempt.
            if buttons & 2:
                self.pending.kind = "jump"
            kind = self.pending.kind
        new_move = moving and (
            not self.driving
            or rotated
            or (
                self.pending
                and (direction != self.pending.direction or kind != self.pending.kind)
            )
        )
        if self.pending and (rotated or new_move):
            self._finish(self.last_img, self.tick, force=True)
        if rotated:
            self.turns += 1
        if new_move:
            before = appearance(
                jpeg if rotated or self.last_img is None else self.last_img
            )
            self.places[self.here].remember(before, yaw, pitch)
            self.pending = Move(
                direction, kind, yaw, pitch, before, self.tick, tick, self.intention
            )
        if self.pending and moving:
            self.pending.last_tick = tick
        self.yaw, self.pitch = yaw, pitch
        if self.pending and not moving:
            self._finish(jpeg, tick)
        if not self.pending and (rotated or tick - self.last_sample >= 16):
            self.places[self.here].remember(appearance(jpeg), yaw, pitch)
            self.last_sample = tick
        if self.exploration:
            self.exploration.observe(jpeg, tick, yaw, pitch, self.here, moved=moving)
        self.tick, self.last_img, self.driving = tick, jpeg, moving

    def same_known_view(self, first, latest):
        place = self.places[self.here]
        return all(
            place.matches(appearance(jpg), self.yaw, self.pitch)
            for jpg in (first, latest)
        )

    def describe(self, scene):
        if not self.pending and abs(self.pitch) < 35:
            self.places[self.here].landmark = scene[:120]
            return True
        return False

    def remember_passages(self, vision):
        place = self.places[self.here]
        for marker in ("route", "landing", "platform"):
            point = vision.get(marker)
            if point is None:
                continue
            if (
                marker == "route"
                and abs(point[0] - 50) < 18
                and vision.get("clearance") in ("too_low", "too_high")
            ):
                continue
            turn = -math.degrees(math.atan((point[0] - 50) / 50))
            place.openings.add(sector(self.yaw + turn))

    def frontier(self):
        """Find a seen, untried opening via confirmed outgoing connections."""
        pending = deque([(self.here, None)])
        seen = {self.here}
        while pending:
            index, first = pending.popleft()
            place = self.places[index]
            unused = sorted(
                k
                for k in place.openings
                if k not in place.exits
                and place.failures[k, "walk"] < 2
                and place.failures[k, "jump"] < 2
            )
            if unused:
                heading = (
                    first
                    if first is not None
                    else min(unused, key=lambda k: angle_delta(k * 45, self.yaw))
                )
                return index, heading
            for heading, neighbor in place.exits.items():
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                pending.append((neighbor, heading if first is None else first))
        return None

    def guidance(self, route, landing=None):
        place = self.places[self.here]
        ahead = sector(self.yaw)
        lessons = getattr(self, "movement_lessons", None)

        def relative(absolute):
            return RELATIVE[(absolute - ahead) % 8]

        blocked = []
        actions = {
            "advance": (self.yaw, "walk"),
            "advance_fire": (self.yaw, "walk"),
            "jump_forward": (self.yaw, "jump"),
            "back_up": (self.yaw + 180, "walk"),
            "strafe_left": (self.yaw + 90, "walk"),
            "strafe_right": (self.yaw - 90, "walk"),
        }
        if route is not None:
            actions["follow_route"] = (
                self.yaw - math.degrees(math.atan((route[0] - 50) / 50)),
                "walk",
            )
        if landing is not None:
            actions["jump_forward"] = (
                self.yaw - math.degrees(math.atan((landing[0] - 50) / 50)),
                "jump",
            )
        for action, (angle, kind) in actions.items():
            direction = sector(angle)
            if place.failures[direction, kind] >= 2 or (
                kind == "walk" and lessons and lessons.blocks_walk(self.tick, self.here, direction)
            ):
                blocked.append(action)
        if (
            self.pending
            and self.pending.kind == "jump"
            and self.pending.direction == sector(actions["jump_forward"][0])
        ):
            blocked.append("jump_forward")
        failures = [
            f"{relative(k)}: {kind} x{n}"
            for (k, kind), n in place.failures.most_common(4)
        ]
        exits = [f"{relative(k)} to P{v + 1}" for k, v in sorted(place.exits.items())]
        tried = set(place.exits) | {k for k, _ in place.failures}
        untried = [
            relative((ahead + i) % 8)
            for i in (0, 2, 6, 4, 1, 7, 3, 5)
            if (ahead + i) % 8 not in tried
        ]
        path = list(self.path)
        looping = len(path) >= 4 and path[-4:-2] == path[-2:]
        recover = (
            self.stalls >= 2
            or self.turns >= 5
            or looping
            or max(place.failures[ahead, "walk"], place.failures[ahead, "jump"]) >= 2
        )
        hint = "Explore a visible untried passage."
        if abs(self.pitch) >= 32:
            hint = "Level the camera to see the floor and routes."
        elif looping:
            hint = "You have traveled between the same two places twice. Try an untried exit."
        elif recover:
            hint = "Leave this spot. Back up or strafe toward an untried direction; use a known return path if cornered."
        escapes = ["back_up", "strafe_left", "strafe_right"]
        if self.turns < 3 and ahead not in tried:
            escapes.append("advance")
        if self.turns < 3:
            escapes.append("turn_around")
        if abs(self.pitch) >= 25:
            escapes.insert(0, "level_view")
        if looping:
            alternatives = [
                a
                for a in escapes
                if a not in actions
                or place.exits.get(sector(actions[a][0])) != path[-2]
            ]
            escapes = alternatives or escapes
        lesson = None
        if lessons and lessons.mode == "active" and "advance" in blocked:
            attempts = place.failures[ahead, "walk"]
            evidence = (
                f"{attempts} walks on this heading at P{self.here + 1} produced no confirmed progress."
                if attempts >= 2 else "The camera stayed nearly still while forward was held."
            )
            lesson = {"lesson": "release_blocked_forward", "advice": evidence + " Try a different heading or step back."}
            escapes.extend(("turn_left", "turn_right"))
        return {
            **({"movement_lesson": lesson} if lesson else {}),
            "place": f"P{self.here + 1}",
            "landmark": place.landmark,
            **(
                {"mechanism": self.mechanisms.context()} if self.mechanisms.door else {}
            ),
            **({"checkpoints": self.checkpoints.context()} if self.checkpoints else {}),
            **(
                {"progress": self.exploration.summary(self.tick)}
                if self.exploration
                else {}
            ),
            "previous_places": [
                f"P{n + 1}: {self.places[n].landmark or 'unlabeled view'}"
                for n in path[-4:-1]
            ],
            "escape_options": escapes if recover else [],
            "came_from": f"P{self.entry[1] + 1} ({relative(self.entry[0])})"
            if self.entry
            else "start",
            "visits": place.visits,
            "last_outcome": self.last_outcome,
            "known_passages": exits,
            "unsuccessful": failures,
            "untried": untried[:4],
            "blocked_inputs": sorted(set(blocked)),
            "recover": recover,
            "pitch": round(self.pitch),
            "hint": hint,
        }

    def diagram(self):
        # Keep the browser payload bounded. The decision map keeps the older places.
        visible = self.trail[-48:]
        ids = set(visible)
        return {
            "current": self.here + 1,
            "settling": self.pending is not None,
            "heading": round(self.yaw),
            "total": len(self.places),
            "places": [
                [
                    n + 1,
                    round(self.places[n].x, 2),
                    round(self.places[n].y, 2),
                    self.places[n].visits,
                    self.places[n].landmark,
                ]
                for n in visible
            ],
            "failed_sectors": sorted(
                {
                    k
                    for (k, kind), count in self.places[self.here].failures.items()
                    if count >= 2
                }
            ),
            "links": [
                [a + 1, b + 1]
                for a, b in sorted(self.visited_edges)
                if a in ids and b in ids
            ],
            "guidance": self.guidance(None),
        }
