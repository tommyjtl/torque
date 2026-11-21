"""Compare short input sequences in an isolated Quake instance from this run's own save."""

import math
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import cv2
import numpy as np
from floor_motion import FloorMotion
from landmarks import PanelScout, aim_angles
from lift_camera import released_camera
from panorama_plan import PanoramaPlan
from passage_graph import PassageGraph
from place_recognition import PlaceCamera
from survey import camera_gray
from swim_probe import vertical_control


def signed(angle):
    return (angle + 180) % 360 - 180


@dataclass(frozen=True)
class Option:
    heading: float
    kind: str = "walk"
    duration: int = 80
    pitch: float = 0
    launch_tick: int = 8
    onward: tuple = ()

    def rows(self, yaw, pitch):
        """The live player and the preview execute the same bounded ordinary inputs."""
        if self.onward:
            rows = replace(self, onward=()).rows(yaw, pitch)
            for step in self.onward:
                _, _, _, _, prior_heading, prior_pitch, _ = rows[-1]
                rows.append((12, 0, 0, 0, prior_heading, prior_pitch, 0))
                rows.extend(step.rows(prior_heading, prior_pitch))
            return rows
        if self.kind == "watch_passage":
            return [(min(8, self.duration - t), 0, 0, 0, yaw, pitch, 0) for t in range(0, self.duration, 8)]
        if self.kind == "clear_corner":
            return [(12, -240, 0, 0, yaw, pitch, 0)] + Option(self.heading, "walk", self.duration, 0).rows(yaw, pitch)
        if self.kind in ("hold_for_lift", "ride_to_landing"):
            hold = self.duration if self.kind == "hold_for_lift" else self.duration - 40
            start = [
                (min(12, hold - t), 0, 0, 0, yaw, pitch, 0) for t in range(0, hold, 12)
            ]
            return (
                start
                if self.kind == "hold_for_lift"
                else start + Option(self.heading, "walk", 40).rows(yaw, pitch)
            )
        turn = signed(self.heading - yaw)
        chunks = math.ceil(abs(turn) / 28)
        rows = [
            (
                4,
                0,
                0,
                0,
                (yaw + turn * (i + 1) / chunks) % 360,
                pitch + (self.pitch - pitch) * (i + 1) / chunks,
                0,
            )
            for i in range(chunks)
        ]
        elapsed = 0
        while elapsed < self.duration:
            stop = self.duration
            if self.kind == "jump":
                stop = min(
                    t
                    for t in (self.launch_tick, self.launch_tick + 4, self.duration)
                    if t > elapsed
                )
            elif self.kind in ("test_control", "board"):
                stop = next(
                    n
                    for n in sorted(
                        {
                            min(8, self.duration),
                            max(12, self.duration - 24),
                            self.duration,
                        }
                    )
                    if n > elapsed
                )
            n = min(stop - elapsed, 12)
            forward = 320
            buttons = (
                2
                if self.kind == "jump"
                and self.launch_tick <= elapsed < self.launch_tick + 4
                else 0
            )
            up = 240 if self.kind == "surface" else -200 if self.kind == "dive" else 0
            if self.kind in ("test_control", "board"):
                forward = 280 if elapsed < self.duration - 24 else 0
                if self.kind == "test_control" and elapsed < 8:
                    forward = 0
                    buttons |= 1
            heading = self.heading
            if self.kind in ("curve_left", "curve_right"):
                sign = 1 if self.kind == "curve_left" else -1
                heading = (
                    heading + sign * 70 * min(1, max(0, (elapsed - 18) / 52))
                ) % 360
            if self.kind == "climb_out":
                up = 280
                if 24 <= elapsed < 36 or 66 <= elapsed < 78:
                    buttons |= 2
            if self.kind == "open_door" and 54 <= elapsed < 102:
                forward = 0
            if self.kind == "ride":
                exit_ticks = 18
                if elapsed < self.duration - exit_ticks:
                    n = min(n, self.duration - exit_ticks - elapsed)
                    forward = 0
                else:
                    forward = 300
            rows.append((n, forward, 0, up, heading, self.pitch, buttons))
            elapsed += n
        return rows

    def label(self):
        if self.onward:
            return " then ".join(step.label() for step in (replace(self, onward=()), *self.onward))
        if self.kind == "jump" and self.launch_tick != 8:
            return (
                f"jump toward {self.heading:.0f}° after {self.launch_tick} run-up ticks"
            )
        if self.kind == "hold_for_lift":
            return "stay aboard the rising platform"
        if self.kind == "test_control":
            tilt = (
                f"{abs(self.pitch):.0f}° {'up' if self.pitch < 0 else 'down'}"
                if abs(self.pitch) >= 0.5
                else "level"
            )
            return f"test control at {self.heading:.0f}°, {tilt}"
        if self.kind.startswith("curve_"):
            return f"curve {self.kind.split('_')[1]} from {self.heading:.0f}°"
        return f"{self.kind.replace('_', ' ')} toward {self.heading:.0f}°"


def render_rows(camera, rows):
    # Quake's client view advances on renders. Match the live render boundaries
    # even when adjacent input rows hold identical controls.
    stream = MotionStream(rows)
    while stream.index < len(rows):
        frame = camera.frame(*stream.next(4))
    return frame


def fingerprint(frame):
    gray = camera_gray(frame)[12:161, 8:312]
    return cv2.resize(
        cv2.GaussianBlur(gray, (5, 5), 0), (24, 15), interpolation=cv2.INTER_AREA
    ).astype(np.float32)


def photo_error(a, b):
    diff = a - b
    return float(np.abs(diff - diff.mean()).mean() + 0.35 * abs(diff.mean()))


def panorama(camera):
    pictures = [camera.glance(yaw, 0) for yaw in (0, 90, 180, 270)]
    return np.stack([fingerprint(f) for f in pictures]), pictures


def panorama_after_wait(camera, option):
    camera.frame(18, 0, 0, 0, option.heading, option.pitch)
    return panorama(camera)[0]


def target_response(camera, option):
    """Compare the marked surface while the player's feet and aim stay fixed."""
    camera.rewind()
    camera.frame(6, 0, 0, 0, option.heading, option.pitch)
    with camera.endpoint():

        def sample(button):
            camera.rewind()
            camera.frame(8, 0, 0, 0, option.heading, option.pitch, button)
            resting = camera.frame(34, 0, 0, 0, option.heading, option.pitch)
            return camera_gray(resting).astype(np.float32)

        reference = sample(0)
        fired = sample(1)
        repeat = sample(0)
    # Compare the patch around the reticle with nearby surfaces after flash/recoil.
    # The weapon, HUD and outer screen are excluded.
    area = np.s_[70:139, 89:231]
    differences = fired[area] - reference[area]
    repeat_error = repeat[area] - reference[area]
    changes = np.abs(differences - np.median(differences)) - np.abs(
        repeat_error - np.median(repeat_error)
    )
    mask = changes > 10
    center = mask[36:63, 55:88]
    surroundings = np.ones_like(mask, dtype=bool)
    surroundings[32:67, 50:93] = False
    background = float(mask[surroundings].mean())
    fraction = float(center.mean())
    return {
        "target_change_fraction": round(fraction, 3),
        "background_change_fraction": round(background, 3),
        "localized": bool(
            fraction > max(0.045, 3.2 * background) and background < 0.12
        ),
    }


def room_distances(rooms, query):
    if not len(rooms):
        return np.array([])
    delta = rooms - query
    means = delta.mean(axis=(-2, -1))
    shape = np.abs(delta - means[:, :, None, None]).mean(axis=(-2, -1))
    return np.sort(shape + 0.35 * np.abs(means), axis=1)[:, :3].mean(axis=1)


class RoomBook:
    """Only commit a visit when the live camera agrees with the predicted handoff."""

    def __init__(self):
        self.rooms = {}
        self.visits = Counter()
        self.attempts = Counter()
        self.last = None
        self.path = deque(maxlen=12)
        self.cursor = np.zeros(2)
        self.last_delta = None
        self.cells = Counter()
        self.graph = PassageGraph()
        self.interactions = Counter()

    @staticmethod
    def cell(point):
        return tuple(int(i) for i in np.floor(point / 128))

    def choose(self, result, intent, preferred=None):
        if self.last is not None and self.last_delta is not None:
            self.cursor = self.cursor + self.last_delta
        self.last_delta = None
        dests, frontier_scores = self.graph.scores(result, self.cursor)
        node = self.graph.current
        if node not in self.rooms:
            self.rooms[node] = result["source_pano"]
        else:
            self.cursor = 0.25 * self.cursor + 0.75 * self.graph.positions[node]
        self.cells[self.cell(self.cursor)] += 1
        self.visits[node] += 1
        self.path.append(node)
        self.last = node
        confirmed = np.asarray(list(self.rooms.values()))
        weights = np.array([self.visits[i] for i in self.rooms])
        ranked = []
        guide = result.get("guide")
        interaction = None
        if guide and guide["kind"] in (
            "door",
            "touch_button",
            "shoot_button",
            "platform",
            "exit_opening",
        ):
            interaction = (
                guide.get("landmark_id", guide["source_tick"]),
                guide["kind"],
            )
        for branch, destination, frontier_score in zip(
            result["branches"], dests, frontier_scores
        ):
            branch["destination"] = destination
            option = branch["option"]
            key = (round(option.heading / 15) % 24, option.kind)
            distances = room_distances(confirmed, branch["pano"])
            nearest = float(distances.min())
            dest = destination if destination in self.rooms else None
            changed = room_distances(
                np.asarray([result["source_pano"]]), branch["pano"]
            )[0]
            # Several rotated camera views at the same location should not earn exploration credit.
            gain = min(1.5, changed / 10) + min(1.5, nearest / 9)
            stuck = changed < 3.5
            risk = max(0, branch["damage"]) / 7
            resource = max(0, -branch["damage"]) / 16 + min(
                1, max(0, branch["ammo_gain"]) / 5
            )
            score = (
                gain
                + resource
                - risk
                - 1.7 * stuck
                - 1.4 * math.log1p(self.attempts[node, key])
            )
            if (result.get("local_choice") or {}).get("input") == option.label():
                score += 0.95
            if branch.get("onward_preview") and branch["damage"] <= 0 and not stuck:
                score += min(2.3, max(0., branch["onward_preview"]["score"]) * .7)
            tried_bearings = (result.get("restore_departure") or {}).get("tried_bearings", ())
            if tried_bearings and any(abs(signed(option.heading-bearing)) < 35 for bearing in tried_bearings):
                score -= 5
            hint = branch.get("archive_advice")
            if hint and branch["damage"] <= 4 and not stuck:
                score += 4.5 if hint.get("exit_steps") is None else 18
            score += frontier_score
            if dest is not None:
                score -= 0.55 * math.log1p(self.visits[dest]) + 0.32 * list(
                    self.path
                ).count(dest)
            if branch.get("support", 0) >= 0.35:
                delta = branch["delta"]
                reach = min(1.5, np.linalg.norm(delta) / 210)
                cell = self.cell(self.cursor + delta)
                score += 1.6 * reach - 1.7 * math.log1p(self.cells[cell])
                if (
                    branch["end_speed"] is not None
                    and branch["end_speed"] < 0.65
                    and option.kind == "walk"
                ):
                    score -= 1.7
            density = float(np.exp(-((distances / 15) ** 2)) @ weights)
            score -= 1.35 * math.log1p(density)
            if preferred:
                bearing, requested_kind = preferred
                separation = abs(signed(option.heading - bearing))
                score += max(0, 1 - separation / 50) * (
                    3.5 if option.kind == requested_kind else 1.4
                )
            if (
                interaction
                and preferred
                and abs(signed(option.heading - preferred[0])) < 8
                and option.kind == preferred[1]
            ):
                tested = self.interactions[interaction, option.kind]
                score += 7.2 if tested == 0 else 0.7 if tested == 1 else -4
            if option.kind in ("test_control", "board"):
                score += 1.7 / (1 + self.attempts[node, key])
            if option.kind == "test_control" and (
                effect := branch.get("interaction_effect")
            ):
                score += min(2.5, effect["changed_view_fraction"] * 8)
                if effect.get("localized"):
                    score += 2.8
            if option.kind == "test_control":
                score += 0.55 if intent == "interact" else -0.18
            if option.kind == "jump":
                score += 0.5 if intent == "cross" else -0.12
            if (
                branch["notice"]
                and "opens elsewhere" in branch["notice"].lower()
                and option.kind in ("open_door", "board")
                and branch.get("support", 0) >= 0.35
                and np.linalg.norm(branch["delta"]) < 70
            ):
                score -= 6
            if branch["notice"] and "secret area" in branch["notice"].lower():
                score += 1.2
            if branch.get("possible_shore") and changed > 4:
                score += 4.2
            if (
                branch.get("ride_observed")
                and destination is not None
                and destination not in self.rooms
            ):
                score += 5
            if branch.get("after_step") == "descending":
                score -= 8
            if (
                option.kind == "hold_for_lift"
                and branch["hp"] != 0
                and branch["damage"] <= 8
            ):
                score += 14
            if branch["complete"]:
                score += 1000
            if branch["hp"] is not None and branch["hp"] <= 0:
                score -= 100
            # Familiar passages are necessary on the way back to a discovered exit from a room.
            backtracking = (
                self.graph.summary.get("steps") or 0
            ) > 1 or self.graph.return_target is not None
            start_health = (
                (branch["hp"] + branch["damage"]) if branch["hp"] is not None else None
            )
            safe = (branch["hp"] is None or branch["hp"] > 0) and branch["damage"] <= (
                4 if start_health is not None and start_health < 30 else 8
            )
            branch["restores_health"] = bool(
                start_health is not None
                and start_health <= 45
                and branch["damage"] <= -10
            )

            branch["ride_priority"] = bool(
                safe
                and branch.get("ride_observed")
                and branch.get("after_step") != "descending"
                and (
                    option.kind == "hold_for_lift"
                    or destination is not None
                    and destination not in self.rooms
                )
            )
            branch["jump_priority"] = bool(
                safe
                and (branch.get("jump_comparison") or {}).get("different_landing")
                and destination is not None
                and destination not in self.rooms
            )
            branch["route_priority"] = bool(
                backtracking and branch["route_step"] and safe
            )
            near_mark = bool(
                guide and abs(signed(option.heading - guide["bearing"])) < 8
            )
            branch["marked_input"] = bool(
                interaction
                and near_mark
                and preferred
                and (
                    option.kind == preferred[1]
                    or guide["kind"] in ("touch_button", "shoot_button")
                    and option.kind in ("board", "test_control")
                )
            )
            if branch["marked_input"]:
                tries = self.interactions[interaction, option.kind]
                if tries >= 1:
                    score -= min(9, 4.5 * tries)
                elif guide["kind"] == "exit_opening" and safe:
                    score += 8
            ranked.append((score, branch, changed, nearest))
        ranked.sort(
            key=lambda entry: (
                entry[1]["complete"],
                bool((entry[1].get("archive_advice") or {}).get("exit_steps") and entry[1]["hp"] not in (0, None)),
                entry[1]["restores_health"],
                entry[1]["ride_priority"],
                entry[1]["jump_priority"],
                entry[1]["route_priority"],
                entry[0],
            ),
            reverse=True,
        )
        chosen = ranked[0][1]["option"]
        key = (round(chosen.heading / 15) % 24, chosen.kind)
        self.attempts[node, key] += 1
        best = ranked[0][1]
        self.graph.proposed = best["destination"]
        self.graph.last_input = chosen.label()
        self.last_delta = best["delta"] if best.get("support", 0) >= 0.35 else None
        entries = [
            {
                "input": b["option"].label(),
                "score": round(float(score), 2),
                "view_change": round(float(change), 2),
                "novel_view": round(float(distance), 2),
                "estimated_travel": round(float(np.linalg.norm(b["delta"])))
                if b.get("support", 0) >= 0.35
                else None,
                "floor_matches": round(float(b.get("support", 0)), 2),
                "visible_hp": b["hp"],
                "restores_health": b["restores_health"],
                "visible_ammo": b["ammo"],
                "game_message": b["notice"],
                "completion_screen": b["complete"],
                "interaction": b.get("interaction_effect"),
                "possible_shore": bool(b.get("possible_shore")),
                "verified_return": bool(b.get("returned")),
                "toward_frontier": b["route_step"],
                "backtracking": b["route_priority"],
                "marked_input": b["marked_input"],
                "ride_observed": bool(b.get("ride_observed")),
                "after_step": b.get("after_step"),
                "jump_comparison": b.get("jump_comparison"),
                "onward_preview": b.get("onward_preview"),
                "archive_advice": b.get("archive_advice"),
            }
            for score, b, change, distance in ranked
        ]
        return chosen, entries


def compare_jump_lanes(camera, headings, serial):
    """Screen candidate takeoffs with matched forward inputs at the visible tutorial cue."""
    comparisons = []
    for index, heading in enumerate(headings):
        launch = (6, 18, 36)[(serial + index) % 3]
        views = []
        for jump in (False, True):
            camera.rewind()
            camera.frame(4, 0, 0, 0, heading, 0)
            camera.frame(launch, 320, 0, 0, heading, 0)
            camera.frame(4, 320, 0, 0, heading, 0, 2 if jump else 0)
            camera.frame(100 - launch - 4, 320, 0, 0, heading, 0)
            for _ in range(2):
                camera.frame(4, 0, 0, 0, heading, 0)
            views.append(panorama(camera)[0])
        distance = float(room_distances(np.asarray([views[0]]), views[1])[0])
        comparisons.append((distance, heading, launch))
    return sorted(comparisons, key=lambda row: row[0], reverse=True)


def untested_lanes(previous, options, serial):
    """Bisect untried angular gaps; include a short stride that can stop at a junction."""
    rays = dict(previous)
    for option in options:
        if option.kind == "walk":
            rays.setdefault(round(option.heading / 5) % 72, (0, False))
    if len(rays) < 2:
        return []
    extra = []
    for index in range(2):
        bearings = sorted(rays)
        arcs = []
        for left, right in zip(bearings, bearings[1:] + [bearings[0] + 72]):
            span = right - left
            if span < 3:
                continue
            edge = rays[left][1] != rays[right % 72][1]
            arcs.append(
                (
                    span * (1.35 if edge else 1),
                    (left - serial * 17) % 72,
                    (left + round(span / 2)) % 72,
                )
            )
        if not arcs:
            break
        _, _, sector = max(arcs)
        rays[sector] = (0, False)
        extra.append(Option(sector * 5, "explore_lane", 38 if index == 0 else 76))
    return extra


class PreviewSearch:
    def __init__(self, hud, directory=None, planner=None, player=None, scene=None, future_passages=False, archive_search=False):
        from future_passages import FuturePassages
        self.future_passages = FuturePassages(hud) if future_passages else None
        from visual_frontier import VisualFrontier
        self.archive = VisualFrontier(hud, Option) if archive_search else None
        self.hud = hud
        self.player = player
        self.scene = scene
        self.floor = FloorMotion()
        self.place_camera = PlaceCamera()
        self.directory = directory
        self.advisor = PanoramaPlan(planner, directory) if planner else None
        self.camera = None
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="quake-own-save-search")
        self.job = None
        self.generation = 0
        self.book = RoomBook()
        self.batch = 0
        self.saved_places = {}
        self.door_node = None
        self.receipt = None
        self.last_offer = None

    def invalidate(self, relocated=False):
        if relocated:
            self.receipt = self.last_offer = None
            if self.advisor:
                self.advisor.invalidate()
        self.generation += 1
        self.book.last = None
        self.book.graph.forget_transition()
        if self.job:
            self.job[0].cancel()
            # A running forecast observes its generation at each branch. The one
            # serialized worker may queue a replacement immediately at the new viewpoint.
            self.job = None

    def record_input(self, event):
        receipt = event.get("lookahead") or {}
        alternatives = receipt.get("alternatives") or []
        guide = receipt.get("panorama_plan")
        if (
            event.get("input_source") == "Own-save lookahead"
            and guide
            and alternatives
            and alternatives[0].get("marked_input")
            and not event.get("lookahead_interrupted")
            and event.get("ticks", 0) > 0
        ):
            identity = guide.get("landmark_id", guide["source_tick"]), guide["kind"]
            self.book.interactions[identity, event["action"]] += 1

    def checkpoint(self, op, game=None, frame=None):
        slot = op["slot"]
        if self.archive and game and op["op"] == "save":
            self.archive.submit_save(slot, game.preview_source(), frame)
        elif self.archive and game and op["op"] == "load":
            self.archive.restored(slot, game.tick)
        if op["op"] == "save":
            self.saved_places[slot] = (
                self.book.cursor.copy(),
                self.book.interactions.copy(),
            )
        else:
            self.invalidate(relocated=True)
            if slot in self.saved_places:
                cursor, attempts = self.saved_places[slot]
                self.book.cursor = cursor.copy()
                self.book.interactions = attempts.copy()

    def choices(self, yaw, serial, views):
        base = round(yaw / 30) * 30
        # Cover the whole circle. Rotate the off-axis probes between batches.
        offsets = (
            (0, 45, -45, 90, -90, 180) if serial % 2 else (0, 30, -30, 120, -120, 180)
        )
        options = [Option((base + v) % 360) for v in offsets]
        options.append(Option(base % 360, "jump", 100))
        options.append(
            Option((base + (60 if serial % 2 else -60)) % 360, "surface", 92)
        )
        if self.scene:
            # Probe the most open bearing in each actual camera tile. Keep absolute compass probes for recovery.
            options = [
                Option(
                    (90 * i + self.scene.read(view, openings=True)["opening_yaw"]) % 360
                )
                for i, view in enumerate(views)
            ] + options[4:]
        bend = "curve_left" if serial % 2 else "curve_right"
        forward = min(options, key=lambda opt: abs(signed(opt.heading - yaw)))
        options.append(Option(forward.heading, bend, 102))
        marked = []
        for i, frame in enumerate(views):
            color = cv2.cvtColor(
                cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)[:192],
                cv2.COLOR_BGR2RGB,
            )
            for target in PanelScout.candidates(color)[:1]:
                direction, tilt = aim_angles(target["point"], 90 * i)
                marked.append((target["shape_match"], direction, tilt))
        if marked:
            _, direction, tilt = max(marked)
            options.extend(
                [
                    Option(direction, "board", 96),
                    Option(direction, "test_control", 96, tilt),
                ]
            )
        return options

    def _forecast(self, source, rows, serial, context):
        try:
            return self._compare(source, rows, serial, context)
        except Exception:
            # An interrupted branch or failed native load must not poison the next live save.
            if self.camera is not None:
                camera, self.camera = self.camera, None
                camera.__exit__(None, None, None)
            raise

    def _compare(self, source, rows, serial, context):
        begun = time.monotonic()
        expected_generation = context.pop("prediction_generation", self.generation)
        def superseded():
            return expected_generation != self.generation
        if superseded():
            return None
        if self.camera is None:
            self.camera = source.open_camera()
        else:
            try:
                self.camera.rebase(source)
            except (RuntimeError, OSError, ValueError):
                self.camera.__exit__(None, None, None)
                self.camera = None
                self.camera = source.open_camera()
        camera = self.camera
        anchor = render_rows(camera, rows)
        camera.pin()
        source_pano, views = panorama(camera)
        known = list(context.pop("place_landmarks", ()))
        first_new = len(known)
        origin = context.pop("return_node", None)
        expected = context.pop("expected_node", None)
        investigation = context.pop("angular_trials", {})
        jump_trials = context.pop("jump_trials", {})
        place_id = self.place_camera.locate(
            self.place_camera.landmark(source_pano, views), known, expected
        )
        health, ammo = self.hud.read_status(anchor)
        vertical = vertical_control(camera, rows[-1][4])
        released = released_camera(camera, rows[-1][4], follow=not vertical["responds"])
        lift_exits = []
        if released["direction"] == "rising" and not vertical["responds"]:
            if released["still_rising"]:
                lift_exits.append(Option(rows[-1][4], "hold_for_lift", 96, rows[-1][5]))
            else:
                _, elevated = panorama(camera)
                for sector, view in enumerate(elevated):
                    offset = (
                        self.scene.read(view, openings=True)["opening_yaw"]
                        if self.scene
                        else 0
                    )
                    lift_exits.append(
                        Option(
                            (90 * sector + offset) % 360,
                            "ride_to_landing",
                            released["elapsed_ticks"] + 40,
                        )
                    )
        current_notice = (
            self.hud.notice_font.read(anchor) if self.hud.notice_font else ""
        )
        cue = (current_notice or context.get("recent_game_message", "")).lower()
        jump_hint = "jump" in cue and ("up" in cue or "across" in cue)
        if current_notice:
            context["visible_game_message"] = current_notice
        lesson = context.get("movement_lesson") or {}
        if lesson.get("lesson") == "compare_walk_and_jump":
            jump_hint = True
        choices = self.choices(rows[-1][4], serial, views)
        if place_id in investigation:
            choices.extend(untested_lanes(investigation[place_id], choices, serial))
        if vertical["responds"]:
            headings = [option.heading for option in choices if option.kind == "walk"]
            candidates = sorted(
                headings, key=lambda angle: abs(signed(angle - rows[-1][4]))
            )
            across = candidates[0]
            other = candidates[-2] if serial % 2 else candidates[len(candidates) // 2]
            choices = [
                Option(across),
                Option(other),
                Option(across, "surface", 114, -20),
                Option(other, "climb_out", 114, -22),
                Option(across, "climb_out", 108, -22),
                Option(other, "dive", 94, 24),
            ] + [o for o in choices if o.kind in ("board", "test_control")]
            context["camera_response_to_controls"] = (
                "Up or down input changed the view compared with an idle trial. Test swimming to a viable shore or an underwater passage."
            )
        if origin is not None and place_id != origin:
            # Test a return move. Only a physically tested, visually verified return becomes an edge.
            outward = np.zeros(2)
            for n, forward, side, _, yaw, _, _ in rows:
                angle = math.radians(yaw)
                outward += (
                    n
                    / 72
                    * np.array(
                        [
                            forward * math.cos(angle) + side * math.sin(angle),
                            forward * math.sin(angle) - side * math.cos(angle),
                        ]
                    )
                )
            measured = context.pop("last_displacement", None)
            if measured is not None and np.linalg.norm(measured) >= 45:
                outward = measured
            distance = float(np.linalg.norm(outward))
            if distance >= 45:
                heading = math.degrees(math.atan2(-outward[1], -outward[0])) % 360
                choices.append(
                    Option(
                        heading,
                        "retrace",
                        max(18, min(110, round(distance * 72 / 320 + 4))),
                    )
                )
        context.pop("last_displacement", None)
        if lift_exits:
            choices = (
                lift_exits
                + [o for o in choices if o.kind in ("walk", "test_control")][:4]
            )
        controls = context.pop("frontier_inputs", ())
        for known_move in controls:
            if known_move not in choices:
                choices.append(known_move)
        guide = (
            self.advisor.update(views, source.tick + sum(r[0] for r in rows), context)
            if self.advisor
            else None
        )
        if guide:
            kind = {
                "landing": "jump",
                "shoot_button": "test_control",
                "touch_button": "board",
                "platform": "ride",
                "door": "open_door",
            }.get(guide["kind"], "walk")
            if guide["kind"] == "platform":
                choices.append(Option(guide["bearing"], "board", 96))
            if guide["kind"] in ("shoot_button", "touch_button"):
                alternative = "board" if kind == "test_control" else "test_control"
                choices.append(
                    Option(
                        guide["bearing"],
                        alternative,
                        96,
                        guide["aim_pitch"] if alternative == "test_control" else 0,
                    )
                )
            choices.append(
                Option(
                    guide["bearing"],
                    kind,
                    150 if kind in ("ride", "open_door") else 96,
                    guide["aim_pitch"] if kind == "test_control" else 0,
                )
            )
        paired_headings = set()
        if jump_hint and not lift_exits and not vertical["responds"]:
            # Try different takeoff distances at a visible traversal cue. Walking the same
            # line supplies a control for jumps that simply land in the same place.
            hint_heading = (
                guide["bearing"]
                if guide and guide["kind"] == "landing"
                else rows[-1][4]
            )
            trials = jump_trials.get(place_id, {})
            directions = [(hint_heading + n * 30) % 360 for n in range(12)]
            directions.sort(
                key=lambda y: (
                    trials.get(round(y / 15) % 24, 0),
                    abs(signed(y - hint_heading)),
                )
            )
            survey_headings = list(
                dict.fromkeys(
                    [directions[0], directions[1]]
                    + [
                        (hint_heading + 30 * (serial % 3) + a) % 360
                        for a in (0, 60, 120, 180, 240, 300)
                    ]
                )
            )
            shortlist = compare_jump_lanes(camera, survey_headings, serial)
            choices = [o for o in choices if o.kind != "jump"]
            for _, y, launch in shortlist[:2]:
                paired_headings.add(y)
                choices.append(Option(y, "walk", 100))
                choices.append(Option(y, "jump", 100, launch_tick=launch))
                choices.append(
                    Option(y, "jump", 100, launch_tick=36 if launch < 20 else 12)
                )
        onward_option = None
        onward_evidence = None
        # Compare one transferable side departure with the ordinary choices. The live
        # game advances throughout the forecast and can interrupt the plan for danger.
        if (self.future_passages and not lift_exits and not vertical["responds"]
                and source.tick - self.future_passages.last_search >= 5 * 72):
            self.future_passages.last_search = source.tick
            junction = camera.snapshot(rows[-1][4], rows[-1][5])
            prediction = self.future_passages.search(junction, Option, superseded) if junction else None
            if prediction:
                moves = prediction["moves"][:2]
                onward_option = replace(moves[0], onward=tuple(moves[1:]))
                choices.append(onward_option)
                onward_evidence = {"options_tested": prediction["trials"],
                                   "path": [m.label() for m in moves], "score": round(prediction["score"], 2)}
        archive_hint = self.archive.suggest(views, current_notice) if self.archive else None
        archive_move = archive_hint["option"] if archive_hint else None
        if archive_move is not None:
            choices.append(archive_move)
        unique = {}
        for option in choices:
            signature = (
                round(option.heading / 2),
                option.kind,
                option.duration,
                round(option.pitch / 2),
                option.launch_tick,
                option.onward,
            )
            unique[signature] = option
        branches = []
        walking_views = {}
        # Evaluate the walking control before its matched jumps.
        for option in sorted(unique.values(), key=lambda o: o.kind == "jump"):
            if superseded():
                return None
            camera.rewind()
            frame, delta, support, speed = self.floor.traverse(
                camera, option, rows[-1][4], rows[-1][5]
            )
            hp, rounds = self.hud.read_status(frame)
            complete = self.hud.completed(frame)
            # Score only visible changes from this point onward.
            scan, end_views = panorama(camera) if not complete else (source_pano, None)
            matched_jump = None
            if not option.onward and option.heading in paired_headings and option.duration == 100:
                if option.kind == "walk":
                    walking_views[option.heading] = scan
                elif option.kind == "jump" and option.heading in walking_views:
                    difference = float(
                        room_distances(
                            np.asarray([walking_views[option.heading]]), scan
                        )[0]
                    )
                    matched_jump = {
                        "hint": cue,
                        "walk_camera_difference": round(difference, 2),
                        "different_landing": difference >= 21,
                        "runup_ticks": option.launch_tick,
                    }
            jump_discovery = bool(matched_jump and matched_jump["different_landing"])
            destination = None
            returned = False
            on_lift = bool(lift_exits) and option.kind in (
                "hold_for_lift",
                "ride_to_landing",
            )
            if end_views and (
                on_lift
                or jump_discovery
                or (support >= 0.35 and np.linalg.norm(delta) >= 45)
                or option.kind == "retrace"
            ):
                endpoint = self.place_camera.landmark(scan, end_views)
                if (
                    option.kind == "retrace"
                    and origin is not None
                    and self.place_camera.agrees(endpoint, known[origin])
                ):
                    destination, returned = origin, True
                elif (
                    on_lift
                    or jump_discovery
                    or (support >= 0.35 and np.linalg.norm(delta) >= 45)
                ):
                    destination = self.place_camera.locate(endpoint, known)

            emerged = False
            if (
                vertical["responds"]
                and option.kind in ("surface", "climb_out")
                and hp
                and not complete
            ):
                with camera.endpoint():
                    arrived = vertical_control(camera, option.heading)
                emerged = not arrived["responds"]
            step_off = None
            if on_lift and option.kind == "ride_to_landing" and hp and not complete:
                with camera.endpoint():
                    step_off = released_camera(camera, option.heading)["direction"]
            interaction_effect = None
            if option.kind == "test_control" and not complete and hp:
                # Compare equal movement and aim, toggling only the button press.
                # Wait out the muzzle flash. The comparison covers visible surfaces only.
                after = panorama_after_wait(camera, option)
                camera.rewind()
                neutral = [
                    (n, f, s, u, y, p, b & ~1)
                    for n, f, s, u, y, p, b in option.rows(rows[-1][4], rows[-1][5])
                ]
                render_rows(camera, neutral)
                without = panorama_after_wait(camera, option)
                changed = (
                    np.abs(
                        (after - after.mean(axis=(1, 2), keepdims=True))
                        - (without - without.mean(axis=(1, 2), keepdims=True))
                    )
                    > 14
                )
                changed_fraction = float(changed.mean(axis=(1, 2)).max())
                interaction_effect = {
                    "changed_view_fraction": round(changed_fraction, 3),
                    "notice": "Visible scene changed after firing"
                    if changed_fraction >= 0.09
                    else "Similar views with and without firing",
                }
                if (
                    guide
                    and guide["kind"] in ("shoot_button", "touch_button")
                    and abs(signed(option.heading - guide["bearing"])) < 8
                ):
                    patch = target_response(camera, option)
                    interaction_effect.update(patch)
                    if patch["localized"]:
                        interaction_effect["notice"] = (
                            "The marked surface changed after a stationary shot."
                        )
                    elif changed_fraction < 0.09:
                        interaction_effect["notice"] = (
                            "The marked surface and its surroundings looked similar with the trigger released."
                        )
            branches.append(
                {
                    "ride_observed": on_lift,
                    "jump_comparison": matched_jump,
                    "onward_preview": onward_evidence if option == onward_option else None,
                    "archive_advice": ({k:v for k,v in archive_hint.items() if k != "option"}
                                       if archive_hint and archive_move == option else None),
                    "after_step": step_off,
                    "place_id": destination,
                    "returned": returned,
                    "interaction_effect": interaction_effect,
                    "option": option,
                    "pano": scan,
                    "frame": frame,
                    "delta": delta,
                    "support": support,
                    "end_speed": speed,
                    "possible_shore": emerged,
                    "hp": hp,
                    "ammo": rounds,
                    "damage": health - hp
                    if health is not None and hp is not None
                    else 0,
                    "ammo_gain": rounds - ammo
                    if ammo is not None and rounds is not None
                    else 0,
                    "notice": self.hud.notice_font.read(frame)
                    if self.hud.notice_font
                    else "",
                    "complete": complete,
                }
            )
        choice_context = {
            "objective": (guide or {}).get("objective") or context.get("objective"),
            "previous_input": context.get("previous_choice"),
        }
        if context.get("movement_lesson"):
            choice_context["movement_lesson"] = context["movement_lesson"]
        local_choice = (
            self.player.choose_preview(branches, choice_context)
            if self.player
            else None
        )
        return {
            "place_id": place_id,
            "new_landmarks": known[first_new:],
            "vertical": vertical,
            "released_camera": released,
            "local_choice": local_choice,
            "guide": guide,
            "anchor": fingerprint(anchor),
            "source_pano": source_pano,
            "scout_views": views if self.future_passages else None,
            "archive": self.archive.status() if self.archive else None,
            "branches": branches,
            "latency_ms": round(1000 * (time.monotonic() - begun)),
        }

    def submit(self, game, rows, plan=None, mechanism=None, hud=None, lesson=None):
        if self.job:
            return
        try:
            source = game.preview_source()
        except RuntimeError as exc:
            self.last_offer = {"status": "Unavailable", "reason": str(exc)[:130]}
            return
        self.batch += 1
        receipt = dict(
            source.receipt,
            batch=self.batch,
            handoff_tick=game.tick + sum(r[0] for r in rows),
            handoff_yaw=rows[-1][4],
            handoff_pitch=rows[-1][5],
        )
        self.last_offer = dict(receipt, status="Comparing")
        context = {
            "objective": (plan or {}).get(
                "objective", "Find the exit through an untried passage."
            )
        }
        context["prediction_generation"] = self.generation
        if lesson:
            context["movement_lesson"] = lesson
        if self.receipt:
            context = {
                **context,
                "previous_choice": self.receipt["selected"],
                "tested_moves": self.receipt["alternatives"][:3],
            }
        if (
            hud
            and hud.get("game_message")
            and hud.get("message_ticks_ago", 99999) < 144
        ):
            context["recent_game_message"] = hud["game_message"]
        if mechanism:
            context["unresolved_door"] = mechanism
        self.book.graph.return_target = (
            self.door_node
            if mechanism and mechanism.get("status") == "verify_door"
            else None
        )
        context["confirmed_recent_passages"] = list(self.book.graph.recent)
        context["exploration_graph"] = self.book.graph.summary
        context["frontier_inputs"] = self.book.graph.next_probes()
        # Immutable descriptors are shared with one worker; speculative nodes are committed in take().
        context["place_landmarks"] = tuple(self.book.graph.landmarks)
        context["expected_node"] = self.book.graph.proposed
        context["angular_trials"] = self.book.graph.tested_headings.copy()
        context["jump_trials"] = self.book.graph.tested_jumps.copy()
        if self.receipt and self.receipt.get("selected_tick") == game.tick:
            context["return_node"] = self.book.graph.current
            context["last_displacement"] = self.book.last_delta
        self.job = (
            self.pool.submit(self._forecast, source, rows, self.batch, context),
            receipt,
            self.generation,
        )

    def handoff_pending(self, tick):
        if not self.job:
            return False
        _, receipt, generation = self.job
        return generation == self.generation and 0 <= tick - receipt["handoff_tick"] <= 120

    def take(self, frame, game, intent="explore", marker=None, departure=None):
        if not self.job:
            return None
        job, receipt, generation = self.job
        if generation != self.generation and job.done():
            self.job = None
            return None
        if not job.done() or game.tick < receipt["handoff_tick"]:
            return None
        self.job = None
        if generation != self.generation:
            return None
        if job.exception() is not None:
            self.last_offer = dict(
                receipt,
                status="Failed",
                reason=str(job.exception())[:140] or type(job.exception()).__name__,
            )
            return None
        result = job.result()
        error = photo_error(result["anchor"], fingerprint(frame))
        aged = game.tick - receipt["handoff_tick"]
        if (
            (aged > 120 or (aged > 60 and error > 4.5))
            or abs(signed(game.yaw - receipt["handoff_yaw"])) > 18
            or abs(game.pitch - receipt["handoff_pitch"]) > 14
            or error > 12
        ):
            self.last_offer = dict(
                receipt,
                status="Expired",
                image_error=round(error, 2),
                latency_ms=result["latency_ms"],
            )
            self.book.last = self.book.last_delta = None
            self.book.graph.forget_transition()
            return None
        if self.future_passages and result.get("scout_views"):
            self.future_passages.remember(result["scout_views"])
        preferred = None
        if marker and marker.get("kind") != "fallen_character":
            bearing = (
                game.yaw - math.degrees(math.atan((marker["point"][0] - 50) / 50))
            ) % 360
            kind = {
                "landing": "jump",
                "touch_button": "board",
                "shoot_button": "test_control",
                "platform": "ride",
                "door": "open_door",
            }.get(marker["kind"], "walk")
            preferred = bearing, kind
        if result.get("guide"):
            guide = result["guide"]
            kind = {
                "landing": "jump",
                "shoot_button": "test_control",
                "touch_button": "board",
                "platform": "ride",
                "door": "open_door",
            }.get(guide["kind"], "walk")
            preferred = guide["bearing"], kind
        if departure:
            result["restore_departure"] = departure
        option, entries = self.book.choose(result, intent, preferred)
        self.receipt = dict(
            receipt,
            status="Selected",
            archive=result.get("archive"),
            selected_tick=game.tick,
            selected=option.label(),
            aim_pitch=option.pitch if option.kind == "test_control" else None,
            panorama_plan=result.get("guide"),
            vertical_response=result.get("vertical"),
            released_camera=result.get("released_camera"),
            local_choice=result.get("local_choice"),
            matched_frame_error=round(error, 2),
            latency_ms=result["latency_ms"],
            alternatives=entries,
            visited_views=len(self.book.rooms),
            source_node=self.book.last,
            frontier=self.book.graph.summary,
        )
        if self.directory:
            import io

            from PIL import Image, ImageDraw

            paths = self.directory / "previews"
            paths.mkdir(exist_ok=True)
            by_label = {b["option"].label(): b["frame"] for b in result["branches"]}
            sheet = Image.new("RGB", (3 * 176, 143), "#161b19")
            draw = ImageDraw.Draw(sheet)
            for index, entry in enumerate(entries[:3]):
                with Image.open(io.BytesIO(by_label[entry["input"]])) as image:
                    sheet.paste(image.resize((176, 116)), (index * 176, 0))
                draw.text((index * 176 + 4, 121), entry["input"], fill="#eeeeee")
            sheet.save(paths / f"{game.tick}.jpg", quality=82)
            self.receipt["sheet_tick"] = game.tick
        self.last_offer = self.receipt
        return option

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        if self.archive:
            self.archive.close()
        if self.future_passages:
            self.future_passages.close()
        if self.advisor:
            self.advisor.close()
        if self.camera:
            self.camera.__exit__(None, None, None)


class MotionStream:
    def __init__(self, rows):
        self.rows = rows
        self.index = self.offset = 0

    def next(self, limit):
        n, forward, side, up, yaw, pitch, buttons = self.rows[self.index]
        count = min(limit, n - self.offset)
        self.offset += count
        if self.offset == n:
            self.index += 1
            self.offset = 0
        return count, forward, side, up, yaw, pitch, buttons
