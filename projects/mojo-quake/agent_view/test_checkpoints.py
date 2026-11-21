import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from checkpoints import Checkpoints, checkpoint_operation, relocate
from game import Game
from navigation import Place, RouteMemory
from observatory import session_outcome

PROJECT = Path(__file__).resolve().parents[1]
MEDIA = Path.home() / "Library/Application Support/Mojo Quake/media"
BINARY = PROJECT / "build/host/tyr-quake"


class CheckpointTests(unittest.TestCase):
    def test_safe_places_and_alternative_after_repeated_death(self):
        memory = RouteMemory()
        d = SimpleNamespace(health=100, ammo=25, last_hit=-10000)
        book = Checkpoints()
        initial = book.propose(24, False, memory, d, None)
        book.record(initial, 28)
        self.assertEqual(initial["slot"], 1)
        memory.places.extend(Place(i, 0) for i in range(5))
        memory.here = 5
        d.last_hit = 1800
        self.assertIsNone(book.propose(1900, False, memory, d, None))
        d.last_hit = -10000
        next_save = book.propose(1900, False, memory, d, None)
        self.assertEqual(next_save["place"], 5)
        book.record(next_save, 1904)
        for i, wanted in enumerate((2, 1)):
            book.first_direction = 2
            op = book.propose(2500 + 500 * i, True, memory, d, None)
            self.assertEqual(op["slot"], wanted)
            book.record(op, 2504 + 500 * i)
        self.assertEqual(book.deaths[2], 2)
        self.assertEqual(book.reloads, 2)
        self.assertEqual(book.failures[2]["departure_direction"], 2)

    def test_death_does_not_count_as_completion(self):
        state = {"map": "e1m1", "hp": "0", "intermission": "0"}
        book = Checkpoints()
        self.assertEqual(session_outcome(state, 4, None, book), "Player died")
        book.saved[1] = {"slot": 1}
        self.assertIsNone(session_outcome(state, 4, None, book))
        self.assertEqual(session_outcome(state, 4, 4, book), "Step limit reached")
        self.assertEqual(
            session_outcome(dict(state, hp="29", intermission="1"), 4, None, book),
            "Level complete",
        )


@unittest.skipUnless(
    BINARY.is_file() and (MEDIA / "id1/pak0.pak").is_file(),
    "Native game and local Quake media",
)
class NativeSaveTests(unittest.TestCase):
    def test_own_save_restores_and_replays_the_same_gameplay(self):
        g = Game(BINARY, MEDIA)
        self.addCleanup(g.close)
        _, state, _ = g.move(24, evaluate=True)
        op = {"op": "save", "slot": 1}
        receipt = checkpoint_operation(g, op)
        self.assertEqual(receipt["state_hash"], state["hash"])
        with tempfile.TemporaryDirectory() as temp:
            g.archive_checkpoint(1, Path(temp))
            self.assertTrue((Path(temp) / "agent_000001.sav").is_file())
        jpeg, next_state, _ = g.move(32, 320, evaluate=True)
        g.yaw = 250
        g.move(12, 240)
        with self.assertRaises(ValueError):
            g.load_checkpoint(8)
        self.assertEqual(g.load_checkpoint(1), receipt)
        _, again, _ = g.move(32, 320, evaluate=True)
        self.assertEqual(g.tick, 100)
        self.assertEqual(next_state["hash"], again["hash"])
        memory = RouteMemory()
        memory.track(jpeg, g.tick, g.yaw, g.pitch)
        memory.places.append(Place(0, 1))
        memory.places[0].exits[2] = 1
        edges = copy.deepcopy(memory.places[0].exits)
        relocate(memory, {"place": 0}, jpeg, g)
        self.assertEqual(memory.places[0].exits, edges)

    def test_rejects_an_altered_save_without_switching_the_live_game(self):
        g = Game(BINARY, MEDIA)
        self.addCleanup(g.close)
        g.move(24)
        g.save_checkpoint(1)
        _, before, _ = g.move(14, 210, evaluate=True)
        path = g.slots[1][-1]
        path.write_bytes(path.read_bytes()[:-7])
        with self.assertRaisesRegex(ValueError, "save file changed"):
            g.load_checkpoint(1)
        self.assertEqual(g.pipe.state()["hash"], before["hash"])


class FrontierSaveTests(unittest.TestCase):
    def test_only_prolonged_familiar_travel_restores_an_own_save_and_changes_its_departure(self):
        from types import SimpleNamespace
        from checkpoints import Checkpoints
        book = Checkpoints(explore_frontiers=True)
        for slot in (1, 2):
            book.record({"op":"save", "slot":slot, "place":slot, "known_views":slot*7, "visible_hp":70},slot*100)
            book.observe_action({"ticks":80,"action":"walk","input_source":"Own-save lookahead","locomotion_bearing":90},0)
        summary = {"seconds_since_new_views":75,"sampled_moving_views":12,"familiar_moving_views":11}
        memory = SimpleNamespace(exploration=SimpleNamespace(summary=lambda tick:summary),
                                 mechanisms=SimpleNamespace(status=None))
        self.assertIsNone(book.backtrack(7200,memory,None,True))
        summary["familiar_moving_views"] = 2
        self.assertIsNone(book.backtrack(7200,memory,None,False))
        summary["familiar_moving_views"] = 11
        op=book.backtrack(7200,memory,None,False)
        self.assertEqual((op["op"],op["slot"],op["cause"]),("load",1,"stalled exploration"))
        book.record(op,7200)
        self.assertEqual(book.deaths[2],0)
        self.assertEqual(book.abandoned[2],1)
        self.assertEqual(book.departure_context(),{"slot":1,"tried_bearings":[90]})
        self.assertIsNone(book.backtrack(7300,memory,None,False))
