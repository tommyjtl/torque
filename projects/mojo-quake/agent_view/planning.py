"""Run strategic advice off the game thread and report its observable lifecycle."""

import base64
import json
import time
from collections import deque
from urllib.parse import urlsplit

import httpx
from game import view_signature, visual_change
from landmarks import MARK_ACTION, Landmark, validated_marker
from models import CLOUD_MODELS

INTENTS = {
    "explore": ("advance", "follow_route", "test_passage", "branch_turn"),
    "inspect": ("turn_left", "turn_right", "look_down", "branch_turn"),
    "cross": ("jump_forward", "test_ledge"),
    "interact": ("board_platform", "ride_lift", "touch_switch", "shoot_switch"),
    "resupply": ("collect_item", "follow_route"),
    "disengage": (
        "bypass_enemy",
        "back_up",
        "turn_around",
        "strafe_left",
        "strafe_right",
    ),
}
PROMPT = """You are the background planner for a Quake player exploring E1M1 from the entrance. The game continues during this request.
Use only this camera image and the supplied local observations. Return a JSON object containing
intent, objective, evidence, success, next_input and character. next_input is the first input you suggest: advance, turn_left, turn_right, back_up, jump_forward, test_passage, bypass_enemy, follow_route, touch_switch, shoot_switch, board_platform or collect_item. Select intent from explore, inspect, cross, interact, resupply, disengage.
Give the player one short objective. For evidence name a concrete visible cue or a recorded failed attempt.
For success give one observable outcome that would end the objective. Each text field is one short sentence.
Character is active, fallen, uncertain or none. A prone body can be a defeated enemy. Distinguish a lamp from an enterable opening.
Also return marker: null or {"kind":"KIND","point":[x,y]} centered on visible evidence, in percent of the full source image.
Allowed kinds are passage, exit_opening, landing, touch_button, shoot_button, platform, health, ammo, armor and fallen_character.
For an interaction or pickup point to the object itself. For exit_opening point inside a traversable marked opening, not at a lamp or sign.
If the local character marker points to a prone body, mark that body. Inspect another direction when the view is ambiguous."""


def read_plan(provider, frame, context, reference=None):
    result = provider._read_frame(
        frame, PROMPT + "\n" + json.dumps(context, separators=(",", ":")), 220,
        **({"reference": reference} if reference is not None else {}),
    )
    if result.get("intent") not in INTENTS or result.get("character") not in (
        "active",
        "fallen",
        "uncertain",
        "none",
    ):
        raise ValueError("Invalid planner categories")
    output = {k: result[k] for k in ("intent", "character")}
    if result.get("next_input") in (
        "advance",
        "turn_left",
        "turn_right",
        "back_up",
        "jump_forward",
        "test_passage",
        "bypass_enemy",
        "follow_route",
        "touch_switch",
        "shoot_switch",
        "board_platform",
        "collect_item",
    ):
        output["next_input"] = result["next_input"]
    marker = validated_marker(result.get("marker"))
    if marker:
        output["marker"] = marker
    for key in ("objective", "evidence", "success"):
        value = result.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 400:
            raise ValueError("Incomplete planner response")
        output[key] = value.strip()
    return output


class PlanFeed:
    def __init__(self, provider, pool, directory, past=None):
        self.provider, self.pool, self.directory = provider, pool, directory
        self.records = deque(maxlen=8)
        self.active_id = None
        self.landmark = None
        self.remembered_marks = deque(maxlen=20)
        self.tried_marks = {}
        self.considered_tick = -1
        self.considered_mark = None
        self.ground_cache = None
        self.job = None
        self.last_submit = -2000
        self.last_trigger = None
        self.generation = 0
        self.clock = 0
        self.revision = 0
        log_path = directory / "planner.jsonl"
        if past and past.is_file() and past != log_path:
            from shutil import copyfile

            copyfile(past, log_path)
        if log_path.is_file():
            with log_path.open() as source:
                for line in source:
                    record = json.loads(line)
                    self._replace(record)
                    self.clock = max(
                        self.clock, record.get("changed_tick", record["source_tick"])
                    )
            for record in list(self.records):
                if record["status"] in (
                    "Reviewing",
                    "Available",
                    "Used",
                    "Delivered",
                    "Input matched",
                ):
                    self._save(
                        dict(
                            record,
                            status="Expired",
                            status_note="Run continued from a saved position.",
                        )
                    )

    def _replace(self, record):
        for i, old in enumerate(self.records):
            if old["id"] == record["id"]:
                self.records[i] = record
                return
        self.records.append(record)

    def _save(self, record):
        self.revision += 1
        record = dict(record, changed_tick=self.clock)
        self._replace(record)
        with (self.directory / "planner.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, separators=(",", ":")) + "\n")

    def invalidate(self, reason, tick=None):
        if tick is not None:
            self.clock = tick
        self.generation += 1
        for r in list(self.records):
            if r["status"] in (
                "Reviewing",
                "Available",
                "Used",
                "Delivered",
                "Input matched",
            ):
                self._save(dict(r, status="Expired", status_note=reason))
        self.active_id = self.landmark = self.ground_cache = None
        self.considered_tick = -1
        self.considered_mark = None
        self.last_trigger = None
        if self.job and self.job[0].cancel():
            self.job = None

    def active(self):
        return next((r for r in self.records if r["id"] == self.active_id), None)

    def _current_mark(self, frame, game):
        current = self.active()
        if not current or self.landmark is None:
            return None
        if not self.ground_cache or self.ground_cache[:2] != (current["id"], game.tick):
            self.ground_cache = (
                current["id"],
                game.tick,
                self.landmark.locate(frame, game.yaw, game.pitch),
            )
        return self.ground_cache[2]

    def ground(self, frame, game):
        if self.considered_tick == game.tick:
            return self.considered_mark
        self.considered_tick = game.tick
        self.considered_mark = None
        active = self.active()
        point = self._current_mark(frame, game)
        if point and active and self.tried_marks.get(active["id"], -10000) <= game.tick:
            self.considered_mark = dict(
                point,
                source_tick=active["source_tick"],
                source_step=active["source_step"],
                source_plan=active["id"],
            )
            return self.considered_mark
        for saved, anchor in reversed(self.remembered_marks):
            if self.tried_marks.get(saved["id"], -10000) > game.tick:
                continue
            if self.turned(saved, game):
                continue
            found = anchor.locate(frame, game.yaw, game.pitch)
            if found and found["match"] >= 0.91:
                self.considered_mark = dict(
                    found,
                    source_tick=saved["source_tick"],
                    source_step=saved["source_step"],
                    source_plan=saved["id"],
                    revisited=True,
                )
                return self.considered_mark
        return None

    def landmark_attempt(self, mark, tick):
        if mark and "source_plan" in mark:
            self.tried_marks[mark["source_plan"]] = tick + 10 * 72
            self.considered_tick = -1

    def snapshot(self):
        return {
            "model": self.provider.cloud_model,
            "revision": self.revision,
            "active_id": self.active_id,
            "records": list(self.records),
        }

    @staticmethod
    def turned(record, game):
        yaw = abs((game.yaw - record.get("source_yaw", game.yaw) + 180) % 360 - 180)
        return yaw > 45 or abs(game.pitch - record.get("source_pitch", game.pitch)) > 25

    def tick(self, game, frame, memory):
        tick = self.clock = game.tick
        current = self.active()
        if current and (
            tick - current["source_tick"] > 20 * 72
            or current["intent"] in ("interact", "cross", "disengage")
            and (memory.here != current["place"] or self.turned(current, game))
            and not self._current_mark(frame, game)
        ):
            self._save(
                dict(
                    current,
                    status="Expired",
                    status_note="The player moved on or the observation aged out.",
                )
            )
            self.active_id = None
        if self.job is None or not self.job[0].done():
            return
        future, request, generation, started, signature = self.job
        self.job = None
        if generation != self.generation:
            return
        record = dict(
            request,
            received_tick=tick,
            latency_ms=round(1000 * (time.monotonic() - started)),
        )
        try:
            record.update(future.result())
        except (ValueError, LookupError, TypeError, httpx.HTTPError) as exc:
            self._save(
                dict(
                    record,
                    status="Failed",
                    status_note=f"Planner request failed ({type(exc).__name__}).",
                )
            )
            return
        stale = tick - request["source_tick"] > 16 * 72 or (
            request["place"] != memory.here and visual_change(signature, frame) > 9
        )
        stale = stale or (
            record["intent"] in ("cross", "interact", "disengage")
            and self.turned(record, game)
        )
        anchor = None
        if record.get("marker"):
            original = self.directory / "frames" / f"{record['source_tick']}.jpg"
            if original.is_file():
                anchor = Landmark(
                    original.read_bytes(),
                    record["marker"],
                    record["source_yaw"],
                    record["source_pitch"],
                )
                if tick - record["source_tick"] <= 16 * 72 and anchor.locate(
                    frame, game.yaw, game.pitch
                ):
                    stale = False
        if (
            anchor
            and anchor.patch is not None
            and record["marker"]["kind"]
            in (
                "touch_button",
                "shoot_button",
                "platform",
                "exit_opening",
                "health",
                "ammo",
                "armor",
            )
        ):
            self.remembered_marks.append((record, anchor))
            record["landmark_retained"] = True
        if stale:
            self._save(
                dict(
                    record,
                    status="Discarded",
                    status_note="The source scene changed before the reply arrived.",
                )
            )
            return
        old = self.active()
        if old:
            self._save(
                dict(
                    old,
                    status="Superseded",
                    status_note="A newer objective was accepted.",
                )
            )
        self.considered_tick = -1
        self.landmark = anchor
        self.ground_cache = None
        self.active_id = record["id"]
        self._save(dict(record, status="Available"))

    def request_if_needed(self, game, frame, step, memory, damage, recent):
        if self.job:
            return
        tick = game.tick
        state = memory.guidance(None)
        hud = damage.context(tick) if damage else {}
        tag = (
            "Visible character"
            if memory.character
            else "Health loss"
            if hud.get("hit_ticks_ago") is not None
            else "Blocked forward"
            if state.get("movement_lesson")
            else "Familiar passage"
            if state["recover"]
            else "Route review"
        )
        if (
            self.records
            and tick - self.last_submit < (5 if tag != self.last_trigger else 14) * 72
        ):
            return
        trigger = "First observation" if not self.records else tag
        record = {
            "id": tick,
            "source_tick": tick,
            "source_step": step,
            "source_yaw": game.yaw,
            "source_pitch": game.pitch,
            "place": memory.here,
            "trigger": trigger,
            "status": "Reviewing",
            "model": self.provider.cloud_model,
        }
        (self.directory / "frames" / f"{tick}.jpg").write_bytes(frame)
        context = {
            "camera_lanes": (
                memory.lane_sense.current(tick, game.yaw, game.pitch) or {}
            ).get("pick")
            if memory.lane_sense
            else None,
            "trigger": trigger,
            "recent_inputs": recent,
            "navigation": state,
            "hud": hud,
            "local_character": (memory.character or {}).get("point"),
        }
        guide = getattr(memory, "route_guide", None)
        if guide:
            context["prepared_route"] = guide.context
            record["route_reference"] = guide.context["photo"]
        lessons = getattr(memory, "movement_lessons", None)
        if state.get("movement_lesson"):
            context["movement_lesson"] = state["movement_lesson"]
        elif lessons and lessons.advice(tick):
            context["movement_lesson"] = lessons.advice(tick)
        if memory.skill_book:
            context["past_traversal"] = memory.skill_book.hints("stalled_forward" if state.get("movement_lesson") else None)
        preview = getattr(memory, "preview", None)
        if preview and preview.receipt:
            result = preview.receipt
            context["last_camera_previews"] = {
                "age_ticks": tick - result["selected_tick"],
                "chosen": result["selected"],
                "alternatives": result["alternatives"][:3],
            }
        if memory.panels and memory.panels.candidate:
            context["visual_hypothesis"] = {
                "point": memory.panels.candidate["point"],
                "cue": "A compact red marking is visible. Check its surround before deciding whether it is a control.",
            }
        if self.records:
            context["past_objectives"] = [
                {
                    "objective": p.get("objective"),
                    "last_input": p.get("applied_input") or p.get("first_input"),
                    "status": p["status"],
                }
                for p in list(self.records)[-4:]
                if p.get("objective")
            ]
        self.last_trigger, self.last_submit = tag, tick
        self._save(record)
        self.job = (
            self.pool.submit(read_plan, self.provider, frame, context,
                             guide.atlas.photos[guide.context["photo"]] if guide else None),
            record,
            self.generation,
            time.monotonic(),
            view_signature(frame),
        )

    def receipt(self, plan_id, step, tick, action, source):
        r = self.active()
        if r is None or r["id"] != plan_id:
            return
        self.clock = tick
        followed = action == r.get("next_input") and source in (
            "model",
            "Mac local model",
            "TypeSafe Jev",
            "Modular Gemma",
        )
        if r.get("seen_step") and (not followed or r.get("applied_step")):
            return
        record = dict(
            r,
            seen_step=r.get("seen_step", step),
            first_input=r.get("first_input", action),
            first_input_source=r.get("first_input_source", source),
            status="Delivered",
        )
        if followed:
            record.update(
                status="Input matched",
                applied_step=step,
                applied_tick=tick,
                applied_input=action,
                input_source=source,
            )
        self._save(record)


LOCAL_MODEL = "laya:en"
CHOICES = {
    "advance": "Walk forward into an open passage or follow the current exploration objective.",
    "turn_left": "Inspect a new direction on the left or turn away from a blocked approach.",
    "turn_right": "Inspect a new direction on the right or turn away from a blocked approach.",
    "back_up": "Back away from an obstacle or danger and find a different approach.",
    "strafe_left": "Step sideways to the left to clear the blocked approach.",
    "strafe_right": "Step sideways to the right to clear the blocked approach.",
    "jump_forward": "Use a running jump to cross a visible lip or narrow gap.",
    "bypass_enemy": "Move around a visible character and continue exploring.",
    "follow_route": "Walk into the verified passage.",
    "touch_switch": "Press the verified wall button by approaching it.",
    "shoot_switch": "Shoot the marked shootable button.",
    "board_platform": "Step onto the marked platform and wait for it.",
    "ride_lift": "Stay on the platform while it moves between floors.",
    "wait_door": "Stay at the entrance while the sliding door opens.",
    "collect_item": "Collect the visible supply.",
}
CUES = {
    "advance": "passage",
    "turn_left": "untried",
    "turn_right": "untried",
    "back_up": "backtrack",
    "strafe_left": "untried",
    "strafe_right": "untried",
    "jump_forward": "landing",
    "bypass_enemy": "opponent",
    "ride_lift": "landing",
    "wait_door": "passage",
    **{action: cue for _, action, cue in MARK_ACTION.values()},
}


class LayeredPlayer:
    def close(self):
        self.http.close()

    def choose_preview(self, candidates, context):
        """Select one of the short movements already tested in the background game."""
        criteria = {}
        for index, b in enumerate(candidates):
            label = b["option"].label()
            moved = (
                f"{float((b['delta'] ** 2).sum()) ** 0.5:.0f} units"
                if b["support"] >= 0.35
                else "uncertain"
            )
            criteria[f"move_{index}"] = (
                f"{label}; predicted camera travel {moved}; visible health loss {b['damage']}; ammunition change {b['ammo_gain']}; message {b['notice'] or 'none'}."
            )
            if b.get("onward_preview"):
                criteria[f"move_{index}"] += " A private camera followed this route beyond its first turn."
        started = time.monotonic()
        try:
            token = self.select(
                "next_move", "Select the tested movement that advances this objective.",
                "Playing an unexplored Quake level. Select a move toward the exit. Prefer progress along an untried opening or an actionable switch. " + json.dumps(context),
                criteria,
            )
            if token not in criteria:
                return None
            index = int(token.split("_")[1])
            return {
                "input": candidates[index]["option"].label(),
                "ms": round(1000 * (time.monotonic() - started)),
                "model": self.model,
            }
        except (httpx.HTTPError, ValueError, LookupError, TypeError):
            return None

    def choose(self, recent, navigation):
        decision, _ = self._choose(recent, navigation)
        return decision

    def _choose(self, recent, navigation, frame=None):
        plan = navigation.get("strategy") or {}
        enemy = navigation.get("local_character")
        blocked = set(navigation.get("blocked_inputs", []))
        choices = ["advance", "turn_left", "turn_right"]
        if navigation.get("recover") or plan.get("intent") == "disengage":
            choices = ["back_up", "turn_left", "turn_right"]
        lane = navigation.get("camera_lanes")
        if lane in ("left", "center", "right") and "follow_route" not in blocked:
            choices.insert(0, "follow_route")
        elif lane == "scan":
            choices = ["turn_left", "turn_right", "back_up"]
        if enemy:
            choices.insert(0, "bypass_enemy")
        if plan.get("intent") == "cross":
            choices.insert(0, "jump_forward")
        grounded = navigation.get("grounded")
        if grounded and grounded.get("kind") in MARK_ACTION:
            _, ground_action, _ = MARK_ACTION[grounded["kind"]]
            choices = (
                [ground_action, "back_up", "turn_left"]
                if not enemy
                else ["bypass_enemy", ground_action]
            )
        lesson = navigation.get("movement_lesson")
        guide = navigation.get("prepared_route") or {}
        suggestion = guide.get("suggested")
        if suggestion in CHOICES:
            choices = [suggestion, "back_up"]
            if enemy:
                choices.append("bypass_enemy")
            if grounded and grounded.get("kind") in MARK_ACTION and plan.get("intent") == "interact":
                choices.append(MARK_ACTION[grounded["kind"]][1])
        if lesson:
            choices += ["back_up", "strafe_left", "strafe_right", "turn_left", "turn_right"]
        if frame is not None:
            choices += ["turn_left", "turn_right"]
        choices = [k for k in dict.fromkeys(choices) if k not in blocked] or ["turn_left", "turn_right"]
        last = recent[-1]["action"] if recent else "none"
        state = (
            f"Game: Quake. Objective: {plan.get('objective', 'Explore a passage toward the exit')}. "
            f"Suggested input: {plan.get('next_input', 'none')}. Visible character: {enemy or 'none detected'}. Last input: {last}. "
            f"Verified landmark in the current camera: {(grounded or {}).get('kind', 'none')}. "
            f"Camera lane estimate: {lane or 'unknown'}. Movement outcome: {navigation.get('last_outcome', 'Starting at the entrance')}. "
            f"Untried directions: {', '.join(navigation.get('untried', []))}."
        )
        if navigation.get("mechanism"):
            state += " Door task: " + navigation["mechanism"]["objective"]
        if guide:
            state += " Prepared route: " + guide["objective"]
            if suggestion:
                state += f" Current camera matches the demonstration. Recommended input: {suggestion}."
            else:
                state += " Reacquire this landmark before committing to its move."
        if lesson:
            state += " Movement feedback: " + lesson["advice"]
        if navigation.get("unsuccessful"):
            state += " Failed approaches here: " + ", ".join(navigation["unsuccessful"]) + "."
        if navigation.get("past_traversal"):
            state += " Experience from earlier moves: " + ". ".join(navigation["past_traversal"]) + "."
        hud = navigation.get("hud", {})
        if hud.get("active_ammo") is not None:
            state += f" Visible health {hud.get('visible_hp')}; active ammunition {hud['active_ammo']}."
        if hud.get("game_message"):
            state += " Game notice: " + hud["game_message"]
        start = time.monotonic()
        source = self.source
        sighting = None
        try:
            criteria = {k: CHOICES[k] + (" The current camera matches this demonstrated move." if k == suggestion else "") for k in choices}
            if frame is None:
                instruction = "Choose the input that follows the matched route unless the current approach is blocked." if suggestion else "Choose a useful next input for the Quake player."
                action = self.select("action", instruction, state, criteria)
            else:
                action, sighting = self.select_image(state, criteria, frame)
            if action not in choices:
                raise ValueError("Invalid local input")

        except (httpx.HTTPError, ValueError, LookupError, TypeError):
            # A missing local service must not leave the simulation waiting for an input.
            action = choices[0]
            source = "Local fallback"
            sighting = None
        decision = action, CUES[action], source, round((time.monotonic() - start) * 1000)
        return decision, sighting


class LocalPlayer(LayeredPlayer):
    model = LOCAL_MODEL
    source = "Mac local model"
    label = "Mac · Laya English 421M"

    def __init__(self, url):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username is not None
        ):
            raise ValueError("The local player requires a loopback Ollaya endpoint")
        self.http = httpx.Client(
            base_url=url, timeout=httpx.Timeout(0.18, connect=0.1), trust_env=False
        )

    def select(self, field, instruction, state, choices):
        reply = self.http.post("/v1/systemone", json={
            "model": self.model, "state": state,
            "questions": {field: {"type": "choice", "instructions": instruction, "criteria": choices}},
        })
        reply.raise_for_status()
        return reply.json()["answers"][field]["choice"]


class ModularGemmaPlayer(LayeredPlayer):
    model = CLOUD_MODELS["gemma"]
    source = "Modular Gemma"
    label = "Modular Cloud · Gemma 4 31B"

    def __init__(self, key):
        self.http = httpx.Client(base_url="https://api.modular.com", timeout=4,
                                 headers={"Authorization": "Bearer " + key})

    def select(self, field, instruction, state, choices):
        return self._request(field, instruction, state, choices)[field]

    def choose_with_frame(self, recent, navigation, frame):
        return self._choose(recent, navigation, frame)

    def select_image(self, state, choices, frame):
        instruction = (
            "Choose the next Quake input from the game screenshot and navigation objective. "
            "If a live monster is off-center, turn toward it for another look. "
            "Ignore the HUD, first-person weapon, bodies and lamps when locating a live monster. "
            "Region is its horizontal third in the game frame, or unknown if unconfirmed."
        )
        result = self._request("action", instruction, state, choices, frame)
        if result["sighting"] not in ("live", "fallen", "none", "unclear") or result["region"] not in ("left", "center", "right", "unknown"):
            raise ValueError("Invalid game-frame observation")
        return result["action"], {"sighting": result["sighting"], "region": result["region"] if result["sighting"] == "live" else "unknown"}

    def _request(self, field, instruction, state, choices, frame=None):
        properties = {field: {"type": "string", "enum": list(choices)}}
        content = json.dumps({"state": state, "choices": choices})
        if frame is not None:
            properties.update(
                sighting={"type": "string", "enum": ["live", "fallen", "none", "unclear"]},
                region={"type": "string", "enum": ["left", "center", "right", "unknown"]},
            )
            content = [
                {"type": "text", "text": content},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii")}},
            ]
        schema = {
            "type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False,
        }
        reply = self.http.post("/v1/chat/completions", json={
            "model": self.model, "temperature": 0, "max_tokens": 65 if frame is not None else 48,
            "reasoning": {"enabled": False},
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "quake_input", "strict": True, "schema": schema}},
            "messages": [
                {"role": "system", "content": instruction + " Return only the requested JSON object."},
                {"role": "user", "content": content},
            ],
        })
        reply.raise_for_status()
        content = reply.json()["choices"][0]["message"]["content"]
        return json.loads(content)
