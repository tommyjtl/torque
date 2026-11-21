"""Remember which camera-predicted passages the live player has actually explored."""

import math
from collections import Counter, deque

import numpy as np


class PassageGraph:
    def __init__(self):
        self.landmarks = []
        self.positions = []
        self.edges = {}
        self.controls = {}
        self.visits = Counter()
        self.used = Counter()
        self.missed = Counter()
        self.tested_headings = {}
        self.tested_jumps = {}
        self.waiting_for = None
        self.unavailable = 0
        self.proposed = None
        self.root = None
        self.current = None
        self.frontier = None
        self.return_target = None
        self.summary = {}
        self.recent = deque(maxlen=8)
        self.last_input = None

    def accept_location(self, index, new_landmarks, first_new, estimate):
        if index == len(self.landmarks):
            self.landmarks.append(new_landmarks[index - first_new])
            self.positions.append(estimate.copy())
            self.edges[index] = set()
        return index

    def forget_transition(self):
        self.proposed = self.current = self.last_input = None

    def distances(self, start):
        found = {start: 0}
        pending = deque([start])
        while pending:
            src = pending.popleft()
            for dest in self.edges[src]:
                if dest not in found:
                    found[dest] = found[src] + 1
                    pending.append(dest)
        return found

    def next_probes(self):
        start, goal = self.proposed, self.frontier
        if start is None or goal is None or start == goal:
            return []
        queue = deque([(start, None)])
        seen = {start}
        while queue:
            here, first = queue.popleft()
            for after in self.edges[here]:
                step = first or self.controls.get((here, after))
                if after == goal and step:
                    return [step]
                if after not in seen and step:
                    seen.add(after)
                    queue.append((after, step))
        return []

    def scores(self, result, position):
        first_new = len(self.landmarks)
        new_landmarks = result["new_landmarks"]
        here = self.accept_location(
            result["place_id"], new_landmarks, first_new, position
        )
        if self.current is not None and self.proposed is not None:
            self.edges[self.current].add(here)
            self.used[self.current, here] += 1
            if self.last_input:
                self.recent.append(
                    {
                        "from": self.current,
                        "input": self.last_input,
                        "to": here,
                        "already_visited": bool(self.visits[here]),
                    }
                )
        self.current = here
        if self.root is None:
            self.root = here
        self.visits[here] += 1
        dests = []
        previous_controls = {
            dest: self.controls.get((here, dest)) for dest in self.edges[here]
        }
        for b in result["branches"]:
            if b["place_id"] is None:
                dests.append(None)
                continue
            dest = self.accept_location(
                b["place_id"],
                new_landmarks,
                first_new,
                self.positions[here] + (b["delta"] if b["support"] >= 0.35 else 0),
            )
            dests.append(dest)
            if b["hp"] != 0:
                self.edges[here].add(dest)
                self.controls[here, dest] = b["option"]
        # Only camera-matched batches become evidence about directions tested at this place.
        sectors = self.tested_headings.setdefault(here, {})
        for direction, branch in zip(dests, result["branches"]):
            option = branch["option"]
            if branch.get("jump_comparison"):
                self.tested_jumps.setdefault(here, Counter())[
                    round(option.heading / 15) % 24
                ] += 1
            if option.kind in ("walk", "explore_lane"):
                key = round(option.heading / 5) % 72
                count, _ = sectors.get(key, (0, False))
                sectors[key] = (count + 1, direction is not None and direction != here)
        for old_dest, old_input in previous_controls.items():
            if old_input is None:
                continue
            outcomes = [
                dest
                for dest, b in zip(dests, result["branches"])
                if b["option"] == old_input
            ]
            if old_dest in outcomes:
                self.missed[here, old_dest] = 0
            elif outcomes:
                self.missed[here, old_dest] += 1
                if self.missed[here, old_dest] >= 2 and old_dest not in dests:
                    self.edges[here].discard(old_dest)
                    self.controls.pop((here, old_dest), None)
        local = self.distances(here)
        root = self.distances(self.root)
        candidates = [i for i in local if not self.visits[i]]
        direct = {
            dest
            for dest, b in zip(dests, result["branches"])
            if dest in candidates and b["hp"] != 0 and b["damage"] <= 8
        }
        if (
            self.return_target in local
            and self.return_target != here
            and self.unavailable < 3
        ):
            self.frontier = self.return_target
        elif direct:
            if self.frontier not in direct:
                self.frontier = max(
                    direct,
                    key=lambda i: (
                        root.get(i, 0),
                        np.linalg.norm(self.positions[i] - self.positions[here]),
                    ),
                )
        elif self.frontier not in candidates or self.unavailable >= 3:
            choices = [
                i for i in candidates if i != self.waiting_for or self.unavailable < 3
            ]
            self.frontier = min(
                choices, key=lambda i: (local[i], -root.get(i, 0)), default=None
            )
        # Distances in the reverse graph provide a shortest next step toward the frontier.
        toward = {}
        if self.frontier is not None:
            reverse = {}
            for src in local:
                for dst in self.edges[src]:
                    reverse.setdefault(dst, []).append(src)
            toward = {self.frontier: 0}
            queue = deque([self.frontier])
            while queue:
                after = queue.popleft()
                for before in reverse.get(after, ()):
                    if before not in toward:
                        toward[before] = toward[after] + 1
                        queue.append(before)
        scores = []
        any_step = False
        for branch, dest in zip(result["branches"], dests):
            on_route = (
                dest in toward and toward[dest] < toward[here]
                if here in toward
                else False
            )
            branch["route_step"] = on_route
            any_step |= on_route
            bonus = 0.0
            if dest is not None:
                if dest == here:
                    bonus -= 2.5
                elif dest in toward and toward[dest] < toward[here]:
                    bonus += 4.5
                bonus += (
                    1 if not self.visits[dest] else -1.5 * math.log1p(self.visits[dest])
                )
                bonus -= math.log1p(self.used[here, dest])
                repeats = sum(
                    edge["from"] == here and edge["to"] == dest for edge in self.recent
                )
                if repeats and dest != self.frontier:
                    bonus -= min(4, 1.6 * repeats)
            scores.append(bonus)
        if self.frontier != self.waiting_for or any_step:
            self.unavailable = 0
        else:
            self.unavailable += 1
        self.waiting_for = self.frontier
        self.summary = {
            "at": here,
            "target": self.frontier,
            "purpose": "revisit door"
            if self.frontier is not None and self.frontier == self.return_target
            else "explore",
            "steps": toward.get(here),
            "visited": len(self.visits),
            "reachable": len(local),
        }
        return dests, scores
