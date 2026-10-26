import ast
import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('led_demo', ROOT / 'examples/01-linux-rgb-led/main.py')
led_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(led_demo)


class ExampleTests(unittest.TestCase):
    def fixture_led(self, root):
        for index, name in enumerate(led_demo.CHANNELS):
            channel = root / name
            channel.mkdir()
            (channel / 'brightness').write_text(str(index) + '\n')
            (channel / 'max_brightness').write_text('255\n')
            (channel / 'trigger').write_text('none [timer] heartbeat\n')
        return led_demo.UserLed(root)

    def assert_restored(self, root):
        for index, name in enumerate(led_demo.CHANNELS):
            self.assertEqual((root / name / 'brightness').read_text(), str(index) + '\n')
            self.assertEqual((root / name / 'trigger').read_text(), 'timer\n')

    def test_rgb_demo_restores_previous_brightness_and_triggers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            led = self.fixture_led(root)
            with patch.object(led_demo.time, 'sleep'):
                led.cycle(1, 0.1)
            self.assert_restored(root)

    def test_rgb_demo_restores_state_after_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            led = self.fixture_led(root)
            with patch.object(led_demo.time, 'sleep', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    led.cycle(1, 0.1)
            self.assert_restored(root)

    def test_read_only_initialization_does_not_change_leds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            led = self.fixture_led(root)
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            led_demo.UserLed(root)
            self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_python_sources_parse_without_installing_app_lab_on_host(self):
        for path in [*ROOT.glob('scripts/*.py'), *ROOT.glob('examples/**/*.py'),
                     *ROOT.glob('packages/device/src/**/*.py'), *ROOT.glob('firmware/**/*.py')]:
            with self.subTest(path=path):
                ast.parse(path.read_text(), filename=str(path))

    def test_complete_app_layouts_and_resolvable_skill_references(self):
        app = ROOT / 'firmware/uno-q/controller'
        for relative in ['README.md', 'app.yaml', 'python/main.py', 'sketch/sketch.ino', 'sketch/sketch.yaml']:
            self.assertTrue((app / relative).is_file(), str(app / relative))
        for name in ['02-mcu-rgb-led', '03-matrix-patterns', '04-matrix-animation']:
            self.assertTrue((ROOT / 'examples' / name / 'main.py').is_file())
            self.assertFalse((ROOT / 'examples' / name / 'sketch').exists())
        for skill in (ROOT / 'agent/skills').glob('*/SKILL.md'):
            text = skill.read_text()
            self.assertTrue(text.startswith('---\nname: ' + skill.parent.name + '\n'))
            self.assertRegex(text, r'\ndescription: .+')
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if not target.startswith('https://'):
                    self.assertTrue((skill.parent / target).is_file(), str(skill.parent / target))


if __name__ == '__main__':
    unittest.main()
