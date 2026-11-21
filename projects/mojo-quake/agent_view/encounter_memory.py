"""Short-term memory for a Quake encounter, measured in game ticks."""

import math

from unoq_bridge import HZ


def screen_yaw(x):
    """Convert a horizontal position in the 90-degree Quake view to relative yaw."""
    return -math.degrees(math.atan((x - 50) / 50))


class EncounterMemory:
    def __init__(self):
        self.health = None
        self.damage = None
        self.sighting = None
        self.shot = None
        self.search_turns = 0
        self.search_side = None
        self.followup_checks = 0

    def observe_health(self, health, tick):
        if health is None:
            return
        if self.health is not None and 0 < health < self.health:
            if (
                not self.search_turns
                or self.damage is None
                or tick - self.damage[0] > 2 * HZ
            ):
                self.search_turns = 3
                self.search_side = None
            self.damage = (tick, self.health, health)
        self.health = health

    def context(self, tick, yaw):
        recent = {}
        if self.damage is not None:
            hit_tick, before, after = self.damage
            if tick - hit_tick <= 2 * HZ:
                recent["recent_hit"] = {
                    "hp_lost": before - after,
                    "ticks_ago": tick - hit_tick,
                    "search_turns_left": self.search_turns,
                    "search_side": self.search_side,
                }
        if self.sighting is not None:
            seen_tick, label, bearing = self.sighting
            if tick - seen_tick <= 2 * HZ:
                recent["last_sighting"] = {
                    "label": label,
                    "ticks_ago": tick - seen_tick,
                    "relative_yaw": round((bearing - yaw + 180) % 360 - 180),
                }
        if self.shot is not None:
            shot_tick, _, outcome = self.shot
            if tick - shot_tick <= 2 * HZ:
                recent["last_shot"] = {
                    "ticks_ago": tick - shot_tick,
                    "outcome": outcome,
                    "checks_left": self.followup_checks,
                }
        return recent

    def react(self, choice, tick, yaw, context):
        """Give a fresh sighting priority and bound searches based on older evidence."""
        label = choice["opponent"]
        if label in ("live_ahead", "live_left", "live_right"):
            x = choice.get("opponent_x")
            offset = (
                screen_yaw(x)
                if x is not None
                else {"live_ahead": 0, "live_left": 34, "live_right": -34}[label]
            )
            self.sighting = (tick, label, (yaw + offset) % 360)
            self.search_turns = 0
            return choice

        shot = context.get("last_shot", {})
        sighting = context.get("last_sighting", {})
        hit = context.get("recent_hit", {})
        bearing = sighting.get("relative_yaw", 0)
        if shot.get("outcome") == "unconfirmed" and shot["checks_left"]:
            action = (
                ("face_left" if bearing > 0 else "face_right")
                if abs(bearing) > 12
                else "check_view"
            )
            reason = "Checking whether the guard survived the last shot."
        elif sighting and (hit.get("search_turns_left") or sighting["ticks_ago"] <= HZ):
            action = (
                ("face_left" if bearing > 0 else "face_right")
                if abs(bearing) > 12
                else "check_view"
            )
            reason = "Checking the last sighting before resuming the route."
        elif hit.get("search_turns_left"):
            # A health drop indicates danger, but gives no attacker bearing.
            side = hit["search_side"]
            if not side:
                side = (
                    "right"
                    if choice["action"] in ("face_right", "turn_right")
                    else "left"
                )
            action = "turn_" + side
            reason = "Scanning after taking damage. The attacker is outside the current view."
        else:
            return choice
        return dict(choice, action=action, encounter_reason=reason)

    def applied(self, decision, tick, kills):
        if decision["action"] == "fire":
            self.shot = (tick, kills, "unconfirmed")
            self.followup_checks = 2
        elif decision.get("encounter_reason"):
            if self.shot and self.shot[2] == "unconfirmed" and self.followup_checks:
                self.followup_checks -= 1
            if self.search_turns:
                self.search_turns -= 1
                if decision["action"] in ("turn_left", "turn_right"):
                    self.search_side = decision["action"].removeprefix("turn_")

    def confirm_kills(self, kills):
        if self.shot is None or self.shot[2] != "unconfirmed":
            return False
        tick, before, _ = self.shot
        if kills is None or before is None or kills <= before:
            return False
        self.shot = (tick, before, "confirmed kill")
        self.followup_checks = self.search_turns = 0
        self.sighting = self.damage = None
        return True
