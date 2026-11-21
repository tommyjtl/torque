"""Image-to-action adapter for TypeSafe Jev in the Quake observatory."""

import base64
import io
import math
import time
import uuid

import httpx
import numpy as np
from PIL import Image

from floor_motion import FloorMotion
from lookahead import Option, panorama, render_rows, room_distances
from models import LEVEL_GOAL

MODEL = "jev-1.14.0"
AIM_CONFIDENCE = 0.50
MOVES = {
    "advance": "Walk forward through the visible passage.",
    "back_up": "Back away from a close obstruction.",
    "turn_left": "Turn left to inspect a different passage.",
    "turn_right": "Turn right to inspect a different passage.",
    "strafe_left": "Step left around an obstacle.",
    "strafe_right": "Step right around an obstacle.",
    "aim_fire": "Aim at and fire at a clearly visible living opponent.",
    "jump_left": "Test a running jump toward a visible landing 30 degrees to the left.",
    "jump_forward": "Test a running jump straight ahead toward a visible landing.",
    "jump_right": "Test a running jump toward a visible landing 30 degrees to the right.",
}
TARGETS = {
    "live": "A living opponent is visible.",
    "fallen": "Only a fallen opponent is visible.",
    "none": "No opponent is clearly visible.",
}
CUES = {
    "wall": "An obstructing wall.",
    "opening": "A traversable opening.",
    "enemy": "A living opponent.",
    "ledge": "A possible raised landing or gap.",
    "unclear": "The view is ambiguous.",
}
JUMP_TURN = {"jump_left": 30, "jump_forward": 0, "jump_right": -30}


def camera_image(jpeg):
    with Image.open(io.BytesIO(jpeg)) as image:
        buffer = io.BytesIO()
        image.convert("RGB").resize((384, 288), Image.Resampling.BILINEAR).save(
            buffer, "JPEG", quality=90
        )
        return buffer.getvalue()


def confidence(answer):
    value = answer["confidence"]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("Invalid confidence in Jev response")
    return value


def decode(answers):
    choice = answers["action"]["choice"]
    target = answers["target"]["choice"]
    cue = answers["cue"]["choice"]
    if choice not in MOVES or target not in TARGETS or cue not in CUES:
        raise ValueError("Jev returned an unknown choice")
    response = {
        "proposed": choice,
        "action_confidence": confidence(answers["action"]),
        "target": target,
        "target_confidence": confidence(answers["target"]),
        "cue": cue,
        "box_confidence": confidence(answers["aim"]),
        "box": None,
    }
    box = answers["aim"]["box"]
    coords = [box[key] for key in ("left", "top", "right", "bottom")]
    if all(
        type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in coords
    ):
        left, top, right, bottom = coords
        if (
            target == "live"
            and left < right
            and top < bottom
            and (top + bottom) / 2 < 0.8
            and response["box_confidence"] >= AIM_CONFIDENCE
        ):
            response["box"] = dict(zip(("left", "top", "right", "bottom"), coords))
    return response


def check_jump(source, turn, hud):
    """Compare equal-heading walk/jump outcomes and check the next step using only pictures."""
    if source is None or hud is None:
        return False, "No private camera was available."
    heading = (source.yaw + turn) % 360
    with source.open_camera() as camera:
        camera.pin()
        initial_hp = hud.read(camera.glance(source.yaw, source.pitch))
        views = []
        for kind in ("walk", "jump"):
            camera.rewind()
            render_rows(
                camera, Option(heading, kind, 72).rows(source.yaw, source.pitch)
            )
            settled = camera.frame(12, 0, 0, 0, heading, 0, 0)
            if hud.completed(settled):
                return kind == "jump", "The private camera saw the completion screen."
            views.append(panorama(camera)[0])
        hp = hud.read(settled)
        if initial_hp is None or hp is None or hp <= 0 or hp < initial_hp:
            return False, "The preview could not confirm a safe landing."
        difference = float(room_distances(np.asarray([views[0]]), views[1])[0])
        if difference < 8:
            return False, "Walking and jumping ended in similar views."
        end, delta, support, _ = FloorMotion().traverse(
            camera, Option(heading, "walk", 36), heading, 0
        )
        end_hp = hud.read(end)
        if (
            end_hp is not None
            and end_hp >= hp
            and support >= 0.45
            and np.linalg.norm(delta) >= 48
        ):
            return True, "The jump reached a distinct view with a safe onward step."
        return False, "The preview could not confirm enough onward movement."


class JevPlayer:
    cloud_model = MODEL
    single_call = True

    def __init__(self, key):
        self.client = httpx.Client(
            base_url="https://api.typesafe.ai",
            timeout=6.0,
            follow_redirects=False,
            headers={
                "Authorization": "Bearer " + key,
                "TypeSafe-Danger-Zone-Images": "true",
            },
        )

    def choose(self, image, recent, navigation, source=None, hud=None):
        reference = str(uuid.uuid4())
        state = {
            "camera": reference,
            "objective": LEVEL_GOAL,
            "planner": navigation.get("strategy"),
            "recent_inputs": recent,
            "navigation_hint": navigation.get("hint"),
            "visible_hud": navigation.get("hud"),
            "lessons": navigation.get("past_traversal", []),
        }
        body = {
            "model": MODEL,
            "state": state,
            "assets": {
                reference: {
                    "type": "image",
                    "format": "jpg",
                    "data_base64": base64.b64encode(image).decode("ascii"),
                }
            },
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": "Choose one next game input from this current frame. Engage clearly living opponents. Use the planner objective and recent movement outcomes to explore.",
                    "criteria": MOVES,
                },
                "target": {
                    "type": "choice",
                    "instructions": "Classify visible opponents in the camera. Exclude the weapon and HUD portraits.",
                    "criteria": TARGETS,
                },
                "cue": {
                    "type": "choice",
                    "instructions": "Which visual cue most affects the next move?",
                    "criteria": CUES,
                },
                "aim": {
                    "type": "box",
                    "instructions": "Locate the closest clearly living opponent. Exclude corpses, the HUD and the player's weapon.",
                },
            },
        }
        start = time.monotonic()
        reply = self.client.post("/v1/systemone", json=body)
        reply.raise_for_status()
        data = reply.json()
        result = decode(data["answers"])
        result["api_ms"] = round((time.monotonic() - start) * 1000)
        result["model"] = data.get("model") or MODEL
        action = result["proposed"]
        box = result["box"]
        point = (
            [50 * (box["left"] + box["right"]), 50 * (box["top"] + box["bottom"])]
            if box
            else None
        )
        vision = {
            "scene": f"Jev identified {result['cue']} as the movement cue. Opponent classification: {result['target']}.",
            "enemy": point,
            "route": None,
            "landing": None,
            "jev": result,
        }
        reason = MOVES[action]
        if action == "aim_fire" and (
            not box or (navigation.get("hud") or {}).get("active_ammo") == 0
        ):
            action, reason = (
                "hold",
                "Fire withheld: a living target, a reliable aim box and available ammo are required.",
            )
        elif action in JUMP_TURN:
            ok, detail = check_jump(source, JUMP_TURN[action], hud)
            result["preview"] = {"approved": ok, "detail": detail}
            reason = detail
            action = "jump_forward" if ok else "hold"
        return vision, (action, reason)

    def close(self):
        self.client.close()
