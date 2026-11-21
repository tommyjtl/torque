"""Gemma controllers for pixel observations and bounded Quake inputs."""

import base64
import json
import math
import os
import re

import httpx

VISION_MODEL = "google/gemma-4-31b-it"
CLOUD_MODELS = {
    "gemma": VISION_MODEL,
    "minimax": "MiniMaxAI/MiniMax-M3.1-Flash",
    "qwen": "qwen/qwen3.8-27b",
    "deepseek": "deepseek/deepseek-v4.1-flash-1017",
}
DECISION_MODEL = "gemma4:e4b-mlx"
LEVEL_GOAL = "Find and enter the exit slipgate to complete The Slipgate Complex (E1M1)."
JUMP_RUNUP = 8
JUMP_PRESS = 4
# Duration (72 Hz ticks), forward speed, strafe speed, buttons, relative yaw, relative pitch.
ACTIONS = {
    "jump_back": (32, -280, 0, 0, 0, 0),
    "back_up": (25, -280, 0, 0, 0, 0),
    "turn_around": (12, 0, 0, 0, 180, 0),
    "level_view": (8, 0, 0, 0, 0, 0),
    "advance": (27, 320, 0, 0, 0, 0),
    "advance_fire": (27, 245, 0, 1, 0, 0),
    "fire": (38, 0, 0, 1, 0, 0),
    "aim_fire": (30, 0, 0, 1, 0, 0),
    "bypass_enemy": (27, 190, 230, 0, 0, 0),
    "collect_item": (32, 295, 0, 0, 0, 0),
    "board_platform": (44, 270, 0, 0, 0, 0),
    "ride_lift": (48, 0, 0, 0, 0, 0),
    "wait_door": (50, 0, 0, 0, 0, 0),
    "inspect_panel": (96, 305, 0, 0, 0, 0),
    "touch_switch": (42, 320, 0, 0, 0, 0),
    "shoot_switch": (18, 0, 0, 1, 0, 0),
    "follow_route": (24, 290, 0, 0, 0, 0),
    "turn_left": (12, 0, 0, 0, 32, 0),
    "turn_right": (12, 0, 0, 0, -32, 0),
    "aim_left": (8, 0, 0, 0, 9, 0),
    "aim_right": (8, 0, 0, 0, -9, 0),
    "look_up": (8, 0, 0, 0, 0, -10),
    "look_down": (8, 0, 0, 0, 0, 10),
    "strafe_left": (18, 0, -300, 0, 0, 0),
    "strafe_right": (18, 0, 300, 0, 0, 0),
    "jump_forward": (60, 320, 0, 0, 0, 0),
}
VISION_PROMPT = (
    LEVEL_GOAL
    + """ Describe this Quake frame for the player. Highlight visible exit signs, slipgates,
switches, lifts and passages that could lead onward. Ignore the lower HUD when estimating positions.
Return JSON with these keys: scene (one short factual sentence), enemy (null, or [x,y] for the center of
a clearly visible enemy), route (null, or [x,y] along the best onward path), and landing (null, or [x,y]
on the visible top of a low ledge or the walkable far side of a narrow gap that calls for a running jump).
Look for a lip and usable space above it on the onward path, especially when a jump tutorial message
is on screen. A shelf below a wall panel can be a landing; mark the horizontal top rather than the panel.
Return item (health, armor, ammo, or null) and pickup ([x,y] on that collectible or null).
Only mark a distinct floor pickup; a symbol printed on a wall is scenery.
Return blocker for what currently stops onward movement: none, wall, low_opening, ledge, gap,
closed_door, moving_platform, enemy, or unknown. Choose unknown if there is no visual evidence.
Return platform: null, or [x,y] on the visible horizontal surface of a likely lift or transport pad.
Look for a distinct surface, moving geometry or an activation marking. A wall recess alone is insufficient.
Also return switch: null, or [x,y] at a clearly visible operable button or trigger marked on a wall.
Ordinary wall panels and decorations are not switches. Read visible messages about activation.
Also return clearance for the path directly ahead: walkable, jump_up, jump_across, too_low, too_high,
or unclear. Judge relative height from the visible floor, lip, top surface and space overhead.
A dark slit below a solid panel may be too low to stand in. Darkness alone gives unclear clearance.
For blocked clearance, route may point to a distinct way around; use null if none is visible.
Use null for landing at ordinary doorways, vertical walls, or when the landing surface is hidden.
Coordinates are percentages of the FULL frame from the top left, 0 through 100. Note walls, gaps and
open doors in scene. For example, the center is [50,50] and the bottom right is [100,100].
Return null if a location is uncertain. The centered weapon is the player's own. Describe evidence only."""
)
CUES = {
    "opponent": "Enemy visible in the game frame.",
    "supply": "A useful pickup is visible.",
    "switch": "A visible switch may open the onward route.",
    "passage": "A visible opening offers a route forward.",
    "obstacle": "An obstruction or gap interrupts the route.",
    "stalled": "The recent input produced little visual movement.",
    "backtrack": "Return along a previously traveled connection.",
    "untried": "Try another direction from this place.",
    "hit": "Health dropped on the visible status bar.",
    "clearance": "The visible opening has insufficient clearance.",
    "landing": "A visible landing can be reached with a forward jump.",
    "explore": "The way forward is unclear.",
}
DECISION_PROMPT = (
    LEVEL_GOAL
    + """ Explore onward through doors, lifts and passages. Follow visible exit signs.
Use touch_switch to press a marked switch or shoot_switch when the visual cue calls for a shot.
Use current HUD information. With zero active ammunition, bypass a distant opponent and seek
ammo. collect_item walks to a marked collectible. When health is low favor a visible health pack.
Use recent on-screen game messages to interpret doors, switches and steps near where you read them.
After reloading your own checkpoint, use the recorded failed approach and try another route or tactic.
Defend yourself when threatened or when an enemy blocks progress, then resume exploring.
aim_fire points the shotgun at the reported enemy and fires. follow_route steers towards the
reported opening and walks. When landing is visible, prefer jump_forward to get onto the ledge
or across the gap. It aims toward the landing, builds speed, jumps and keeps running through touchdown.
At a too-low slit or too-high wall, back off or look for a side path. Look down to inspect a lip.
After damage, jump_back retreats while keeping a visible opponent in view; turn_around checks behind
when nothing ahead explains the hit.
board_platform walks onto a visible pad and stops to let it operate; ride_lift stays aboard.
A closed door can respond when approached. A moving platform can carry a player who steps on it
and waits. Wall buttons can respond to touch or a shot. Inspect signs and subsequent frames for
a change; a visible panel or changed image alone does not confirm activation. If an action
failed, use a different approach or inspect a different direction. Use the route memory to avoid failed moves at this place. Prefer an untried way out or backtrack
when trapped. back_up reverses, turn_around faces behind, and level_view points the camera at the
horizon. Choose one allowed input and the cue behind it."""
)


def game_input(action, vision, current_pitch=0):
    ticks, forward, side, buttons, yaw, pitch = ACTIONS[action]
    if action == "level_view":
        pitch = -current_pitch
    target = {
        "aim_fire": "enemy",
        "collect_item": "pickup",
        "touch_switch": "switch",
        "inspect_panel": "panel",
        "shoot_switch": "switch",
        "board_platform": "platform",
        "follow_route": "route",
        "jump_forward": "landing",
    }.get(action)
    if target and vision.get(target) is not None:
        x, y = vision[target]
        # Convert the observation to relative mouse-look at the fixed 90-degree horizontal FOV.
        yaw = -math.degrees(math.atan((x - 50) / 50))
        if action in ("aim_fire", "shoot_switch"):
            pitch = math.degrees(math.atan((y - 50) * 0.015))
    if action == "bypass_enemy":
        enemy = vision.get("enemy")
        side = 230 if enemy and enemy[0] <= 50 else -230
    return ticks, forward, side, buttons, round(yaw, 2), round(pitch, 2)


def input_chunk(action, remaining, controls, frame_ticks):
    """Generate ordinary key holds, including a distinct jump press after takeoff speed builds."""
    chunk = min(remaining, frame_ticks) if remaining else frame_ticks
    if remaining and action == "inspect_panel":
        if remaining <= 28:
            return chunk, (0, 0, 0)
        return min(chunk, remaining - 28), controls
    if remaining and action == "board_platform":
        if remaining <= 20:
            return chunk, (0, 0, 0)
        return min(chunk, remaining - 20), controls
    if remaining and action in ("jump_forward", "jump_back", "evade_and_scan"):
        forward, side, buttons = controls
        elapsed = (36 if action == "evade_and_scan" else ACTIONS[action][0]) - remaining
        if elapsed < JUMP_RUNUP:
            chunk = min(chunk, JUMP_RUNUP - elapsed)
        elif elapsed < JUMP_RUNUP + JUMP_PRESS:
            chunk = min(chunk, JUMP_RUNUP + JUMP_PRESS - elapsed)
            buttons |= 2
        if action == "evade_and_scan" and elapsed >= 28:
            forward = 0
        return chunk, (forward, side, buttons)
    return chunk, controls


def read_key(path, variable="MODULAR_API_KEY"):
    if path:
        for line in path.read_text().splitlines():
            match = re.fullmatch(
                rf"\s*(?:export\s+)?{re.escape(variable)}\s*=\s*(.*?)\s*", line
            )
            if match:
                key = match[1].strip().strip("\"'")
                if key:
                    return key
        raise ValueError(f"The supplied file has no {variable} setting")
    key = os.environ.get(variable)
    if not key:
        raise ValueError(f"Set {variable} or supply a key file")
    return key


def parse_observation(text):
    result, _ = json.JSONDecoder().raw_decode(text[text.index("{") :])
    return observation_fields(result)


def observation_fields(result):
    scene = result["scene"]
    if not isinstance(scene, str) or not scene.strip():
        raise ValueError("Vision returned no scene description")
    observation = {"scene": scene.strip()[:400]}
    if "blocker" in result:
        blocker = result["blocker"]
        observation["blocker"] = (
            blocker
            if blocker
            in (
                "none",
                "wall",
                "low_opening",
                "ledge",
                "gap",
                "closed_door",
                "moving_platform",
                "enemy",
                "unknown",
            )
            else "unknown"
        )
    if "clearance" in result:
        value = result["clearance"]
        observation["clearance"] = (
            value
            if value
            in ("walkable", "jump_up", "jump_across", "too_low", "too_high", "unclear")
            else "unclear"
        )
    if "item" in result:
        item = result["item"]
        observation["item"] = item if item in ("health", "ammo", "armor") else None
    unlocated = []
    markers = ["enemy", "route"]
    markers.extend(
        name for name in ("landing", "switch", "platform", "pickup") if name in result
    )
    for name in markers:
        point = result.get(name)
        if name not in result or (
            point is not None
            and not (
                isinstance(point, list)
                and len(point) == 2
                and all(type(v) in (int, float) and 0 <= v <= 100 for v in point)
            )
        ):
            # The scale of malformed coordinates is ambiguous. Keep the text and
            # the other marker, and exclude this one from mouse-look calculations.
            unlocated.append(name)
            point = None
        observation[name] = point
    if unlocated:
        observation["unlocated"] = unlocated
    return observation


def candidate_inputs(recent, navigation):
    # These constraints are known before the cloud sees the new frame. Jump and
    # follow_route sectors depend on the new landing/route point.
    allowed = [
        a
        for a in ACTIONS
        if a != "inspect_panel"
        and (a != "wait_door" or navigation.get("prepared_route", {}).get("suggested") == a)
        and (
            a not in navigation["blocked_inputs"]
            or a in ("jump_forward", "follow_route")
        )
    ]
    if (
        recent
        and recent[-1]["action"] in ("advance", "advance_fire", "follow_route")
        and recent[-1]["view_change_pct"] < 2
    ):
        allowed = [
            a for a in allowed if a not in ("advance", "advance_fire", "follow_route")
        ]
    if navigation.get("hud", {}).get("active_ammo") == 0:
        allowed = [
            a
            for a in allowed
            if a not in ("aim_fire", "fire", "advance_fire", "shoot_switch")
        ]
    if abs(navigation["pitch"]) < 8 and "level_view" in allowed:
        allowed.remove("level_view")
    if navigation["pitch"] < -38 and "look_up" in allowed:
        allowed.remove("look_up")
    if navigation["pitch"] > 38 and "look_down" in allowed:
        allowed.remove("look_down")
    return allowed


def allowed_inputs(vision, recent, navigation):
    allowed = [
        a
        for a in candidate_inputs(recent, navigation)
        if a not in navigation["blocked_inputs"]
    ]
    if not (vision.get("item") and vision.get("pickup")):
        allowed = [a for a in allowed if a != "collect_item"]
    if not vision.get("enemy"):
        allowed = [a for a in allowed if a != "bypass_enemy"]
    if vision["enemy"] is None and "aim_fire" in allowed:
        allowed.remove("aim_fire")
    if vision["route"] is None and "follow_route" in allowed:
        allowed.remove("follow_route")
    if vision.get("blocker") != "moving_platform" and "ride_lift" in allowed:
        allowed.remove("ride_lift")
    if not vision.get("platform") and "board_platform" in allowed:
        allowed.remove("board_platform")
    if not vision.get("panel") and "inspect_panel" in allowed:
        allowed.remove("inspect_panel")
    if not vision.get("switch"):
        allowed = [a for a in allowed if a not in ("touch_switch", "shoot_switch")]
    landing = vision.get("landing")
    route = vision["route"]
    if (
        landing is not None
        and vision["enemy"] is None
        and (route is None or abs(landing[0] - route[0]) < 18)
    ):
        # Vision marked the onward lane as requiring a jump. Gemma can jump,
        # line up, or back off rather than walking straight into the obstacle.
        allowed = [
            a for a in allowed if a not in ("advance", "advance_fire", "follow_route")
        ]
    if (
        navigation.get("camera_lanes") in ("left", "right")
        and route is not None
        and abs(route[0] - 50) >= 20
        and "follow_route" not in navigation["blocked_inputs"]
        and "follow_route" not in allowed
    ):
        allowed.append("follow_route")
    if vision.get("clearance") in ("too_low", "too_high"):
        blocked = {"advance", "advance_fire"}
        if route is None or abs(route[0] - 50) < 22:
            blocked.add("follow_route")
        if landing is None or abs(landing[0] - 50) < 22:
            blocked.add("jump_forward")
        allowed = [a for a in allowed if a not in blocked]
    if navigation["recover"] and vision["enemy"] is None:
        escapes = [a for a in navigation["escape_options"] if a in allowed]
        if (
            navigation.get("camera_lanes") in ("left", "right")
            and "follow_route" in allowed
        ):
            escapes.append("follow_route")
        if vision.get("landing") is not None and "jump_forward" in allowed:
            escapes.append("jump_forward")
        escapes.extend(
            a
            for a in (
                "touch_switch",
                "shoot_switch",
                "ride_lift",
                "wait_door",
                "board_platform",
                "collect_item",
            )
            if a in allowed
        )
        if escapes:
            return escapes
    return allowed


def validate_choice(action, cue, vision, recent, navigation):
    if action not in allowed_inputs(vision, recent, navigation) or cue not in CUES:
        raise ValueError(f"Unavailable game input or cue: {action!r}, {cue!r}")
    return action, CUES[cue]


def resolve_proposal(proposal, vision, recent, navigation):
    action, cue = proposal
    allowed = allowed_inputs(vision, recent, navigation)
    if action in allowed and isinstance(cue, str) and cue in CUES:
        return action, CUES[cue], "model"
    if (
        navigation.get("hud", {}).get("active_ammo") == 0
        and "bypass_enemy" in allowed
        and action in ("fire", "aim_fire", "advance_fire")
    ):
        return (
            "bypass_enemy",
            "The active ammunition display reads zero; moving around the visible opponent.",
            "HUD reflex",
        )
    # The model may propose a route which its own new observation rules out.
    # Pick one of the validated, non-targeted recovery inputs on this same frame.
    choices = [
        "level_view",
        "back_up",
        "strafe_left",
        "strafe_right",
        "turn_left",
        "turn_right",
        "turn_around",
    ]
    if recent and recent[-1]["action"] in choices:
        previous = recent[-1]["action"]
        choices.remove(previous)
        choices.append(previous)
    replacement = next((a for a in choices if a in allowed), None)
    if replacement is None:
        replacement = next(
            a for a in allowed if a not in ("fire", "aim_fire", "advance_fire")
        )
    return (
        replacement,
        "The proposed input was unavailable; repositioning to inspect another approach.",
        "local recovery",
    )


class Models:
    def __init__(self, key, *, single_call=False, cloud_model=VISION_MODEL):
        self.cloud_model = cloud_model
        self.single_call = single_call
        self.cloud = httpx.Client(
            base_url="https://api.modular.com",
            timeout=25,
            headers={"Authorization": "Bearer " + key},
        )
        self.mac = (
            None
            if single_call
            else httpx.Client(
                base_url="http://127.0.0.1:11434", timeout=45, trust_env=False
            )
        )

    def _read_frame(self, jpeg, prompt, max_tokens, *, reference=None, schema=None):
        url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
        body = {
            "model": self.cloud_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
            "reasoning": {"enabled": False},
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "quake_board_decision",
                    "strict": True,
                    "schema": schema,
                },
            }
        if reference is not None:
            body["messages"][0]["content"].extend([
                {"type": "text", "text": "The second image is the prepared route reference. The first image is the live camera. Return marker coordinates only on the first image."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(reference).decode()}},
            ])
        if self.cloud_model == CLOUD_MODELS["minimax"]:
            body.pop("reasoning")
            body.update(reasoning_effort="low", max_tokens=2048)
        response = self.cloud.post("/v1/chat/completions", json=body)
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        result, _ = json.JSONDecoder().raw_decode(text[text.index("{") :])
        return result

    def observe(self, jpeg):
        return observation_fields(self._read_frame(jpeg, VISION_PROMPT, 150))

    def observe_and_choose(self, jpeg, recent, navigation):
        prompt = (
            VISION_PROMPT
            + "\n"
            + DECISION_PROMPT
            + " Also include action and cue in the same JSON object. Choose one allowed input and one cue. "
            "Use screen targets only when visible. Respect blocked inputs and the escape options during recovery.\n"
            + json.dumps(
                {
                    "actions": candidate_inputs(recent, navigation),
                    "cues": CUES,
                    "recent": recent,
                    "route_memory": navigation,
                },
                separators=(",", ":"),
            )
        )
        result = self._read_frame(jpeg, prompt, 240)
        return observation_fields(result), (result["action"], result["cue"])

    def decide(self, vision, recent, navigation):
        allowed = allowed_inputs(vision, recent, navigation)
        schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": allowed},
                "cue": {"type": "string", "enum": list(CUES)},
            },
            "required": ["action", "cue"],
        }
        body = {
            "model": DECISION_MODEL,
            "think": False,
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0, "num_predict": 36, "num_ctx": 2048},
            "format": schema,
            "messages": [
                {"role": "system", "content": DECISION_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "observation": vision,
                            "recent": recent,
                            "route_memory": navigation,
                            "allowed_inputs": allowed,
                        }
                    ),
                },
            ],
        }
        response = self.mac.post("/api/chat", json=body)
        response.raise_for_status()
        result = json.loads(response.json()["message"]["content"])
        return validate_choice(
            result["action"], result["cue"], vision, recent, navigation
        )

    def close(self):
        self.cloud.close()
        if self.mac is not None:
            self.mac.close()
