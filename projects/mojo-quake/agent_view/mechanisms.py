"""Remember an unresolved door from the player's visible game messages."""

import re
from collections import deque


class MechanismMemory:
    def __init__(self):
        self.door = None
        self.status = None
        self.history = deque(maxlen=4)
        self.last_notice = -10000
        self.last_departure = -10000
        self.new_contact = False
        self.return_by = 0
        self.last_route = None
        self.route_key = None
        self.tests = 0
        self.unsuccessful_returns = 0

    def see_notice(self, text, tick, place, heading, landmark):
        if not text:
            return False
        words = " ".join(text.lower().split())
        remote = bool(re.search(r"door.*(?:opens|opened|unlocks).*elsewhere", words))
        key = re.search(r"(?:need|requires?).{0,22}(silver|gold).{0,8}key", words)
        if not (remote or key):
            return False
        fresh = tick - self.last_notice > 3 * 72
        self.last_notice = tick
        if not fresh:
            return False
        if self.status == "verify_door":
            self.unsuccessful_returns += 1
            self.history.append(
                "The locked-door message appeared again after the last control test."
            )
        self.door = {
            "place": place,
            "heading": heading,
            "notice": text,
            "landmark": landmark[:140],
            "key": key[1] if key else None,
        }
        self.status = (
            "find_key"
            if key
            else (
                "explore_routes" if self.unsuccessful_returns >= 2 else "find_control"
            )
        )
        self.new_contact = True
        self.route_key = None
        return True

    def tested(self, event, tick):
        if not self.door or event.get("note") or not event.get("ticks"):
            return
        action = event.get("action")
        preview = event.get("lookahead") or {}
        mark = (preview.get("panorama_plan") or {}).get("kind")
        best = (preview.get("alternatives") or [{}])[0]
        if "marked_input" in best and not best["marked_input"]:
            return
        if action == "test_control" and mark in ("shoot_button", "touch_button"):
            action = "shoot_switch"
        elif action == "board" and mark == "touch_button":
            action = "touch_switch"
        if action not in ("inspect_panel", "touch_switch", "shoot_switch"):
            return
        if self.status == "find_key":
            return
        self.tests += 1
        self.history.append(
            f"Tested a visible control with {action.replace('_', ' ')} at step {event['seq']}. Its effect still needs checking."
        )
        effect = best.get("interaction") or {}
        if self.unsuccessful_returns >= 2 and not effect.get("localized"):
            self.status = "explore_routes"
            self.history.append("Keep this door in memory and explore other passages.")
            return
        self.status = "verify_door"
        self.return_by = tick + 40 * 72
        self.route_key = None

    def after_load(self):
        if self.door:
            self.status = "find_key" if self.door["key"] else "find_control"
            self.history.append(
                "A save was restored. Check the current state of earlier mechanisms."
            )
        self.new_contact = False
        self.route_key = None

    def departure(self, tick):
        if not self.new_contact or tick - self.last_departure < 6 * 72:
            return False
        self.new_contact = False
        self.last_departure = tick
        return True

    def direction(self, memory, tick):
        if self.status != "verify_door":
            return None
        if tick > self.return_by:
            self.status = "find_control"
            return None
        target = self.door["place"]
        if not 0 <= target < len(memory.places):
            return None
        if memory.here == target:
            return self.door["heading"]
        cache = (memory.here, target, len(memory.visited_edges))
        if cache == self.route_key:
            return self.last_route
        reverse = {}
        for origin, place in enumerate(memory.places):
            for heading, dest in place.exits.items():
                reverse.setdefault(dest, []).append(((heading + 4) % 8, origin))
        queue = deque([(memory.here, None)])
        seen = {memory.here}
        self.last_route = None
        while queue:
            node, first = queue.popleft()
            for k, dest in [*memory.places[node].exits.items(), *reverse.get(node, ())]:
                if dest in seen or memory.places[node].failures[k, "walk"] >= 2:
                    continue
                step = k if first is None else first
                if dest == target:
                    self.last_route = step
                    queue.clear()
                    break
                seen.add(dest)
                queue.append((dest, step))
        self.route_key = cache
        return self.last_route

    def context(self):
        if not self.door:
            return None
        objective = {
            "find_control": "Explore an untried passage and watch for a control for this door.",
            "explore_routes": "Explore a different route toward the exit. Recheck the door when new evidence points to it.",
            "find_key": "Find the key requested at the door.",
            "verify_door": "Revisit the door and test whether the control opened it.",
        }
        return {
            "status": self.status,
            "objective": objective[self.status],
            "notice": self.door["notice"],
            "door_place": f"P{self.door['place'] + 1}",
            "landmark": self.door["landmark"],
            "tested_controls": self.tests,
            "recent_evidence": list(self.history),
        }
