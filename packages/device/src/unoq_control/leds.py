"""Standard-library Linux user LED control; no Bridge dependency."""
from pathlib import Path
import re
import time

CHANNELS = ('red:user', 'green:user', 'blue:user')


class UserLed:
    def __init__(self, root=Path('/sys/class/leds')):
        self.root = Path(root)
        self.original = {}
        for name in CHANNELS:
            path = self.root / name
            brightness = int((path / 'brightness').read_text())
            maximum = int((path / 'max_brightness').read_text())
            trigger = path / 'trigger'
            active = re.search(r'\[([^]]+)\]', trigger.read_text()) if trigger.exists() else None
            self.original[name] = (brightness, maximum, active.group(1) if active else None)

    def __enter__(self):
        try:
            self.manual()
        except BaseException:
            self.restore()
            raise
        return self

    def __exit__(self, *_):
        self.restore()

    def set(self, r, g, b):
        if any(type(value) is not bool for value in (r, g, b)):
            raise ValueError('RGB channels must be booleans')
        self.color((r, g, b))

    def manual(self):
        for name, (_, _, trigger) in self.original.items():
            if trigger is not None:
                (self.root / name / 'trigger').write_text('none\n')

    def color(self, rgb):
        for name, enabled in zip(CHANNELS, rgb):
            maximum = self.original[name][1]
            (self.root / name / 'brightness').write_text(str(maximum if enabled else 0) + '\n')

    def restore(self):
        errors = []
        for name, (brightness, _, trigger) in self.original.items():
            try:
                (self.root / name / 'brightness').write_text(str(brightness) + '\n')
                if trigger is not None:
                    (self.root / name / 'trigger').write_text(trigger + '\n')
            except OSError as error:
                errors.append(type(error).__name__ + ': ' + name)
        if errors:
            raise OSError('Could not restore all LED channels: ' + ', '.join(errors))

    def cycle(self, cycles, interval):
        try:
            self.manual()
            for _ in range(cycles):
                for rgb in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
                    self.color(rgb)
                    time.sleep(interval)
        finally:
            self.restore()
