"""Short, camera-triggered movement lessons. Bearings and room history last one attempt."""

import io

import numpy as np
from PIL import Image


def _scene(jpeg):
    with Image.open(io.BytesIO(jpeg)) as image:
        # Exclude the weapon, HUD and console notifications from translation feedback.
        return np.asarray(
            image.convert("L").crop((8, 34, 312, 140)).resize((60, 24)),
            dtype=np.float32,
        )


def _difference(a, b):
    return float(np.abs(a - b).mean())


class MovementLessons:
    def __init__(self, mode):
        self.mode = mode
        self.turns = 0
        self.reset()

    def reset(self):
        self.previous = self.anchor = None
        self.last_tick = None
        self.stationary_ticks = 0
        self.pending = False
        self.detected_tick = None
        self.stall_location = None
        self.next_trigger = 0
        self.landing_until = self.junction_until = -1

    def observe(
        self, jpeg, tick, length, yaw, pitch, forward, side, up, buttons, walking,
        location=None,
    ):
        if self.mode == "off":
            return
        if not walking or forward < 160 or side or up or buttons:
            self.previous = self.anchor = None
            self.stationary_ticks = 0
            self.last_tick = None
            return
        frame = _scene(jpeg)
        steady = (
            self.last_tick == tick - length
            and self.previous is not None
            and abs((yaw - self.heading + 180) % 360 - 180) < 1
            and abs(pitch - self.pitch) < 1
        )
        if (
            steady
            and frame.std() > 5
            and _difference(frame, self.previous) < 2
            and _difference(frame, self.anchor) < 3
        ):
            self.stationary_ticks += length
        else:
            self.stationary_ticks = 0
            self.anchor = frame
        self.previous, self.heading, self.pitch, self.last_tick = (
            frame,
            yaw,
            pitch,
            tick,
        )
        if self.stationary_ticks >= 24 and tick >= self.next_trigger:
            self.pending = True
            self.detected_tick = tick
            self.stall_location = location
            self.next_trigger = tick + 96

    def blocks_walk(self, tick, place, direction):
        return (
            self.mode == "active" and self.stall_location == (place, direction)
            and self.detected_tick is not None and 0 <= tick - self.detected_tick <= 144
        )

    def see_landing(self, tick, marker, notice):
        if self.mode == "off":
            return
        text = (notice or "").lower()
        if (marker or {}).get("kind") == "landing" or (
            "jump" in text and ("up" in text or "across" in text)
        ):
            # A remembered cue licenses a new survey, never aiming at the old image coordinates.
            self.landing_until = tick + 144

    def recovery_due(self, tick):
        return (
            self.mode == "active"
            and self.pending
            and self.detected_tick is not None
            and tick - self.detected_tick <= 36
        )

    def recovery(self, tick, yaw, lane):
        if not self.pending:
            return None
        self.pending = False
        if self.detected_tick is None or tick - self.detected_tick > 36:
            return None
        sign = {"left": 1, "right": -1}.get(lane)
        if sign is None:
            sign = 1 if self.turns % 2 == 0 else -1
        self.turns += 1
        # Median absolute departure angle after slowing in three training-map demos.
        return (yaw + 80 * sign) % 360

    def see_junction(self, tick, exploration):
        samples = exploration.get("sampled_moving_views", 0)
        if samples >= 8 and exploration.get("familiar_moving_views", 0) >= .6 * samples:
            self.junction_until = tick + 144

    def advice(self, tick):
        candidate = self.context(tick)
        if (
            self.mode == "active"
            and candidate
            and candidate["lesson"] in ("release_blocked_forward", "compare_onward_turns")
        ):
            return candidate
        return None

    def context(self, tick):
        if self.mode == "off":
            return None
        if self.detected_tick is not None and tick - self.detected_tick <= 144:
            return {
                "lesson": "release_blocked_forward",
                "observed_tick": self.detected_tick,
                "advice": "Forward input produced almost no translation. Step back and test an open side. Verify translation past the obstruction.",
            }
        if tick <= self.junction_until:
            return {"lesson": "compare_onward_turns",
                    "advice": "Moving views match earlier travel. Preview both departures from the junction and a second move beyond it. Prefer a safe route whose endpoint looks unfamiliar."}
        if tick <= self.landing_until:
            return {
                "lesson": "compare_walk_and_jump",
                "advice": "Inspect both sides for a reachable top surface. Compare a walk and a running jump on the same heading and test for a settled landing with a way onward.",
            }
        return None
