# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.28,<1", "Pillow>=11,<13", "opencv-python-headless>=4.10,<5"]
# ///
"""Replay known camera turns without inference. Compare tracked and projected x for a marked point."""

import argparse
import json
import math
import time
from pathlib import Path

import cv2
from fast_control import PROJECT, Game, seed_plan, stage
from visual_tracker import FeatureBuffer, FrameBuffer


def probe(binary, media):
    cv2.setNumThreads(1)
    results = []
    for scene in ("ledge", "enemy"):
        for size in (6, -8, 12, -14):
            game = Game(
                binary, media, start_map="start" if scene == "enemy" else "e1m1"
            )
            try:
                before, _ = stage(game, scene)
                point = seed_plan(scene)["vision"][
                    "enemy" if scene == "enemy" else "landing"
                ]
                tick = game.tick
                game.yaw = (game.yaw + size) % 360
                after, _, _ = game.move(4, evaluate=True)
                ideal = 50 + 50 * math.tan(
                    math.atan((point[0] - 50) / 50) + math.radians(size)
                )
                for name, buf in [
                    ("patch", FrameBuffer()),
                    ("features", FeatureBuffer()),
                ]:
                    buf.add(tick, before)
                    track = buf.anchor(
                        tick, point, "enemy" if scene == "enemy" else "surface"
                    )
                    t = time.perf_counter()
                    buf.add(game.tick, after)
                    track.update(buf.frames[-1][1])
                    result = track.point()
                    ms = 1000 * (time.perf_counter() - t)
                    results.append(
                        {
                            "scene": scene,
                            "yaw_delta": size,
                            "method": name,
                            "local_ms": round(ms, 3),
                            "tracked_x_pct": result[0] if result else None,
                            "expected_static_x_pct": round(ideal, 2),
                            "error_px": round(abs(result[0] - ideal) * 3.2, 1)
                            if result
                            else None,
                        }
                    )
            finally:
                game.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media",
        type=Path,
        default=Path.home() / "Library/Application Support/Mojo Quake/media",
    )
    parser.add_argument("--binary", type=Path, default=PROJECT / "build/host/tyr-quake")
    args = parser.parse_args()
    print(json.dumps(probe(args.binary, args.media), indent=2))
