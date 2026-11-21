"""Check optional local soundtrack playback without changing the player's media or speaker."""
import argparse
from array import array
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import wave


OUTPUT_RATE = 48000
LEFT_HZ = 431
RIGHT_HZ = 739


def write_track(path):
    rate = 22050
    with wave.open(str(path), "wb") as file:
        file.setparams((2, 2, rate, 0, "NONE", "PCM"))
        pcm = bytearray()
        for frame in range(6 * rate):
            phase = 2 * math.pi * frame / rate
            pcm.extend(struct.pack("<hh", round(9000 * math.sin(phase * LEFT_HZ)),
                                   round(9000 * math.sin(phase * RIGHT_HZ))))
        file.writeframes(pcm)


def tone_level(channel, frequency):
    phase = 2 * math.pi * frequency / OUTPUT_RATE
    real = sum(value * math.cos(phase * i) for i, value in enumerate(channel))
    imag = sum(value * math.sin(phase * i) for i, value in enumerate(channel))
    return 2 * math.hypot(real, imag) / len(channel)


def verify(binary, pak):
    with tempfile.TemporaryDirectory(prefix="mojo-quake-music-") as tmp:
        root = Path(tmp)
        media = root / "media"
        music = media / "id1/music"
        music.mkdir(parents=True)
        (media / "id1/pak0.pak").symlink_to(pak)
        profile = root / "profile"
        (profile / "id1").mkdir(parents=True)
        for with_track in (False, True):
            if with_track:
                write_track(music / "track06.wav")
            output = root / f"{int(with_track)}.raw"
            env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="disk",
                       SDL_DISKAUDIOFILE=str(output), MOJO_QUAKE_PROFILE=str(profile))
            result = subprocess.run(
                [binary, "-basedir", media, "-window", "-width", "320", "-height", "240",
                 "-noudp", "-noconinput", "-mqticks", "290", "+map", "e1m1"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25, check=True,
            )
            if b"Sound Initialized: 16 bits @ 48000Hz" not in result.stdout:
                raise RuntimeError("Expected 48 kHz signed 16-bit SDL output")
            samples = array("h")
            samples.frombytes(output.read_bytes())
            if len(samples) < 2 * OUTPUT_RATE:
                raise RuntimeError("SDL recorded less than a second of stereo output")
            end = samples[-2 * OUTPUT_RATE:]
            left = end[0::2]
            right = end[1::2]
            ll, lr = tone_level(left, LEFT_HZ), tone_level(left, RIGHT_HZ)
            rl, rr = tone_level(right, LEFT_HZ), tone_level(right, RIGHT_HZ)
            print(f"Track present {with_track}, left {ll:.1f}/{lr:.1f}, right {rl:.1f}/{rr:.1f}")
            if with_track:
                if min(ll, rr) <= 500 or ll <= max(1, lr) * 5 or rr <= max(1, rl) * 5:
                    raise RuntimeError("The two soundtrack channels did not reach their SDL outputs")
            elif max(ll, lr, rl, rr) > 150:
                raise RuntimeError("Control recording contains the test tones")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("software_binary", type=Path)
    parser.add_argument("pak", type=Path)
    args = parser.parse_args()
    verify(args.software_binary.resolve(), args.pak.resolve())
