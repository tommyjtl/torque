import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from game import Game
from hud import HealthHUD
from lookahead import (
    MotionStream,
    Option,
    PreviewSearch,
    fingerprint,
    panorama,
    render_rows,
)

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "build/host/tyr-quake"
MEDIA = Path.home() / "Library/Application Support/Mojo Quake/media"


class PreviewTests(unittest.TestCase):
    def test_live_chunks_exactly_preserve_preview_inputs(self):
        for kind in (
            "walk",
            "jump",
            "surface",
            "dive",
            "board",
            "test_control",
            "curve_left",
            "climb_out",
            "open_door",
            "ride",
        ):
            rows = Option(310, kind, 96, -4).rows(45, 5)
            stream = MotionStream(rows)
            actual = []
            while stream.index < len(rows):
                n, *inputs = stream.next(4)
                actual.extend([inputs] * n)
            self.assertEqual(actual, [list(r[1:]) for r in rows for _ in range(r[0])])

    def test_held_direction_preserves_live_camera_refreshes(self):
        class Camera:
            def __init__(self):
                self.ticks = []

            def frame(self, ticks, *controls):
                self.ticks.append(ticks)
                return len(self.ticks)

        camera = Camera()
        rows = Option(0, duration=80).rows(0, 0)
        self.assertEqual(render_rows(camera, rows), 20)
        self.assertEqual(camera.ticks, [4] * 20)

    @unittest.skipUnless(
        BINARY.is_file() and (MEDIA / "id1/pak0.pak").is_file(),
        "requires native game and original media",
    )
    def test_branch_from_own_save_isolated_rewind_and_camera_match(self):
        game = Game(BINARY, MEDIA)
        self.addCleanup(game.close)
        image, state, _ = game.move(24, evaluate=True)
        self.assertFalse(HealthHUD(MEDIA / "id1/pak0.pak").completed(image))
        source = game.preview_source()
        self.assertEqual(game.slots, {})
        with source.open_camera() as camera:
            self.assertNotEqual(camera.pipe.process.pid, game.pipe.process.pid)
            self.assertEqual(camera.pipe.state()["hash"], state["hash"])
            camera.frame(2, 0, 0, 0, 0, 0)
            camera.pin()
            base = camera.pipe.state()["hash"]
            panorama(camera)
            self.assertEqual(camera.pipe.state()["hash"], base)
            rows = Option(90).rows(0, 0)
            render_rows(camera, rows)
            endpoint = camera.pipe.state()["hash"]
            with camera.endpoint():
                camera.frame(6, 0, 0, 160, 90, 0)
                camera.rewind()
                self.assertEqual(camera.pipe.state()["hash"], endpoint)
            camera.rewind()
            render_rows(camera, rows)
            self.assertEqual(camera.pipe.state()["hash"], endpoint)
            self.assertEqual(game.tick, 24)
            self.assertEqual(game.pipe.state()["hash"], state["hash"])
            other = Game(BINARY, MEDIA)
            try:
                other.move(24)
                with self.assertRaisesRegex(ValueError, "this run"):
                    camera.rebase(other.preview_source())
            finally:
                other.close()

        f = Future()
        search = PreviewSearch(None)
        self.addCleanup(search.close)
        # A different live picture at exactly the forecast tick must also reject the result.
        f.set_result({"anchor": 255 - fingerprint(image), "latency_ms": 25})
        search.job = (
            f,
            {"handoff_tick": 24, "handoff_yaw": game.yaw, "handoff_pitch": game.pitch},
            search.generation,
        )
        self.assertIsNone(search.take(image, game))
        self.assertEqual(search.last_offer["status"], "Expired")

    @unittest.skipUnless(
        BINARY.is_file() and (MEDIA / "id1/pak0.pak").is_file(),
        "requires native game and media",
    )
    def test_preview_recovers_from_a_closed_shadow_with_live_game_intact(self):
        game = Game(BINARY, MEDIA)
        self.addCleanup(game.close)
        _, start, _ = game.move(24, evaluate=True)
        source = game.preview_source()
        search = PreviewSearch(HealthHUD(MEDIA / "id1/pak0.pak"))
        self.addCleanup(search.close)
        search.camera = source.open_camera()
        previous_pid = search.camera.pipe.process.pid
        search.camera.pipe.close()
        search.choices = lambda yaw, serial, views: [Option(yaw, duration=24)]
        result = search._forecast(
            source,
            Option(game.yaw, duration=24).rows(game.yaw, 0),
            1,
            {"frontier_inputs": [Option(40, duration=24)]},
        )
        self.assertEqual(len(result["branches"]), 2)
        self.assertNotEqual(previous_pid, search.camera.pipe.process.pid)
        self.assertEqual(game.pipe.state()["hash"], start["hash"])
        self.assertEqual(game.tick, 24)

    def test_invalidated_inflight_search_cannot_score_a_later_life(self):
        search = PreviewSearch(None)
        self.addCleanup(search.close)
        job = Future()
        job.set_running_or_notify_cancel()
        search.job = job, {"handoff_tick": 100}, search.generation
        search.invalidate(relocated=True)
        job.set_result(None)
        self.assertIsNone(search.take(b"", SimpleNamespace(tick=10)))
        self.assertIsNone(search.job)
        self.assertFalse(search.book.rooms)


class OnwardPlanTests(unittest.TestCase):
    def test_plan_executes_and_settles_its_two_relative_moves(self):
        from lookahead import Option
        next_move = Option(120, "walk", 70)
        root = Option(40, "jump", 54, onward=(next_move,))
        first = Option(40, "jump", 54).rows(260, -12)
        expected = first + [(12, 0, 0, 0, 40, 0, 0)] + next_move.rows(40, 0)
        self.assertEqual(root.rows(260, -12), expected)
        self.assertIn("then", root.label())


class VisualFrontierTests(unittest.TestCase):
    def test_picture_index_separates_visible_inventory_stages(self):
        import numpy as np
        from visual_frontier import PictureIndex
        rng = np.random.default_rng(51)
        index = PictureIndex(rng)
        picture = rng.normal(size=(4,96)).astype(np.float32)
        _,_,codes = index.find(picture, 0)
        self.assertEqual(index.add(picture, codes, 0), 0)
        self.assertEqual(index.find(picture,0)[:2], (0,0.))
        self.assertIsNone(index.find(picture,1)[0])

    def test_a_visual_plan_can_only_request_its_own_current_slot(self):
        from visual_frontier import VisualFrontier
        from lookahead import Option
        advisor = VisualFrontier(None, Option)
        self.assertIsNone(advisor.root_request(50,{1}))
        advisor.win = {"slot":3,"depth":4}
        self.assertIsNone(advisor.root_request(50,{1}))
        self.assertEqual(advisor.root_request(50,{1,3}),3)
        advisor.restored(3,50)
        self.assertIsNone(advisor.root_request(70,{1,3}))
        advisor.close()


class SearchSupersessionTests(unittest.TestCase):
    def test_running_stale_job_releases_handoff_for_the_new_camera_source(self):
        from concurrent.futures import Future
        from lookahead import PreviewSearch
        search = PreviewSearch(None)
        self.addCleanup(search.close)
        job = Future()
        job.set_running_or_notify_cancel()
        old = search.generation
        search.job = job, {"handoff_tick": 200}, old
        search.invalidate()
        self.assertIsNone(search.job)
        self.assertNotEqual(search.generation, old)
        self.assertFalse(search.handoff_pending(208))
        job.set_result(None)

    def test_a_blocked_door_message_does_not_advance_the_visual_archive(self):
        from visual_frontier import VisualFrontier
        self.assertEqual(VisualFrontier.milestone("This door opens elsewhere..."),0)
        self.assertEqual(VisualFrontier.milestone("You need the gold key"),0)
        self.assertNotEqual(VisualFrontier.milestone("Only 1 more to go..."),0)
        self.assertNotEqual(VisualFrontier.milestone("Sequence completed!"),0)
