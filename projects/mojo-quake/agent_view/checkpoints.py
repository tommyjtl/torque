"""Choose native Quake saves using the player's own observations in this run."""

from collections import Counter

from navigation import sector


class Checkpoints:
    def __init__(self, explore_frontiers=False):
        self.explore_frontiers = explore_frontiers
        self.departures = {}
        self.abandoned = Counter()
        self.last_backtrack = -10000
        self.saved = {}
        self.active = None
        self.deaths = Counter()
        self.failures = {}
        self.reloads = 0
        self.last_operation = -10000
        self.first_direction = None
        self.inspect_again = False
        self.last_scene = ""

    def context(self):
        slot = self.saved.get(self.active)
        if slot is None:
            return {"saves": 0, "reloads": 0}
        return {
            "saves": len(self.saved),
            "reloads": self.reloads,
            "slot": self.active,
            "saved_place": slot["place"] + 1,
            "saved_hp": slot["visible_hp"],
            "previous_attempts": self.deaths[self.active],
            "last_failed_approach": self.failures.get(self.active),
        }

    def departure_context(self):
        if not self.explore_frontiers or not self.inspect_again or self.active is None:
            return None
        counts = self.departures.get(self.active, {})
        return {"slot": self.active, "tried_bearings": [45 * s for s in counts]}

    def backtrack(self, tick, memory, damage, nearby):
        if (not self.explore_frontiers or len(self.saved) < 2 or nearby
                or (damage and tick - damage.last_hit < 6 * 72)
                or tick - self.last_operation < 30 * 72 or tick - self.last_backtrack < 45 * 72):
            return None
        exploration = memory.exploration.summary(tick) if memory.exploration else {}
        samples = exploration.get("sampled_moving_views", 0)
        if (samples < 8 or exploration.get("familiar_moving_views", 0) < .8 * samples
                or exploration.get("seconds_since_new_views", 0) < 60):
            return None
        if getattr(memory.mechanisms, "status", None) == "verify_door":
            return None
        candidates = [n for n in self.saved if n != self.active]
        def promise(slot):
            known = self.departures.get(slot, {})
            return (-(self.abandoned[slot] + self.deaths[slot]), -len(known),
                    min(self.saved[slot].get("visible_hp") or 0, 90), slot)
        slot = max(candidates, key=promise)
        return {"op": "load", "cause": "stalled exploration", "slot": slot,
                "failed_slot": self.active, "failed_direction": self.first_direction,
                "last_scene": self.last_scene, "last_visible_ammo": damage.ammo if damage else None,
                "seconds_since_checkpoint": round((tick-self.last_operation)/72, 1),
                "familiar_views": exploration["familiar_moving_views"], "observations": samples}

    def propose(self, tick, dead, memory, damage, nearby):
        if dead:
            if not self.saved:
                return None
            failed = self.deaths.copy()
            failed[self.active] += 1
            choices = sorted(self.saved, reverse=True)
            slot = next(
                (n for n in choices if failed[n] < 2),
                min(choices, key=lambda n: (failed[n], -n)),
            )
            return {
                "op": "load",
                "slot": slot,
                "failed_slot": self.active,
                "failed_direction": self.first_direction,
                "last_scene": self.last_scene,
                "seconds_since_checkpoint": round((tick - self.last_operation) / 72, 1),
                "last_visible_ammo": damage.ammo if damage else None,
            }
        alternate = self.backtrack(tick, memory, damage, nearby)
        if alternate:
            return alternate
        hp = damage.health if damage else None
        ammo = damage.ammo if damage else None
        if self.saved:
            if hp is None or hp < 45 or ammo is not None and ammo < 4:
                return None
            if nearby or damage and tick - damage.last_hit < 6 * 72:
                return None
            if tick - self.last_operation < 24 * 72:
                return None
            if any(s["place"] == memory.here for s in self.saved.values()):
                return None
            previous = self.saved[self.active]
            progressed = len(memory.places) >= previous["known_views"] + 5
            gained_health = (
                hp >= previous["visible_hp"] + 20
                if previous["visible_hp"] is not None
                else False
            )
            gained_ammo = (
                ammo is not None
                and previous["visible_ammo"] is not None
                and ammo >= previous["visible_ammo"] + 10
            )
            if not (progressed or gained_health or gained_ammo):
                return None
            # Save distinct new views; postpone a save in the middle of a known loop.
            explorer = memory.exploration
            if (
                explorer
                and tick - explorer.last_novel > 24 * 72
                and not (gained_health or gained_ammo)
            ):
                return None
        slot = max(self.saved, default=0) + 1
        return {
            "op": "save",
            "slot": slot,
            "saved_tick": tick,
            "place": memory.here,
            "visible_hp": hp,
            "visible_ammo": ammo,
            "known_views": len(memory.places),
            "landmark": memory.places[memory.here].landmark or self.last_scene,
            "direction": sector(memory.yaw),
        }

    def record(self, operation, tick):
        slot = operation["slot"]
        if operation["op"] == "save":
            self.saved[slot] = operation.copy()
        else:
            failed = operation["failed_slot"]
            if operation.get("cause") == "stalled exploration":
                self.abandoned[failed] += 1
                self.last_backtrack = tick
            elif operation.get("cause") != "visual exit forecast":
                self.deaths[failed] += 1
            self.failures[failed] = {
                "departure_direction": operation.get("failed_direction"),
                "last_scene": operation.get("last_scene", ""),
                "survived_seconds": operation.get("seconds_since_checkpoint"),
                "last_visible_ammo": operation.get("last_visible_ammo"),
            }
            self.reloads += 1
            self.inspect_again = True
        self.active = slot
        self.first_direction = None
        self.last_operation = tick

    def observe_action(self, event, yaw):
        vision = event.get("vision") or {}
        if vision.get("scene"):
            self.last_scene = vision["scene"][:180]
        if (
            self.first_direction is None
            and event.get("ticks")
            and (not self.explore_frontiers or not self.inspect_again or event.get("input_source") == "Own-save lookahead")
            and event.get("action")
            in (
                "walk", "jump", "explore_lane", "curve_left", "curve_right", "clear_corner",
                "advance",
                "advance_fire",
                "follow_route",
                "jump_forward",
                "test_passage",
                "test_ledge",
                "board_platform",
                "touch_switch",
                "collect_item",
            )
        ):
            self.first_direction = sector(event.get("locomotion_bearing", yaw))
            if self.active is not None:
                self.departures.setdefault(self.active, Counter())[self.first_direction] += 1
                if event.get("input_source") == "Own-save lookahead":
                    self.inspect_again = False
        if event.get("checkpoint_inspection"):
            self.inspect_again = False

    def inspect(self, memory, action):
        if not self.inspect_again:
            return None
        self.inspect_again = False
        if action in (
            "aim_fire",
            "bypass_enemy",
            "collect_item",
            "shoot_switch",
            "touch_switch",
        ):
            return None
        # Look to a different side on a retry before committing to the same departure.
        failed = self.failures.get(self.active) or {}
        direction = failed.get("departure_direction")
        if direction is None or direction != sector(memory.yaw):
            return None
        return "turn_left" if self.deaths[self.active] % 2 else "turn_right"


def checkpoint_operation(game, op):
    """Use the same native operation in play, continuation and video replay."""
    slot = op["slot"]
    if op["op"] == "save":
        actual = game.save_checkpoint(slot)
    elif op["op"] == "load":
        actual = game.load_checkpoint(slot)
    else:
        raise ValueError("Unknown recorded checkpoint operation")
    if "state_hash" in op and actual["state_hash"] != op["state_hash"]:
        raise ValueError("Checkpoint gameplay hash differs from original")
    return actual


def relocate(memory, point, jpeg, game):
    # Keep learned connections and failed actions. A load itself is not a walked edge.
    memory.here = point["place"]
    memory.pending = memory.entry = None
    memory.driving = False
    memory.turns = memory.stalls = 0
    memory.path.clear()
    memory.path.append(memory.here)
    memory.last_sample = -100
    memory.yaw = (game.yaw - (memory.origin_yaw or 0)) % 360
    memory.pitch = game.pitch
    memory.intention = (None, None)
    memory.character = None
    memory.mechanisms.after_load()
    if memory.lane_sense:
        memory.lane_sense.reset()
    if memory.panels:
        memory.panels.candidate = memory.panels.bearing = None
        memory.panels.first_seen = memory.panels.last_seen = -1000
    if memory.character_track:
        memory.character_track.anchor = None
        memory.character_track.poses.views.clear()
        memory.character_track.last_rejection = None
    if memory.exploration:
        ex = memory.exploration
        ex.active = ex.after_recovery = False
        ex.survey = ex.boundary = ex.departure_reference = None
        ex.departure_views.clear()
        ex.recent_views.clear()
        ex.fresh_streak = ex.failed_departures = 0
        ex.samples.clear()
        ex.last_novel = ex.last_recovery = game.tick
    memory.track(jpeg, game.tick, game.yaw, game.pitch)
    memory.last_outcome = f"Restored the agent's own checkpoint at P{memory.here + 1}."
