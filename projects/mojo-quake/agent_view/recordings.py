"""Produce seekable, annotated H.264 replays from the actual Quake input log."""

import io
import json
import os
import subprocess
import threading
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import lru_cache
from queue import Queue

from checkpoints import checkpoint_operation
from game import Game
from PIL import Image, ImageDraw, ImageFont

FPS = 18  # The observatory publishes a motion frame every four 72 Hz ticks.
VIDEO = "agent.mp4"
META = "recording.json"


@lru_cache
def font(size, bold=False):
    names = (
        ("Arial Bold.ttf", "DejaVuSans-Bold.ttf")
        if bold
        else ("Arial.ttf", "DejaVuSans.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def paragraph(draw, xy, text, size, color, width, height):
    for points in range(size, 11, -1):
        face = font(points)
        lines = []
        line = ""
        for word in text.split():
            candidate = (line + " " + word).strip()
            if line and draw.textlength(candidate, font=face) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
        leading = points + 4
        if len(lines) * leading <= height:
            break
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=face, fill=color)
        y += leading
    return y


class PlanTimeline:
    """Read planner events in game time so a late reply appears only after arrival."""

    def __init__(self, path):
        self.entries = [json.loads(line) for line in path.read_text().splitlines()]
        self.cursor = 0
        self.by_id = {}

    def at(self, tick):
        while self.cursor < len(self.entries):
            entry = self.entries[self.cursor]
            when = entry.get(
                "changed_tick",
                entry.get(
                    "applied_tick", entry.get("received_tick", entry["source_tick"])
                ),
            )
            if when > tick:
                break
            self.by_id[entry["id"]] = entry
            self.cursor += 1
        active = [
            r
            for r in self.by_id.values()
            if r["status"] in ("Available", "Used", "Delivered", "Input matched")
        ]
        return active[-1] if active else next(reversed(self.by_id.values()), {})


class DecisionCard:
    def __init__(self, event, scenario, observation=None, timeline=None, preview=None):
        self.timeline = timeline
        self.event = event
        self.preview = preview
        self.observation = None
        if observation:
            self.observation = (
                Image.open(io.BytesIO(observation)).convert("RGB").resize((160, 120))
            )
            marker = ImageDraw.Draw(self.observation)
            for key, color in (
                ("enemy", "#ffc07d"),
                ("route", "#abe8bf"),
                ("landing", "#9dd3fc"),
            ):
                point = (event["vision"] or {}).get(key)
                if point is not None:
                    x, y = round(159 * point[0] / 100), round(119 * point[1] / 100)
                    marker.ellipse((x - 3, y - 3, x + 3, y + 3), outline=color, width=2)
        vision_time = (
            "" if event["vision_ms"] is None else f"  ·  {event['vision_ms']} ms"
        )
        decision_time = (
            "" if event["decision_ms"] is None else f"  ·  {event['decision_ms']} ms"
        )
        provider = "Mac / Gemma 4 E4B"
        if event.get("controller") == "layered":
            provider = ("Modular Cloud / Gemma 4 31B" if event.get("decision_model") == "google/gemma-4-31b-it"
                        else "Mac / Laya English 421M")
        if event.get("controller") == "single-call":
            provider = "Modular Cloud / same call"
            if event.get("inference_ms") is not None:
                vision_time = f"  ·  {event['inference_ms']} ms"
        if event.get("input_source") in (
            "local recovery",
            "Local fallback",
            "HUD reflex",
            "HUD pickup",
            "Quake checkpoint",
            "Checkpoint memory",
            "Local character detector",
            "Navigation recovery",
            "Camera navigation",
            "Own-save lookahead",
            "Landmark inspection",
            "Game message",
        ):
            provider = event["input_source"]
        vision_label = (
            "Mac / " + event.get("vision_detector", "YOLO11n")
            if provider == "Local character detector"
            else "Mac / RGB camera and HUD"
            if event.get("controller") == "layered"
            else f"Modular / {event.get('cloud_model', 'google/gemma-4-31b-it').split('/')[-1]}"
        )
        canvas = Image.new("RGB", (1056, 560), "#151a18")
        self.canvas = canvas
        d = ImageDraw.Draw(canvas)
        d.text(
            (16, 10), "Quake  /  Agent Observatory", font=font(24, True), fill="#f1f4ed"
        )
        d.text((680, 17), f"E1M1  /  {scenario}", font=font(16), fill="#bcc5be")
        d.rounded_rectangle((671, 49, 1039, 527), radius=8, fill="#202823")
        x = 687
        d.text((x, 64), f"DECISION {event['seq']}", font=font(15, True), fill="#b3c4b8")
        d.text((x, 105), "Vision", font=font(26, True), fill="#a9e6ba")
        d.text(
            (x, 140),
            "Native Quake save/load"
            if event.get("checkpoint")
            else f"{vision_label}{vision_time}",
            font=font(15),
            fill="#c0cbc3",
        )
        y = paragraph(
            d,
            (x, 171),
            event["reason"]
            if event.get("checkpoint")
            else (event["vision"] or {}).get("scene")
            or ((event.get("lookahead") or {}).get("panorama_plan") or {}).get(
                "evidence"
            )
            or (
                "The live viewpoint matched the camera preview."
                if event.get("input_source") == "Own-save lookahead"
                else "Reading game frame…"
            ),
            18,
            "#f2f4e9",
            334,
            145,
        )
        y = max(270, y + 15)
        d.line((x, y, 1020, y), fill="#455248")
        d.text((x, y + 13), "Decision", font=font(26, True), fill="#ffc07d")
        d.text(
            (x, y + 47),
            f"{provider}{decision_time}",
            font=font(15),
            fill="#c0cbc3",
        )
        d.text(
            (x, y + 78),
            (event["action"] or "Waiting").replace("_", " ").title(),
            font=font(23, True),
            fill="#ffc07d",
        )
        paragraph(
            d,
            (x, y + 112),
            event["reason"]
            if (event.get("lookahead") or {}).get("selected")
            else event.get("note") or event["reason"],
            16,
            "#e4ebe4",
            334,
            75,
        )

    def render(self, jpeg, tick, status, marks=False):
        canvas = self.canvas.copy()
        game = (
            Image.open(io.BytesIO(jpeg))
            .convert("RGB")
            .resize((640, 480), Image.Resampling.NEAREST)
        )
        canvas.paste(game, (16, 48))
        d = ImageDraw.Draw(canvas)
        if self.observation:
            canvas.paste(self.observation, (26, 57))
            d.rectangle((25, 56, 186, 177), outline="#a9e6ba")
            d.rectangle((25, 178, 186, 198), fill="#202823")
            d.text(
                (30, 179),
                f"Model input · {self.event['observed_tick']}",
                font=font(13),
                fill="#f1f4ed",
            )
        if marks and self.event["vision"]:
            for key, label, color in (
                ("enemy", "Enemy", "#ffc07d"),
                ("route", "Route", "#abe8bf"),
                ("landing", "Landing", "#9dd3fc"),
                ("switch", "Switch", "#d7c4ec"),
                ("panel", "Possible control", "#d7c4ec"),
                ("platform", "Platform", "#d7c4ec"),
                ("pickup", "Pickup", "#d7c4ec"),
            ):
                point = self.event["vision"].get(key)
                if point is not None:
                    x = 16 + round(639 * point[0] / 100)
                    y = 48 + round(479 * point[1] / 100)
                    d.ellipse((x - 7, y - 7, x + 7, y + 7), outline=color, width=2)
                    d.text(
                        (min(x + 9, 600), min(y, 502)),
                        label,
                        fill=color,
                        font=font(14, True),
                        stroke_width=1,
                        stroke_fill="#141917",
                    )
        d.text((16, 535), status, font=font(15, True), fill="#d6e4d8")
        d.text((680, 535), f"Game tick {tick}", font=font(15), fill="#c0cbc3")
        if self.timeline is not None:
            plan = self.timeline.at(tick)
            guide = (
                (self.event.get("lookahead") or {}).get("panorama_plan")
                if self.preview is not None
                else None
            )
            if guide:
                plan = dict(
                    guide,
                    status="Landmark matched",
                    trigger=f"Panorama view {guide['tile']}",
                )
            extended = Image.new("RGB", (1056, 710), "#202124")
            extended.paste(canvas)
            draw = ImageDraw.Draw(extended)
            draw.text(
                (17, 570),
                "Panorama planner" if guide else "Background planner",
                font=font(18, True),
                fill="#d7c4ec",
            )
            model = plan.get("model", "").split("/")[-1]
            draw.text(
                (242, 573),
                f"{model}   {plan.get('status', 'Standby')}",
                font=font(15),
                fill="#c6bdce",
            )
            paragraph(
                draw,
                (17, 600),
                plan.get("objective")
                or plan.get("status_note")
                or "Waiting for a planner reply.",
                18,
                "#f2f4e9",
                610,
                88,
            )
            if self.preview is not None:
                look = self.event["lookahead"]
                draw.text(
                    (655, 569),
                    f"{len(look['alternatives'])} previews · selected {look['selected']}",
                    font=font(14, True),
                    fill="#ffcb91",
                )
                extended.paste(self.preview, (655, 594))
            elif plan.get("evidence"):
                paragraph(draw, (655, 600), plan["evidence"], 14, "#c5cac6", 380, 65)
            if plan:
                caption = f"Source tick {plan['source_tick']} · {plan['trigger']}"
                if plan.get("applied_step"):
                    caption += (
                        f" · {plan['applied_input']} at step {plan['applied_step']}"
                    )
                draw.text((17, 680), caption, font=font(14), fill="#d7c4ec")
            canvas = extended
        data = io.BytesIO()
        canvas.save(data, "JPEG", quality=88)
        return data.getvalue()


def export_video(directory, binary, media, gpu, scenario, result):
    """Replay every completed action, checking its end-state hash before publication."""
    stage = directory / "agent.partial.mp4"
    count = frames = saves = reloads = 0
    label = "First encounter" if scenario == "encounter" else "Level entrance"
    try:
        plan_log = directory / "planner.jsonl"
        timeline = PlanTimeline(plan_log) if plan_log.is_file() else None
        with ExitStack() as stack:
            game = Game(
                binary,
                media,
                gpu,
                start_map="start" if scenario == "encounter" else "e1m1",
            )
            stack.callback(game.close)
            moves = stack.enter_context((directory / "inputs.trace").open())
            log = stack.enter_context((directory / "decisions.jsonl").open())
            error = stack.enter_context((directory / "video-encode.log").open("w"))
            encoder = subprocess.Popen(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "image2pipe",
                    "-c:v",
                    "mjpeg",
                    "-framerate",
                    str(FPS),
                    "-i",
                    "pipe:0",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-threads",
                    "2",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(stage),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=error,
            )
            stack.callback(encoder.wait)
            stack.callback(encoder.stdin.close)

            def put(frame, repeat=1):
                nonlocal frames
                for _ in range(repeat):
                    encoder.stdin.write(frame)
                frames += repeat

            def next_frame(stop):
                line = moves.readline()
                if not line:
                    raise ValueError("Input trace ended before the recorded decision")
                n, f, s, u, y, p, b, i = line.split()
                n = int(n)
                if n < 1 or game.tick + n > stop:
                    raise ValueError("Decision and input ticks do not align")
                game.yaw, game.pitch = float(y), float(p)
                jpg, state, _ = game.move(
                    n,
                    int(f),
                    int(s),
                    int(b),
                    up=int(u),
                    impulse=int(i),
                    evaluate=game.tick + n == stop,
                )
                return jpg, state

            jpg = state = None
            realtime_origin = None
            realtime_frames = 0
            for line in log:
                event = json.loads(line)
                start, end = event["observed_tick"], event["end_tick"]
                while game.tick < start:
                    jpg, state = next_frame(start)
                if (
                    game.tick != start
                    or state["hash"] != event["observed_stats"]["hash"]
                ):
                    raise ValueError(f"Observation mismatch at tick {start}")
                if event.get("checkpoint"):
                    checkpoint_operation(game, event["checkpoint"])
                    saves += int(event["checkpoint"]["op"] == "save")
                    reloads += int(event["checkpoint"]["op"] == "load")
                original = directory / "frames" / f"{start}.jpg"
                observed = original.read_bytes() if original.is_file() else jpg
                realtime = event.get("timing") == "real-time"
                preview = None
                sheet_tick = (event.get("lookahead") or {}).get("sheet_tick")
                if (
                    type(sheet_tick) is int
                    and event.get("input_source") == "Own-save lookahead"
                ):
                    sheet_path = directory / "previews" / f"{sheet_tick}.jpg"
                    if sheet_path.is_file():
                        with Image.open(sheet_path) as sheet:
                            preview = sheet.convert("RGB").resize(
                                (384, 104), Image.Resampling.LANCZOS
                            )
                card = DecisionCard(
                    event, label, observed if realtime else None, timeline, preview
                )
                if realtime:
                    if realtime_origin is None:
                        realtime_origin = start
                    pending = dict(
                        event, action=None, decision_ms=None, reason="", note=""
                    )
                    seeing = DecisionCard(
                        dict(pending, vision=None, vision_ms=None, inference_ms=None),
                        label,
                        observed,
                        timeline,
                    )
                    choosing = DecisionCard(pending, label, observed, timeline)
                else:
                    put(
                        card.render(observed, start, "Observed frame", marks=True),
                        2 * FPS,
                    )
                motion_frames = 0
                while game.tick < end:
                    jpg, state = next_frame(end)
                    if realtime:
                        total = round((game.tick - realtime_origin) * FPS / 72)
                        active, status = seeing, "Reading frame · game running"
                        if (
                            event.get("vision_tick") is not None
                            and game.tick >= event["vision_tick"]
                        ):
                            if event.get("controller") == "single-call":
                                active, status = card, "Observation and input received"
                            else:
                                active, status = (
                                    choosing,
                                    "Choosing action · game running",
                                )
                        if (
                            event.get("applied_tick") is not None
                            and game.tick > event["applied_tick"]
                        ):
                            active, status = card, "Applying input"
                            if (
                                event["action"]
                                in ("jump_forward", "jump_back", "evade_and_scan")
                                and event.get("jump_press_tick") is not None
                            ):
                                if game.tick < event["jump_press_tick"]:
                                    status = (
                                        "Running up"
                                        if event["action"] == "jump_forward"
                                        else "Backing away"
                                    )
                                elif game.tick < (
                                    event.get("jump_release_tick") or end + 1
                                ):
                                    status = (
                                        "Jump + forward"
                                        if event["action"] == "jump_forward"
                                        else "Jumping back"
                                    )
                                else:
                                    status = (
                                        "Holding forward"
                                        if event["action"] == "jump_forward"
                                        else "Retreating"
                                    )
                                if (
                                    event.get("scan_tick")
                                    and game.tick >= event["scan_tick"]
                                ):
                                    status = "Checking behind"
                        elif game.tick == end and event.get("note"):
                            active, status = card, event["note"]
                        if total > realtime_frames:
                            put(
                                active.render(jpg, game.tick, status),
                                total - realtime_frames,
                            )
                            realtime_frames = total
                    else:
                        total = max(1, round((game.tick - start) * FPS / 72))
                        if total > motion_frames:
                            put(
                                card.render(jpg, game.tick, "Applying input"),
                                total - motion_frames,
                            )
                            motion_frames = total
                if state["hash"] != event["evaluator"]["hash"]:
                    raise ValueError(f"Gameplay mismatch at tick {end}")
                count += 1
            if not count:
                raise ValueError("No completed decisions to record")
            put(card.render(jpg, game.tick, result), 2 * FPS)
            encoder.stdin.close()
            if encoder.wait():
                raise RuntimeError(
                    "FFmpeg could not encode the recording (see video-encode.log)"
                )
        os.replace(stage, directory / VIDEO)
        return {
            "steps": count,
            "duration": round(frames / FPS, 2),
            "saves": saves,
            "reloads": reloads,
        }
    finally:
        stage.unlink(missing_ok=True)


class Recordings:
    def __init__(self, args):
        self.root, self.binary, self.media = args.records, args.binary, args.media
        self.queue = Queue()
        self.lock = threading.Lock()
        self.entries = {}
        for path in self.root.glob("session-*/" + META):
            entry = json.loads(path.read_text())
            self.entries[path.parent.name] = entry
            if entry["status"] in ("Queued", "Encoding"):
                self.queue.put(path.parent)
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def _save(self, directory, entry):
        tmp = directory / (META + ".tmp")
        tmp.write_text(json.dumps(entry, indent=2) + "\n")
        tmp.replace(directory / META)
        self.entries[directory.name] = entry

    def submit(self, directory, scenario, result, gpu):
        with self.lock:
            if directory.name in self.entries:
                return
            self._save(
                directory,
                {
                    "id": directory.name,
                    "scenario": scenario,
                    "result": result,
                    "gpu": gpu,
                    "finished": datetime.now(UTC).isoformat(),
                    "status": "Queued",
                },
            )
        self.queue.put(directory)

    def _work(self):
        while True:
            directory = self.queue.get()
            with self.lock:
                entry = dict(self.entries[directory.name], status="Encoding")
                self._save(directory, entry)
            try:
                details = export_video(
                    directory,
                    self.binary,
                    self.media,
                    entry["gpu"],
                    entry["scenario"],
                    entry["result"],
                )
                entry = dict(entry, status="Ready", **details)
            except (
                OSError,
                ValueError,
                KeyError,
                RuntimeError,
                subprocess.SubprocessError,
            ) as exc:
                entry = dict(entry, status="Failed", error=str(exc)[:220])
            with self.lock:
                self._save(directory, entry)

    def list(self):
        with self.lock:
            return sorted(
                self.entries.values(), key=lambda x: x["finished"], reverse=True
            )

    def file(self, ident):
        with self.lock:
            if self.entries.get(ident, {}).get("status") == "Ready":
                return self.root / ident / VIDEO
        return None
