"""MCU-buffered session cues; the device coordinator owns priority decisions."""
from . import Frame
from .animations import heart_pulse, half_helix


class StatusDisplay:
    def __init__(self, board, static_frames):
        self.board = board
        self.static_frames = static_frames
        self.cached = False

    def invalidate(self):
        # Foreground programs may replace any of the nine resident slots.
        self.cached = False

    def show(self, state):
        matrix = self.board.matrix
        if state not in ('standby', 'working'):
            matrix.draw(Frame.from_rows(self.static_frames[state]))
            return
        if not self.cached:
            for slot, frames, duration in ((1, heart_pulse(5), 50), (2, half_helix(5), 40)):
                matrix.load(frames, durations=duration)
                matrix.cache(slot)
            self.cached = True
        matrix.play_cached(1 if state == 'standby' else 2, repeat=0)
