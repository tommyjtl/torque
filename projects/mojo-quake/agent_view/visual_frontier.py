"""Per-attempt visual graph explored with normal game inputs in private copies of the player's own saves."""

import heapq
import math
import re
import zlib
from collections import Counter, deque
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import monotonic

import cv2
from PIL import Image
import numpy as np

from landmarks import PanelScout


def grayscale(frame):
    if isinstance(frame, Image.Image):
        return np.asarray(frame.convert("L"))
    return cv2.imdecode(np.frombuffer(frame,np.uint8),cv2.IMREAD_GRAYSCALE)


def panorama_code(frames):
    tiles = []
    for frame in frames:
        gray = grayscale(frame)
        tile = cv2.resize(
            gray[34:163, 8:312], (12, 8), interpolation=cv2.INTER_AREA
        ).astype(np.float32)
        tiles.append(
            np.clip((tile - tile.mean()) / max(12.0, tile.std()), -2.5, 2.5).ravel()
        )
    return np.array(tiles)


def live_appearance(frame):
    image = grayscale(frame)
    return cv2.resize(
        image[32:153, 8:312], (32, 16), interpolation=cv2.INTER_AREA
    ).astype(np.float32)


def eye_error(a, b):
    diff = a - b
    return float(np.abs(diff - diff.mean()).mean() + 0.25 * abs(diff.mean()))


def scene_error(a, b):
    return float(np.sort(np.abs(a - b).mean(axis=1))[:3].mean())


class PictureIndex:
    def __init__(self, rng):
        self.vectors = []
        self.buckets = [{} for _ in range(12)]
        self.axes = rng.normal(size=(12, 10, 96)).astype(np.float32)

    def codes(self, picture):
        bits = np.einsum("ijk,ik->ij", self.axes, np.tile(picture, (3, 1))) > 0
        return (bits @ (1 << np.arange(10))).tolist()

    def find(self, picture, stage):
        codes = self.codes(picture)
        pool = set()
        for table, key in zip(self.buckets, codes):
            pool.update(table.get((stage, key), ())[-64:])
        if not pool:
            return None, 1.0, codes
        ids = list(pool)
        values = np.asarray([self.vectors[i] for i in ids])
        sizes = np.sort(np.abs(values - picture).mean(axis=2), axis=1)[:, :3].mean(
            axis=1
        )
        best = int(sizes.argmin())
        return ids[best], float(sizes[best]), codes

    def add(self, picture, codes, stage):
        ident = len(self.vectors)
        self.vectors.append(picture)
        for table, key in zip(self.buckets, codes):
            table.setdefault((stage, key), []).append(ident)
        return ident


@dataclass
class Cell:
    save: object
    slot: int
    parent: object
    incoming: object
    bearing: float
    depth: int
    novelty: float
    options: list
    stage: int
    tried: int = 0
    discoveries: int = 0
    encounters: int = 1
    live_visits: int = 0
    edges: dict = field(default_factory=dict)
    eye: object = None
    pitch: float = 0
    hp: object = None


def execute(camera, move, yaw, pitch=0):
    """Batch adjacent identical controls without changing the input at any simulation tick."""
    combined = []
    for row in move.rows(yaw, pitch):
        if combined and row[1:] == combined[-1][1:] and row[0] + combined[-1][0] <= 160:
            combined[-1] = (combined[-1][0] + row[0], *row[1:])
        else:
            combined.append(row)
    frame = None
    for n, f, s, u, y, p, b in combined:
        frame = camera.frame(n, f, s, u, y, p, b)
    return frame


class VisualFrontier:
    def __init__(self, hud, option_type, limit=48000, seed=472):
        self.hud = hud
        self.option = option_type
        self.limit = limit
        self.rng = np.random.default_rng(seed)
        self.index = PictureIndex(self.rng)
        self.cells = []
        self.queues = {}
        self.root_steps = Counter()
        self.root_discoveries = Counter()
        self.live_stage = 0
        self.retire_cursor = 0
        self.roots = {}
        self.latest = deque()
        self.lock = Lock()
        self.stop = Event()
        self.signal = Event()
        self.worker = None
        self.camera = None
        self.steps = 0
        self.packed_bytes = 0
        self.notices = Counter()
        self.win = None
        self.error = None
        self.last_live = None
        self.last_hint = None
        self.verifier_camera = None
        self.path_nodes = ()
        self.canonical_views = {}
        self.rehearsed_eyes = {}
        self.rejected_witnesses = 0
        self.exit_route = {}
        self.next_health = {}
        self.root_retries = 0
        self.last_goal_step = None
        self.misses = 0
        self.rejoined_at = None

    def submit_save(self, slot, source, frame=None):
        if self.stop.is_set():
            return
        with self.lock:
            self.latest.append((slot, source, frame))
            if self.worker is None:
                self.worker = Thread(
                    target=self._run, name="quake-visual-frontier", daemon=True
                )
                self.worker.start()
        self.signal.set()

    def _panels(self, views):
        out = []
        for i, frame in enumerate(views):
            if isinstance(frame, Image.Image):
                rgb = np.asarray(frame)
            else:
                rgb = cv2.cvtColor(cv2.imdecode(np.frombuffer(frame,np.uint8),cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            marks = PanelScout.candidates(rgb[:192])
            if not marks:
                continue
            x, y = marks[0]["point"]
            bearing = (90 * i - math.degrees(math.atan((x - 50) / 50))) % 360
            tilt = math.degrees(math.atan((y - 50) * 2.4 / 160))
            out.extend(
                (
                    self.option(bearing, "test_control", 96, tilt),
                    self.option(bearing, "board", 96),
                )
            )
        return out

    def _moves(self, h, views, notice):
        bearing = round(h / 15) * 15
        options = []
        weights = []
        # Relative turns and short takeoffs are transferable gestures from the human training maps.
        for d, kinds in (
            (76, ("walk", "jump")),
            (38, ("walk", "jump")),
            (103, ("open_door", "climb_out", "dive")),
        ):
            for a in (0, 80, -80, 155, -155, 38, -38, 180):
                for k in kinds:
                    y = (
                        bearing + a + (0 if d == 76 else self.rng.uniform(-14, 14))
                    ) % 360
                    options.append(
                        self.option(
                            y,
                            k,
                            d,
                            -16 if k == "climb_out" else 20 if k == "dive" else 0,
                            int(self.rng.choice((6, 12, 22))) if k == "jump" else 8,
                        )
                    )
                    weights.append(
                        (1 if k == "walk" else 0.85 if k == "jump" else 0.24)
                        * (1.5 if d == 76 else 1)
                    )
        order = np.argsort(
            -np.log(np.maximum(self.rng.random(len(options)), 1.0e-8)) / weights
        )
        moves = [options[i] for i in order]
        for i, option in enumerate(self._panels(views)):
            moves.insert(min(2 * i + 1, len(moves)), option)
        moves.insert(8, self.option(h, "hold_for_lift", 100))
        if "jump" in notice.lower():
            moves.sort(key=lambda v: v.kind != "jump")
        return moves

    def _schedule(self, i):
        c = self.cells[i]
        if c.tried >= len(c.options) or c.save is None:
            return
        score = (
            1.6 * c.novelty
            + 0.095 * min(c.depth, 28)
            + 0.32 * min(4, c.discoveries)
            + 0.33 * min(3, c.live_visits)
            - 1.8 * math.log1p(c.tried)
            - 0.28 * math.log1p(c.encounters)
            + self.rng.gumbel() * 0.82
        )
        heapq.heappush(self.queues.setdefault(c.slot, []), (-score, i))

    def _free_search_space(self):
        """Retain the visual graph and root/keyframe saves when retiring older work."""
        if self.packed_bytes < 560_000_000:
            return
        scanned = 0
        while self.packed_bytes > 500_000_000 and scanned < len(self.cells):
            i = self.retire_cursor % len(self.cells)
            self.retire_cursor += 1
            scanned += 1
            cell = self.cells[i]
            if cell.save and cell.parent is not None and cell.depth % 8 and cell.tried >= 2:
                self.packed_bytes -= cell.save.packed_size
                cell.save = None

    def _take_source(self):
        slots = [slot for slot,q in self.queues.items() if q]
        if not slots:
            return None
        young = [slot for slot in slots if self.root_steps[slot] < 128]
        if young:
            slot = min(young, key=lambda s:self.root_steps[s])
        elif self.steps % 5 < 2:
            slot = int(self.rng.choice(sorted(slots)[-4:]))
        elif self.steps % 5 == 2:
            slot = max(slots, key=lambda s:(4+self.root_discoveries[s])/(16+self.root_steps[s]))
        else:
            slot = int(self.rng.choice(slots))
        _, ident = heapq.heappop(self.queues[slot])
        return ident

    @staticmethod
    def milestone(text):
        text = " ".join((text or "").lower().split())
        if (not text or "need" in text or "opens elsewhere" in text or
            not re.search(r"(sequence complete|more to go|has been (lit|opened|unlocked)|you got .{0,20}key)",text)):
            return 0
        return 1 << (2 + zlib.crc32(text.encode()) % 16)

    def _insert(
        self,
        source,
        slot,
        parent,
        move,
        depth,
        h,
        novelty,
        desc,
        views,
        codes,
        stage,
        notice,
        frame,
    ):
        ident = self.index.add(desc, codes, stage)
        compact = source.pack()
        self.packed_bytes += compact.packed_size
        self.cells.append(
            Cell(
                compact,
                slot,
                parent,
                move,
                h,
                depth,
                min(1.0, novelty),
                self._moves(h, views, notice),
                stage,
            )
        )
        self.cells[-1].eye = live_appearance(frame)
        self.cells[-1].pitch = source.pitch
        self.cells[-1].hp = self.hud.read(frame)
        self._schedule(ident)
        return ident

    def _root(self, slot, source, frame=None):
        if self.camera is None:
            self.camera = source.open_camera(raw_images=True)
        else:
            self.camera.rebase(source)
        views = [self.camera.glance(i, 0) for i in (0, 90, 180, 270)]
        desc = panorama_code(views)
        with self.lock:
            if slot in self.roots:
                return
            stage = self.hud.key_mask(views[0]) | self.live_stage
            # A real own save remains an exact root even if it looks similar to a hypothetical state.
            node = self._insert(
                source,
                slot,
                None,
                None,
                0,
                source.yaw,
                1.0,
                desc,
                views,
                self.index.codes(desc),
                stage,
                "",
                frame
                if frame is not None
                else self.camera.glance(source.yaw, source.pitch),
            )
            self.roots[slot] = node
            self.cells[node].live_visits = 1

    def _complete(self, i, move):
        cell = self.cells[i]
        ordered = [(i, move)]
        seen = {i}
        while cell.parent is not None:
            node = cell.parent
            if node in seen:
                raise RuntimeError("Invalid private search tree")
            seen.add(node)
            ordered.append((node, cell.incoming))
            cell = self.cells[node]
        ordered.reverse()
        # Independently verify the whole hypothetical path as a continuous game before
        # proposing a checkpoint restore. The real game proceeds on a different thread.
        root = cell.save.unpack()
        yaw, pitch = root.yaw, root.pitch
        eyes = {}
        with root.open_camera(raw_images=True) as rehearsal:
            frame = rehearsal.glance(yaw,pitch)
            for node, option in ordered:
                if self.stop.is_set():
                    return False
                eyes[node] = live_appearance(frame)
                for n,forward,side,up,yaw,pitch,buttons in option.rows(yaw,pitch):
                    while n:
                        dt = min(n,4)
                        frame = rehearsal.frame(dt,forward,side,up,yaw,pitch,buttons)
                        n -= dt
            if not self.hud.completed(frame):
                self.rejected_witnesses += 1
                return False
        with self.lock:
            self.path_nodes = tuple(node for node,_ in ordered)
            self.rehearsed_eyes = eyes
            self.exit_route = {node:(step,option) for step,(node,option) in enumerate(ordered)}
            self.next_health = {node:self.cells[ordered[step+1][0]].hp
                                for step,(node,_) in enumerate(ordered[:-1])}
            self.win = {"slot":cell.slot, "depth":len(ordered),"at_trial":self.steps,
                        "continuous_visual_rehearsal":True}
        return True

    def _step(self):
        i = self._take_source()
        if i is None or self.cells[i].save is None:
            return
        parent = self.cells[i]
        self.root_steps[parent.slot] += 1
        move = parent.options[parent.tried]
        parent.tried += 1
        c = self.camera
        c.rebase(parent.save.unpack())
        end_heading, end_pitch = move.rows(parent.bearing, parent.pitch)[-1][4:6]
        frame = execute(c, move, parent.bearing, parent.pitch)
        self.steps += 1
        if self.hud.completed(frame):
            if not self._complete(i, move):
                self._schedule(i)
            return
        hp = self.hud.read(frame)
        if hp is not None and hp > 0:
            views = [c.glance(h, 0) for h in (0, 90, 180, 270)]
            desc = panorama_code(views)
            notice = self.hud.notice_font.read(frame) if self.hud.notice_font else ""
            stage = (parent.stage & ~3) | self.hud.key_mask(frame) | self.milestone(notice)
            self._free_search_space()
            with self.lock:
                ident, err, codes = self.index.find(desc, stage)
            if (
                (ident is None or err > 0.345)
                and len(self.cells) < self.limit
                and self.packed_bytes < 650_000_000
            ):
                state = c.snapshot(end_heading, end_pitch)
                if state:
                    notice = (
                        self.hud.notice_font.read(frame) if self.hud.notice_font else ""
                    )
                    with self.lock:
                        ident = self._insert(
                            state,
                            parent.slot,
                            i,
                            move,
                            parent.depth + 1,
                            end_heading,
                            err,
                            desc,
                            views,
                            codes,
                            stage,
                            notice,
                            frame,
                        )
                        parent.discoveries += 1
                        self.root_discoveries[parent.slot] += 1
                        if notice:
                            self.notices[notice[:110]] += 1
            elif err > 0.345:
                ident = None
            if ident is not None:
                with self.lock:
                    self.cells[ident].encounters += 1
                    if ident != i:
                        parent.edges.setdefault(ident, move)
        self._schedule(i)

    def _run(self):
        try:
            while not self.stop.is_set():
                with self.lock:
                    root = self.latest.popleft() if self.latest else None
                if root:
                    self._root(*root)
                elif any(self.queues.values()) and self.win is None:
                    self._step()
                else:
                    self.signal.wait(0.15)
                    self.signal.clear()
        except Exception as exc:
            with self.lock:
                self.error = f"{type(exc).__name__}: {str(exc)[:100]}"
        finally:
            if self.camera:
                self.camera.__exit__(None, None, None)

    def suggest(self, views, notice=None):
        desc = panorama_code(views)
        self.live_stage |= self.milestone(notice)
        stage = self.hud.key_mask(views[0]) | self.live_stage
        with self.lock:
            node, err, _ = self.index.find(desc, stage)
            if node is None or err > 0.30:
                return None
            c = self.cells[node]
            if self.last_live != node:
                c.live_visits += 1
                self.last_live = node
            if node in self.exit_route:
                step, move = self.exit_route[node]
                return dict(
                    option=move,
                    exit_steps=self.win["depth"] - step,
                    match=round(err, 3),
                    node=node,
                )
            # A short route to a landmark observed beyond the player's actual visits.
            queue = deque([(node, None, 0)])
            visited = {node}
            best = None
            while queue and len(visited) < 90:
                at, first, depth = queue.popleft()
                t = self.cells[at]
                if depth:
                    score = (
                        min(len(t.edges), 7) * 0.18
                        + 0.32 * min(4, t.discoveries)
                        + 0.20 * depth
                        - 1.1 * math.log1p(t.live_visits)
                        + 0.6 * t.novelty
                    )
                    exit_steps = None
                    if at in self.exit_route:
                        n, _ = self.exit_route[at]
                        exit_steps = self.win["depth"] - n + depth
                        score = 100 - exit_steps * 0.03
                    if best is None or score > best[0]:
                        best = (
                            score,
                            dict(
                                option=first,
                                exit_steps=exit_steps,
                                match=round(err, 3),
                                node=node,
                                target=at,
                            ),
                        )
                if depth >= 5:
                    continue
                for nxt, opt in t.edges.items():
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append((nxt, first or opt, depth + 1))
            return best[1] if best else None

    def root_request(self, tick, owned_slots):
        """Return only a slot the live agent created in this attempt."""
        with self.lock:
            if (
                not self.win
                or self.root_retries >= 3
                or self.win["slot"] not in owned_slots
            ):
                return None
            if self.rejoined_at is not None and (
                self.misses < 4 or tick - self.rejoined_at < 5 * 72
            ):
                return None
            return self.win["slot"]

    def restored(self, slot, tick):
        with self.lock:
            if slot in self.roots:
                self.live_stage = self.cells[self.roots[slot]].stage & ~3
            if self.win and self.win["slot"] == slot:
                self.root_retries += 1
                self.rejoined_at = tick
                self.misses = 0
                self.last_goal_step = None

    def _canonical(self, source):
        if self.verifier_camera is None:
            self.verifier_camera = source.open_camera(raw_images=True)
        else:
            self.verifier_camera.rebase(source)
        self.verifier_camera.frame(4,0,0,0,source.yaw,source.pitch,0)
        return panorama_code([self.verifier_camera.glance(h,0) for h in (0,90,180,270)])

    def _reference(self, node):
        if node not in self.canonical_views:
            cell = self.cells[node]
            chain = []
            while cell.save is None:
                chain.append(cell)
                cell = self.cells[cell.parent]
            source = cell.save.unpack()
            if chain:
                self._canonical(source)
                camera = self.verifier_camera
                camera.rebase(source)
                yaw,pitch = source.yaw,source.pitch
                for child in reversed(chain):
                    execute(camera, child.incoming, yaw, pitch)
                    yaw,pitch=child.bearing,child.pitch
                source = camera.snapshot(yaw,pitch)
                if source is None:
                    return self.index.vectors[node]
            self.canonical_views[node] = self._canonical(source)
        return self.canonical_views[node]

    def live_move(self, frame, yaw, pitch, source_factory=None):
        """Read the present camera, then check the next landing from a fresh own save."""
        with self.lock:
            if not self.win:
                return None
            current = live_appearance(frame)
            candidates = []
            expected = 0 if self.last_goal_step is None else self.last_goal_step + 1
            for node,(step,move) in self.exit_route.items():
                cell = self.cells[node]
                bearing = abs((yaw-cell.bearing+180)%360-180)
                error = min(eye_error(current,cell.eye),eye_error(current,self.rehearsed_eyes[node]))
                if bearing > 20 or abs(pitch-cell.pitch)>12:
                    continue
                if step != expected and error > 9:
                    continue
                candidates.append((step != expected,error+.1*bearing,step,move,node,error))
            candidates.sort(key=lambda row:row[:3])
        if not candidates:
            self.misses += 1
            return None
        try:
            source = source_factory() if source_factory else None
        except (RuntimeError, OSError, ValueError):
            self.misses += 1
            return None
        try:
            source_view = self._canonical(source) if source else None
        except (RuntimeError, OSError, ValueError):
            self.misses += 1
            return None
        begun = monotonic()
        for _,_,step,move,node,error in candidates[:3]:
            verified = False
            destination_error = None
            if source:
                if self.verifier_camera is None:
                    self.verifier_camera = source.open_camera(raw_images=True)
                else:
                    self.verifier_camera.rebase(source)
                last = execute(self.verifier_camera, move, yaw, pitch)
                if step+1 == len(self.path_nodes):
                    verified = self.hud.completed(last)
                else:
                    target = self.path_nodes[step+1]
                    pictures = [self.verifier_camera.glance(h,0) for h in (0,90,180,270)]
                    destination_error = scene_error(panorama_code(pictures),self.index.vectors[target])
                    hp = self.hud.read(last)
                    if destination_error >= .10:
                        end_heading,end_pitch = move.rows(yaw,pitch)[-1][4:6]
                        arrived = self.verifier_camera.snapshot(end_heading,end_pitch)
                        if arrived:
                            destination_error = min(destination_error,scene_error(self._canonical(arrived),self._reference(target)))
                    source_match = scene_error(source_view,self._reference(node))
                    verified = hp is not None and hp>0 and (destination_error<.10 or (source_match<.12 and destination_error<.28))
            else:
                verified = error <= 8 and step == expected
            if not verified:
                continue
            if self.last_goal_step == step and self.misses>=2:
                continue
            return move, {"step":step,"source":"current-attempt visual search","camera_error":round(error,2),
                          "next_view_error":round(destination_error,3) if destination_error is not None else None,
                          "recheck_ms":round((monotonic()-begun)*1000,1),
                          "steps_to_previewed_exit":len(self.path_nodes)-step,
                          "own_slot":self.win["slot"],"expected_health":self.next_health.get(node)}
        self.misses += 1
        return None

    def applied(self, witness):
        """A suggested move counts only when the live controller actually releases it."""
        step = witness["step"]
        self.misses = self.misses+1 if self.last_goal_step == step else 0
        self.last_goal_step = step

    def status(self):
        with self.lock:
            return dict(
                trials=self.steps,
                places=len(self.cells),
                root_trials=dict(self.root_steps),
                noticed_transitions=sum(self.milestone(k)!=0 for k in self.notices),
                rejected_visual_witnesses=self.rejected_witnesses,
                own_saves=len(self.roots),
                visible_exit=dict(self.win) if self.win else None,
                error=self.error,
                packed_mib=round(self.packed_bytes / (1024 * 1024), 1),
            )

    def close(self):
        self.stop.set()
        self.signal.set()
        if self.worker:
            self.worker.join()
        if self.verifier_camera:
            self.verifier_camera.__exit__(None,None,None)
