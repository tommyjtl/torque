"""Review previously unseen passages using four views from a private game camera."""

import io
import json
import math
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from landmarks import MARK_ACTION, Landmark, PanelScout, aim_angles
from PIL import Image, ImageDraw

HEADINGS = (0, 90, 180, 270)
PROMPT = """The game is Quake. Help the player explore an unknown level from the entrance and find its exit. Use only the pictures and this run's experiences. The four tiles show the same stationary first-person viewpoint facing directions A, B, C and D. The nine numbered cells in each tile mark potential directions. Each tile has its own grid numbered 1 through 9. The lower strip of each picture is the player's HUD.
Choose a specific opening, branch around an obstacle, jump landing, elevator, actionable control, or visible exit to approach. Inspect floor elevation and width; a painted panel can be a wall. Prefer a new passage or control over looking for fallen enemies or repeatedly circling a room. When a game sign or switch suggests a mechanism, propose an action whose effect can be checked on camera.
Return one JSON object with tile (one of A,B,C,D), cell (an integer 1 through 9), kind (one allowed marker kind), objective (one short sentence), evidence (one short visible cue). Valid marker kinds: passage, exit_opening, door, landing, touch_button, shoot_button, platform, health, armor, ammo. Consider a framed sliding door or lift which opens on approach. For a previously locked door, look for the control and a way back."""


def panorama_sheet(views):
    sheet = Image.new("RGB", (640, 524), "#151a18")
    draw = ImageDraw.Draw(sheet)
    for i, jpeg in enumerate(views):
        x, y = 320 * (i % 2), 262 * (i // 2)
        with Image.open(io.BytesIO(jpeg)) as image:
            sheet.paste(image.convert("RGB"), (x, y))
        for cell in range(9):
            col, row = cell % 3, cell // 3
            lx, ly = x + col * 107 + 4, y + row * 64 + 4
            draw.rectangle((lx, ly, lx + 13, ly + 13), fill="#192922")
            draw.text((lx + 3, ly), str(cell + 1), fill="#e7f1dd")
        draw.text(
            (x + 8, y + 243), chr(65 + i) + f"    {HEADINGS[i]} degrees", fill="#f2f1e9"
        )
    out = io.BytesIO()
    sheet.save(out, format="JPEG", quality=84)
    return out.getvalue()


def describe(views):
    def compact(view):
        gray = cv2.imdecode(np.frombuffer(view, np.uint8), cv2.IMREAD_GRAYSCALE)
        return cv2.resize(gray[12:160], (18, 12), interpolation=cv2.INTER_AREA)

    return np.stack([compact(v) for v in views]).astype(np.float32)


class PanoramaPlan:
    def __init__(self, provider, directory):
        self.provider = provider
        self.directory = directory
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="quake-preview-planner")
        self.job = None
        self.submitted = -10000
        self.epoch = 0
        self.landmarks = deque(maxlen=24)

    def invalidate(self):
        self.epoch += 1
        self.landmarks.clear()

    def update(self, views, tick, context):
        if self.job and self.job[0].done():
            future, original, source_tick, epoch = self.job
            self.job = None
            if epoch == self.epoch and not future.exception():
                answer = future.result()
                tile = str(answer.get("tile", "")).upper()
                marker = None
                cell, kind = answer.get("cell"), answer.get("kind")
                if (
                    isinstance(cell, int)
                    and 1 <= cell <= 9
                    and (kind == "door" or kind in MARK_ACTION)
                    and tile in list("ABCD")
                ):
                    point = [
                        ((cell - 1) % 3 + 0.5) * 100 / 3,
                        ((cell - 1) // 3 + 0.5) * 80 / 3,
                    ]
                    if kind in ("touch_button", "shoot_button"):
                        bgr = cv2.imdecode(
                            np.frombuffer(original[ord(tile) - 65], np.uint8),
                            cv2.IMREAD_COLOR,
                        )
                        candidates = PanelScout.candidates(
                            cv2.cvtColor(bgr[:192], cv2.COLOR_BGR2RGB)
                        )
                        if candidates:
                            candidate = min(
                                candidates, key=lambda m: math.dist(point, m["point"])
                            )
                            if math.dist(point, candidate["point"]) < 30:
                                point = candidate["point"]
                    marker = {"kind": kind, "point": point}
                if (
                    tile in list("ABCD")
                    and marker
                    and marker["kind"] != "fallen_character"
                ):
                    index = ord(tile) - 65
                    mark = Landmark(original[index], marker, HEADINGS[index], 0)
                    record = {
                        "source_tick": source_tick,
                        "tile": tile,
                        "objective": str(answer.get("objective", ""))[:220],
                        "evidence": str(answer.get("evidence", ""))[:220],
                        "marker": marker,
                        "cell": cell,
                        "model": self.provider.cloud_model,
                    }
                    descriptor = describe(original)
                    record["landmark_id"] = source_tick
                    for prior, old_mark, baseline in reversed(self.landmarks):
                        if (
                            prior["tile"] != tile
                            or prior["marker"]["kind"] != marker["kind"]
                        ):
                            continue
                        if (
                            np.sort(np.abs(descriptor - baseline).mean(axis=(1, 2)))[
                                :3
                            ].mean()
                            > 16
                        ):
                            continue
                        found = old_mark.locate(original[index], HEADINGS[index], 0)
                        if found and math.dist(found["point"], marker["point"]) <= 8:
                            record["landmark_id"] = prior["landmark_id"]
                            break
                    self.landmarks.append((record, mark, descriptor))
                    if self.directory:
                        with (self.directory / "panorama-plans.jsonl").open("a") as out:
                            print(json.dumps(record), file=out)
        grounded = None
        locations = describe(views)
        ranked = []
        for record, mark, original in tuple(self.landmarks):
            diff = np.abs(original - locations).mean(axis=(1, 2))
            room_error = float(np.sort(diff)[:3].mean())
            ranked.append((room_error, -record["source_tick"], record, mark, diff))
        matches = []
        for room_error, _, record, mark, errors in sorted(
            ranked, key=lambda item: item[:2]
        )[:4]:
            if room_error > 28:
                continue
            i = ord(record["tile"]) - 65
            marker = record["marker"]
            match = mark.locate(views[i], HEADINGS[i], 0)
            if match:
                point, strength = match["point"], match["match"]
            elif room_error < 7 and errors[i] < 8:
                point, strength = marker["point"], 0.82
            else:
                continue
            angle, elevation = aim_angles(point, HEADINGS[i])
            kind = marker["kind"]
            priority = (
                strength
                + (
                    0.27
                    if kind
                    in (
                        "exit_opening",
                        "door",
                        "touch_button",
                        "shoot_button",
                        "platform",
                    )
                    else 0
                )
                - room_error / 150
            )
            matches.append(
                (
                    priority,
                    dict(
                        record,
                        match=strength,
                        bearing=angle,
                        aim_pitch=elevation,
                        matched_point=point,
                        kind=kind,
                    ),
                )
            )
        if matches:
            grounded = max(matches, key=lambda item: item[0])[1]
        if not self.job and tick - self.submitted >= (6 if not grounded else 12) * 72:
            stream = panorama_sheet(views)
            if self.directory:
                folder = self.directory / "panoramas"
                folder.mkdir(exist_ok=True)
                (folder / f"{tick}.jpg").write_bytes(stream)
            self.job = (
                self.pool.submit(
                    self.provider._read_frame,
                    stream,
                    PROMPT + "\nRecent camera comparisons: " + json.dumps(context),
                    200,
                ),
                views,
                tick,
                self.epoch,
            )
            self.submitted = tick
        return grounded

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
