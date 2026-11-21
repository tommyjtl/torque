# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python-headless>=4.10,<5", "numpy>=1.26,<3", "Pillow>=11,<13"]
# ///
"""Build an RGB first-person weapon profile from the player's local Quake media."""

import argparse
import io
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "agent_view"))
from game import Game
from weapon_poses import SIZE, small_gray


def playing_area(jpeg):
    with Image.open(io.BytesIO(jpeg)) as frame:
        return np.asarray(frame.convert("RGB"))[:192].copy()


def foreground_pose(shown, hidden):
    world = playing_area(shown)
    difference = np.abs(
        world.astype(np.int16) - playing_area(hidden).astype(np.int16)
    ).max(axis=2)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    changed = cv2.morphologyEx(
        (difference > 17).astype(np.uint8), cv2.MORPH_CLOSE, kernel
    )
    count, components, stats, _ = cv2.connectedComponentsWithStats(changed, 8)
    # The held weapon enters the playing area from the bottom or a side.
    visible = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area > 50 and (y + h >= 180 or x < 6 or x + w > 314):
            visible.append(index)
    if not visible:
        return None
    mask = np.isin(components, visible).astype(np.uint8) * 255
    mask = cv2.resize(mask, SIZE, interpolation=cv2.INTER_AREA) > 178
    if not 15 <= mask.sum() <= 1100:
        return None
    return mask, small_gray(world).astype(np.uint8)


def already_covered(mask, masks):
    area = int(mask.sum())
    for previous in masks:
        if abs(int(previous.sum()) - area) <= area * 0.10:
            union = np.count_nonzero(previous | mask)
            if np.count_nonzero(previous & mask) / union > 0.91:
                return True
    return False


def calibrate(binary, media, gpu=False):
    masks, textures = [], []
    for run in range(8):
        with ExitStack() as cleanup:
            cameras = []
            for shown in (True, False):
                game = Game(binary, media, gpu, start_map="start", show_weapon=shown)
                cleanup.callback(game.close)
                cameras.append(game)
            for sample in range(135):
                frames, states = [], []
                weapon = (1 if run % 4 else 2) if sample == 1 else 0
                for game in cameras:
                    game.yaw = (run * 43 + sample * 3.75) % 360
                    game.pitch = (run % 5 - 2) * 6
                    image, state, _ = game.move(
                        4 if sample else 24,
                        180 if run >= 4 and (sample // 10) % 2 == 0 else 0,
                        buttons=int(5 <= sample % 48 < 42),
                        impulse=weapon,
                        evaluate=True,
                    )
                    frames.append(image)
                    states.append(state)
                if states[0]["hash"] != states[1]["hash"]:
                    raise RuntimeError("Calibration cameras diverged")
                if states[0]["map"] != "start" or int(states[0]["hp"]) <= 0:
                    break
                pose = foreground_pose(*frames)
                if pose is not None and not already_covered(pose[0], masks):
                    masks.append(pose[0])
                    textures.append(pose[1])
    if not masks:
        raise RuntimeError("No visible weapon poses were captured")
    return np.asarray(masks), np.asarray(textures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=PROJECT / "build/host/tyr-quake")
    parser.add_argument(
        "--media",
        type=Path,
        default=Path.home() / "Library/Application Support/Mojo Quake/media",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--gpu", action="store_true", help="Use with a matching OpenGL game binary"
    )
    args = parser.parse_args()
    masks, textures = calibrate(args.binary.resolve(), args.media.resolve(), args.gpu)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=args.output.parent, suffix=".npz", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        np.savez_compressed(temporary, masks=masks, gray=textures)
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Saved {len(masks)} observed weapon poses to {args.output}")


if __name__ == "__main__":
    main()
