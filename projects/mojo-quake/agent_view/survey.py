"""Explore passage connections by moving and measuring the resulting game images."""

import io
import math
from collections import Counter, deque

import numpy as np
from PIL import Image

OFFSETS = ((1, 0), (0, 1), (-1, 0), (0, -1))
PROBES = ("test_passage", "test_ledge")


def survey_keys(action, remaining, frame_ticks):
    jumping = action == "test_ledge"
    elapsed = (54 if jumping else 42) - remaining
    drive_until = 46 if jumping else 14
    boundaries = (8, 12, drive_until, 54 if jumping else 42)
    chunk = min(frame_ticks, next(t for t in boundaries if t > elapsed) - elapsed)
    return chunk, (
        320 if elapsed < drive_until else 0,
        0,
        2 if jumping and 8 <= elapsed < 12 else 0,
    )


def camera_gray(jpeg):
    with Image.open(io.BytesIO(jpeg)) as image:
        return np.asarray(image.convert("L"))[:190].copy()


def radial_flow(before, after):
    import cv2

    mask = np.zeros_like(before)
    mask[12:185, 3:313] = 255
    mask[118:, 124:196] = 0
    a = cv2.goodFeaturesToTrack(before, 70, 0.012, 6, mask=mask)
    if a is None or len(a) < 5:
        return None
    b, found, errors = cv2.calcOpticalFlowPyrLK(
        before, after, a, None, winSize=(15, 15), maxLevel=2
    )
    a, b = a.reshape(-1, 2), b.reshape(-1, 2)
    # Horizontal expansion on a fixed heading distinguishes forward travel
    # from the weapon animation or a vertical camera bob against a wall.
    use = (
        found.ravel().astype(bool)
        & (errors.ravel() < 20)
        & (np.abs(a[:, 0] - 159.5) > 22)
    )
    if use.sum() < 5:
        return None
    return float(np.median((b[use, 0] - a[use, 0]) / (a[use, 0] - 159.5)))


class PassageSurvey:
    def __init__(self, origin):
        self.origin = origin
        self.cell = (0, 0)
        self.visits = Counter({self.cell: 1})
        self.edges = {}
        self.attempts = Counter()
        self.facing = 0
        self.pending = None
        self.previous = None
        self.flow = []
        self.last = None
        self.mechanisms = set()
        self.steps = 0
        self.snapshots = [[] for _ in range(4)]
        self.revisits = 0
        self.last_registration = None

    def neighbor(self, cell, direction):
        dx, dy = OFFSETS[direction]
        return cell[0] + dx, cell[1] + dy

    def next_edge(self, preferred):
        # Closest reachable junction with an untested direction first. Retry
        # blocked approaches with a jump only after walking options run out.
        for jumping in (False, True):
            queue = deque([(self.cell, None)])
            seen = {self.cell}
            while queue:
                node, first = queue.popleft()
                options = []
                for k in range(4):
                    dest = self.neighbor(node, k)
                    edge = self.edges.get((node, k))
                    if (edge is None and not jumping) or (
                        edge is False and jumping and self.attempts[node, k] < 2
                    ):
                        options.append(
                            (
                                bool(self.visits[dest]),
                                k != preferred,
                                k != self.facing,
                                (k - self.facing) % 4,
                                k,
                            )
                        )
                    if edge is True and dest not in seen:
                        seen.add(dest)
                        queue.append((dest, k if first is None else first))
                if options:
                    return (
                        (min(options)[-1], jumping) if first is None else (first, False)
                    )
        # A door or lift can change which connections are open.
        k = min(
            range(4),
            key=lambda k: (
                self.attempts[self.cell, k],
                self.visits[self.neighbor(self.cell, k)],
            ),
        )
        return k, True

    def register_view(self, jpeg, yaw, pitch):
        facing = round((yaw - self.origin) / 90) % 4
        error = (yaw - self.origin - facing * 90 + 180) % 360 - 180
        if abs(error) > 2.5 or abs(pitch) > 3:
            return
        with Image.open(io.BytesIO(jpeg)) as frame:
            world = (
                frame.crop((8, 12, 312, 143))
                .convert("L")
                .resize((40, 18), Image.Resampling.BOX)
            )
            descriptor = np.asarray(world, dtype=np.int16)
        if descriptor.std() < 10:
            return
        choices = self.snapshots[facing]
        best, distance = None, float("inf")
        for previous, node in choices:
            diff = descriptor - previous
            score = float(
                np.abs(diff - np.median(diff)).mean() + 0.35 * abs(diff.mean())
            )
            if score < distance:
                best, distance = node, score
        if distance < 4.5 and best != self.cell:
            self.last_registration = {
                "estimated": list(self.cell),
                "recognized": list(best),
                "image_error": round(distance, 2),
            }
            self.revisits += 1
            self.cell = best
            self.pending = None
        if distance >= 5.0:
            choices.append((descriptor, self.cell))
            if len(choices) > 200:
                choices.pop(0)

    def ready_probe(self, yaw, pitch):
        if self.pending is None:
            return None
        direction, jump = self.pending
        error = (self.origin + direction * 90 - yaw + 180) % 360 - 180
        if abs(error) <= 2 and abs(pitch) <= 3:
            return "test_ledge" if jump else "test_passage"
        return None

    def choose(self, game, vision, jpeg=None):
        if self.pending is None and jpeg is not None:
            self.register_view(jpeg, game.yaw, game.pitch)
        facing = round((game.yaw - self.origin) / 90) % 4
        if (
            self.pending is None
            and vision.get("platform")
            and (self.cell, facing) not in self.mechanisms
        ):
            self.mechanisms.add((self.cell, facing))
            self.pending = None
            return (
                "board_platform",
                0,
                "Testing the marked surface before trying another passage.",
            )
        if self.pending is None:
            preferred = None
            if vision.get("route") and vision.get("clearance") in (
                "walkable",
                "jump_up",
            ):
                yaw = game.yaw - math.degrees(math.atan((vision["route"][0] - 50) / 50))
                preferred = round((yaw - self.origin) / 90) % 4
            landing = vision.get("landing")
            if (
                landing
                and vision.get("clearance") in ("jump_up", "jump_across")
                and abs(landing[0] - 50) < 22
                and self.attempts[self.cell, facing] < 2
            ):
                self.pending = facing, True
            else:
                self.pending = self.next_edge(preferred)
        k, jump = self.pending
        turn = (self.origin + k * 90 - game.yaw + 180) % 360 - 180
        if abs(turn) > 2 or abs(game.pitch) > 3:
            return (
                "branch_turn",
                turn,
                "Facing the next passage selected from the explored connections.",
            )
        return (
            "test_ledge" if jump else "test_passage",
            0,
            "Testing a blocked approach with a jump."
            if jump
            else "Walking a short distance to test this connection.",
        )

    def begin(self, jpeg):
        self.previous = camera_gray(jpeg)
        self.flow = []

    def sample(self, jpeg):
        frame = camera_gray(jpeg)
        value = radial_flow(self.previous, frame)
        if value is not None:
            self.flow.append(value)
        self.previous = frame

    def finish(self, completed):
        direction, jump = self.pending
        origin = self.cell
        expansion = sum(max(-0.25, min(0.25, x)) for x in self.flow)
        advanced = (
            expansion > 0.048
            and sum(x > 0.004 for x in self.flow) >= 3
            and (sum(x < -0.02 for x in self.flow) < 3 or expansion > 0.16)
        )
        if completed:
            self.steps += 1
            self.attempts[origin, direction] += 1
            self.edges[origin, direction] = advanced
            if advanced:
                self.cell = self.neighbor(origin, direction)
                self.visits[self.cell] += 1
                self.edges[self.cell, (direction + 2) % 4] = True
                self.facing = direction
        self.last = {
            "from": list(origin),
            "to": list(self.cell),
            "heading": direction,
            "jump": jump,
            "result": "interrupted"
            if not completed
            else "crossed"
            if advanced
            else "no confirmed travel",
            "flow_samples": len(self.flow),
            "net_expansion": round(expansion, 3),
        }
        self.pending = self.previous = None
        return self.last


class BoundaryTravel:
    """Keep moving along the visible boundary when isolated steps repeatedly revisit it."""

    def __init__(self, tick, yaw, attempt):
        self.started = tick
        self.heading = yaw
        self.hand = 1 if attempt % 2 else -1
        self.turns = self.held = self.stalled = self.moving = 0
        self.next_bend = 192
        self.previous = None
        self.preference = 0
        self.turning = False
        self.last_lane_turn = -10000

    def begin(self, jpeg):
        self.previous = camera_gray(jpeg)

    def use_lane(self, lanes, game):
        if (
            not lanes
            or lanes["pick"] not in ("left", "right")
            or game.tick - self.last_lane_turn < 72
        ):
            return False
        center = lanes["lanes"].get("center", {}).get("range_estimate")
        best = lanes["lanes"][lanes["pick"]]["range_estimate"]
        if self.stalled < 12 and (
            center is None or best is None or center >= 115 or best < center + 28
        ):
            return False
        offset = 32 if lanes["pick"] == "left" else -32
        self.heading = (lanes["source_yaw"] + offset) % 360
        self.last_lane_turn = game.tick
        self.stalled = 0
        return True

    def controls(self, game, ticks):
        if self.stalled >= 24 or self.held >= 870:
            # Continue driving through the turn, then give the new heading time to work.
            self.turns += 1
            sign = self.preference or -self.hand
            self.preference = 0
            offset = sign * (60, 95, 42, 77)[self.turns % 4]
            if self.turns % 8 == 0:
                offset = 140
            self.heading = (self.heading + offset) % 360
            self.held = self.stalled = 0
            self.next_bend = 192
            if self.turns % 6 == 0:
                self.hand *= -1
        if self.held >= self.next_bend:
            self.heading = (self.heading + self.hand * 7) % 360
            self.next_bend += 96
        turn = (self.heading - game.yaw + 180) % 360 - 180
        self.turning = abs(turn) > 5 or abs(game.pitch) > 4
        game.yaw = (game.yaw + max(-24, min(24, turn))) % 360
        game.pitch += max(-12, min(12, -game.pitch))
        self.held += ticks
        return 320, -self.hand * 85 if self.held > 108 else 0, 0

    def sample(self, jpeg, ticks):
        frame = camera_gray(jpeg)
        flow = None if self.turning else radial_flow(self.previous, frame)
        self.previous = frame
        if self.turning:
            return
        if self.held > 24 and abs(flow or 0) < 0.007:
            self.stalled += ticks
        else:
            self.stalled = max(0, self.stalled - 2 * ticks)
            if flow is not None and abs(flow) >= 0.007:
                self.moving += ticks

    def snapshot(self):
        return {
            k: getattr(self, k)
            for k in (
                "started",
                "heading",
                "hand",
                "turns",
                "held",
                "stalled",
                "moving",
                "next_bend",
            )
        }

    @classmethod
    def restore(cls, saved):
        move = cls(saved["started"], saved["heading"], 0)
        for k in move.snapshot():
            setattr(move, k, saved[k])
        return move
