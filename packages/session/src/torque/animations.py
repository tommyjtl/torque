"""Pure frame generators shared by reference projects and session status."""
import math
from . import Frame


def half_helix(peak):
    """An original single traveling strand, sampled on a 5x5 region at (4,1)."""
    frames = []
    for step in range(24):
        pixels = [0] * 104
        phase = math.tau * step / 24
        for y in range(5):
            center = 2 + 1.8 * math.sin(phase - math.tau * y / 5)
            for x in range(5):
                coverage = min(1.0, max(0.0, 1.2 - abs(x - center)))
                pixels[(y + 1) * 13 + x + 4] = int(peak * coverage + 0.5)
        frames.append(Frame(pixels, bits=3))
    return frames


def heart_pulse(peak):
    """An original double beat across a circular 5x5 glow at (4,1)."""
    def beat(step, start, apex, end):
        if not start < step < end:
            return 0
        progress = ((step - start) / (apex - start) if step <= apex else
                    (end - step) / (end - apex))
        return (1 - math.cos(math.pi * progress)) / 2

    frames = []
    for step in range(28):
        strength = max(beat(step, 0, 5, 14), 0.55 * beat(step, 14, 18, 21))
        pixels = [0] * 104
        for y in range(5):
            for x in range(5):
                distance = (x - 2)**2 + (y - 2)**2
                if distance == 8:  # Circular mask: leave the four corners dark.
                    continue
                base, crest = ((1/3, 1) if distance == 0 else
                               (1/6, 3/4) if distance <= 2 else (1/12, 1/5))
                level = int(peak * (base + (crest - base) * strength) + 0.5)
                pixels[(y + 1) * 13 + x + 4] = max(1, level)
        frames.append(Frame(pixels, bits=3))
    return frames
