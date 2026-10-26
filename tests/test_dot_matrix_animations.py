"""Quantized animation families and passive Keychron/terminal selection."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/device/src'), str(ROOT / 'packages/session/src')]
spec = importlib.util.spec_from_file_location('dot_matrix_animations', ROOT / 'examples/06-dot-matrix-animations/main.py')
animations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(animations)
from torque import input as inputs


def input_record(kind, code, value):
    return inputs.EVENT.pack(10, 20, kind, code, value)


def adapter(events=()):
    source = object.__new__(animations.KeychronKeys)
    source.keypad = SimpleNamespace(poll=Mock(return_value=list(events)),close=Mock())
    return source


class AnimationTests(unittest.TestCase):
    def test_all_clips_fit_buffer_region_and_native_brightness(self):
        for name, count in [('half-helix', 24), ('neon-drift', 24), ('crt-glide', 30),
                            ('echo-ring', 32), ('origin-wave', 32), ('prism-bloom', 32),
                            ('sound-bars', 24), ('mobius-run', 32), ('plasma-veil', 24),
                            ('heart-pulse', 28)]:
            frames = animations.render_frames(7, name)
            with self.subTest(name=name):
                self.assertEqual(len(frames), count)
                self.assertGreaterEqual(len(set(frames)), 5 if name in ('crt-glide','heart-pulse') else 12)
                self.assertTrue(any(p not in (0, 7) for f in frames for p in f.pixels))
                for frame in frames:
                    self.assertEqual(frame.bits, 3)
                    self.assertTrue(all(0 <= p <= 7 for p in frame.pixels))
                    self.assertTrue(all(not p or (4 <= i % 13 < 9 and 1 <= i // 13 < 6)
                                        for i, p in enumerate(frame.pixels)))
                self.assertTrue(all(p <= 3 for f in animations.render_frames(3, name) for p in f.pixels))

    def test_neon_drift_moves_from_top_right_and_keeps_diagonals_coherent(self):
        frames = animations.render_frames(animation='neon-drift')
        self.assertEqual(frames[0].pixels[1 * 13 + 8], 7)
        self.assertEqual(frames[0].pixels[5 * 13 + 4], 0)
        self.assertEqual(frames[12].pixels[4 * 13 + 6], 7)
        for frame in frames:
            diagonals = {}
            for y in range(5):
                for x in range(5):
                    diagonals.setdefault(y + 4 - x, set()).add(frame.pixels[(y+1)*13+x+4])
            self.assertTrue(all(len(levels) == 1 for levels in diagonals.values()))

    def test_crt_glide_scans_down_with_a_fading_wake_and_dark_rows_ahead(self):
        frames = animations.render_frames(animation='crt-glide')
        self.assertEqual(len(frames),30)
        self.assertEqual(len(set(frames)),5)
        self.assertNotIn('core-spiral',animations.ANIMATIONS)
        self.assertEqual(animations.DIGITS['3'],'crt-glide')
        for scan in range(5):
            self.assertTrue(all(frame == frames[scan*6] for frame in frames[scan*6:scan*6+6]))
            levels=[]
            for y in range(5):
                row=frames[scan*6].pixels[(y+1)*13+4:(y+1)*13+9]
                self.assertEqual(len(set(row)),1)
                levels.append(row[0])
            self.assertEqual(levels[scan],7)
            self.assertTrue(all(level==0 for level in levels[scan+1:]))
            self.assertEqual(levels[:scan+1],sorted(levels[:scan+1]))
        self.assertEqual([frames[-1].pixels[(y+1)*13+4] for y in range(5)],[0,1,2,4,7])

    def test_echo_ring_is_centered_and_has_a_weaker_trailing_echo(self):
        frames = animations.render_frames(animation='echo-ring')
        for frame in frames:
            for y in range(5):
                for x in range(5):
                    self.assertEqual(frame.pixels[(y+1)*13+x+4], frame.pixels[(x+1)*13+(4-y)+4])
        self.assertEqual(frames[0].pixels[3*13+6], 7)
        self.assertGreater(frames[8].pixels[3*13+6], 0)
        self.assertLess(frames[8].pixels[3*13+6], frames[8].pixels[3*13+8])
        self.assertFalse(any(frames[-1].pixels))

    def test_origin_wave_expands_from_local_one_one_and_fades(self):
        frames = animations.render_frames(animation='origin-wave')
        self.assertEqual(frames[0].pixels[2*13+5], 7)
        self.assertEqual(frames[0].pixels[5*13+8], 0)
        self.assertEqual(frames[24].pixels[5*13+8], 7)
        self.assertFalse(any(frames[-1].pixels))

    def test_prism_bloom_has_distinct_symmetric_motifs(self):
        frames = animations.render_frames(animation='prism-bloom')
        self.assertEqual(len({frames[i] for i in (0,8,16,24)}), 4)
        for frame in frames:
            for y in range(5):
                for x in range(5):
                    self.assertEqual(frame.pixels[(y+1)*13+x+4], frame.pixels[(5-y)*13+(4-x)+4])

    def test_sound_bars_are_bottom_anchored_and_vary_in_height(self):
        frames = animations.render_frames(animation='sound-bars')
        for x in range(5):
            heights = set()
            for frame in frames:
                occupied = [y for y in range(5) if frame.pixels[(y+1)*13+x+4]]
                self.assertTrue(occupied)
                self.assertEqual(occupied, list(range(occupied[0],5)))
                heights.add(len(occupied))
            self.assertGreaterEqual(len(heights),4)

    def test_mobius_keeps_center_off_and_plasma_keeps_corners_off(self):
        folds = {(1,1),(3,1),(1,3),(3,3)}
        for frame in animations.render_frames(animation='mobius-run'):
            self.assertEqual(frame.pixels[3*13+6],0)
            for y in range(1,4):
                for x in range(1,4):
                    if (x,y) not in folds:self.assertEqual(frame.pixels[(y+1)*13+x+4],0)
        for frame in animations.render_frames(animation='plasma-veil'):
            for x,y in ((0,0),(4,0),(0,4),(4,4)):
                self.assertEqual(frame.pixels[(y+1)*13+x+4],0)
            self.assertEqual(frame.pixels[3*13+6],1)

    def test_preview_never_detects_keyboard_or_connects_to_board(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(animations, 'detect_keyboard', side_effect=AssertionError('Input opened')), \
                 patch.object(animations, 'Board', side_effect=AssertionError('Board contacted')), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(animations.main(['--output-dir', temp]), 0)
            self.assertEqual({p.name for p in Path(temp).glob('*.svg')},
                             {name + '.svg' for name in animations.ANIMATIONS})


class KeychronTests(unittest.TestCase):
    def test_numpad_and_number_row_keep_all_nine_presets_without_heart_binding(self):
        self.assertEqual(len(animations.DIGITS),9)
        self.assertNotIn('heart-pulse',animations.KEYPAD_KEYS.values())
        self.assertNotIn('0',animations.DIGITS)
        for digit,name in animations.DIGITS.items():
            events=[inputs.KeyEvent('KP'+digit,'press'),inputs.KeyEvent('KP'+digit,'repeat'),
                    inputs.KeyEvent('KP'+digit,'release'),inputs.KeyEvent(digit,'press')]
            self.assertEqual(adapter(events).poll(),[name,name])
        self.assertEqual(adapter([inputs.KeyEvent('ESC','press')]).poll(),['quit'])
        self.assertEqual(adapter([inputs.KeyEvent('KP0','press'),inputs.KeyEvent('KNOB_UP','press'),
                                  inputs.KeyEvent(None,'resync')]).poll(),[])

    def test_adapter_uses_public_keypad_selection_and_releases_it(self):
        keypad=SimpleNamespace(identity={'node':'/fixture/event2'},close=Mock(),poll=Mock(return_value=[]))
        with patch.object(animations,'Keypad',return_value=keypad) as opened:
            source=animations.KeychronKeys(address='02:00:00:00:00:01')
            opened.assert_called_once_with(address='02:00:00:00:00:01')
            self.assertEqual(source.node,'/fixture/event2')
            source.poll(.01);keypad.poll.assert_called_once_with(timeout=.01)
            source.close();keypad.close.assert_called_once()

    def test_auto_discovery_uses_shared_capabilities_and_opens_only_one(self):
        with patch.object(animations,'input_capabilities',return_value={'available':True,'selection_required':False}) as caps, \
             patch.object(animations,'KeychronKeys',return_value='selected') as opened:
            self.assertEqual(animations.detect_keyboard(),'selected')
            caps.assert_called_once_with(address=None);opened.assert_called_once_with(address=None)
        with patch.object(animations,'input_capabilities',return_value={'available':False,'selection_required':False}), \
             patch.object(animations,'KeychronKeys') as opened:
            self.assertIsNone(animations.detect_keyboard());opened.assert_not_called()

    def test_ambiguous_keypads_require_selection_and_explicit_address_is_forwarded(self):
        with patch.object(animations,'input_capabilities',return_value={'available':False,'selection_required':True}), \
             patch.object(animations,'KeychronKeys') as opened:
            with self.assertRaisesRegex(inputs.KeypadUnavailable,'--keyboard-address'):
                animations.detect_keyboard()
            opened.assert_not_called()
        address='02:00:00:00:00:01'
        with patch.object(animations,'input_capabilities',return_value={'available':True,'selection_required':False}) as caps, \
             patch.object(animations,'KeychronKeys',return_value='selected') as opened:
            self.assertEqual(animations.detect_keyboard(address),'selected')
            caps.assert_called_once_with(address=address);opened.assert_called_once_with(address=address)

    def test_explicit_missing_device_busy_lease_and_discovery_race_never_fallback(self):
        with patch.object(animations,'input_capabilities',return_value={'available':False,'selection_required':False}):
            with self.assertRaisesRegex(inputs.KeypadUnavailable,'selected keypad'):
                animations.detect_keyboard('02:00:00:00:00:01')
        for error in (inputs.KeypadBusy('busy'),inputs.KeypadUnavailable('identity changed')):
            with patch.object(animations,'input_capabilities',return_value={'available':True,'selection_required':False}), \
                 patch.object(animations,'Keypad',side_effect=error):
                with self.assertRaises(type(error)):animations.detect_keyboard()

    def test_shared_decoder_fragmented_events_holds_repeats_and_latest_press(self):
        decoder=inputs._Decoder([79]);source=adapter()
        data=b''.join(input_record(1,code,value) for code,value in
                      [(79,1),(79,2),(79,0),(79,1),(79,1),(79,2),(80,1),(81,1),(1,1)])
        source.keypad.poll.side_effect=lambda timeout:decoder.feed(next(chunks),lambda:())
        chunks=iter([data[:5],data[5:]])
        self.assertEqual(source.poll(),[])
        self.assertEqual(source.poll(),['half-helix','neon-drift','crt-glide','quit'])

    def test_shared_overrun_resync_does_not_invent_a_selection(self):
        decoder=inputs._Decoder();source=adapter()
        data=b''.join(input_record(k,c,v) for k,c,v in
                      [(0,3,0),(1,80,1),(0,0,0),(1,79,1),(1,79,0),(1,79,1)])
        source.keypad.poll.side_effect=lambda timeout:decoder.feed(data,lambda:[79])
        self.assertEqual(source.poll(),['half-helix'])

    def test_disconnect_uses_existing_gallery_fallback(self):
        source=adapter();source.keypad.poll.side_effect=inputs.KeypadDisconnected('lost')
        with self.assertRaises(animations.KeyboardDisconnected):source.poll()
        source.close();source.keypad.close.assert_called_once()

    def test_terminal_mode_restores_settings_and_rejects_noninteractive_input(self):
        with patch.object(animations.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'interactive terminal'):
                animations.TerminalKeys()
        import termios
        import tty
        with patch.object(animations.sys.stdin, 'isatty', return_value=True), \
             patch.object(animations.sys.stdin, 'fileno', return_value=7), \
             patch.object(termios, 'tcgetattr', return_value=['saved']), patch.object(tty, 'setcbreak'), \
             patch.object(termios, 'tcsetattr') as restored, \
             patch.object(animations.select, 'select', return_value=([7], [], [])), \
             patch.object(animations.os, 'read', return_value=b'123456789q'):
            keys = animations.TerminalKeys()
            self.assertEqual(keys.poll(), [*animations.KEYPAD_ANIMATIONS, 'quit'])
            keys.close()
            restored.assert_called_once_with(7, termios.TCSADRAIN, ['saved'])


class PlaybackTests(unittest.TestCase):
    def test_ambiguous_or_busy_keyboard_never_opens_board_or_starts_gallery(self):
        for error in (inputs.KeypadUnavailable('multiple keypads'),inputs.KeypadBusy('busy')):
            with tempfile.TemporaryDirectory() as temp,patch.object(animations,'detect_keyboard',side_effect=error), \
                 patch.object(animations,'Board') as board,contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(type(error)):animations.main(['--play','--output-dir',temp])
                board.assert_not_called()

    def test_address_selection_and_incompatible_modes_are_explicit(self):
        source=SimpleNamespace(poll=Mock(return_value=['quit']),close=Mock())
        matrix=SimpleNamespace(load=Mock(),play=Mock(),status=lambda:{'playing':False},clear=Mock())
        with tempfile.TemporaryDirectory() as temp,patch.object(animations,'detect_keyboard',return_value=source) as detected, \
             patch.object(animations,'Board') as board,contextlib.redirect_stdout(io.StringIO()):
            board.return_value.__enter__.return_value=SimpleNamespace(matrix=matrix)
            animations.main(['--play','--keyboard-address','02:00:00:00:00:01','--output-dir',temp])
            detected.assert_called_once_with(address='02:00:00:00:00:01')
        for mode in ('none','terminal'):
            with patch.object(animations,'Board') as board,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    animations.main(['--keyboard-address','02:00:00:00:00:01','--input',mode])
                board.assert_not_called()

    def test_preload_once_then_each_key_uses_only_cached_play(self):
        matrix=SimpleNamespace(load=Mock(),cache=Mock(),play_cached=Mock(),play=Mock(),
                               status=lambda:{'playing':True},clear=Mock())
        board=SimpleNamespace(matrix=matrix,capability=lambda name:{'max_presets':9,'max_frames':32})
        player=animations.Player(board,25)
        clips={name:animations.render_frames(animation=name) for name in animations.KEYPAD_ANIMATIONS}
        with contextlib.redirect_stdout(io.StringIO()):self.assertTrue(player.prepare(clips))
        self.assertEqual(matrix.load.call_count,9)
        self.assertEqual([c.args[0] for c in matrix.cache.call_args_list],list(range(1,10)))
        matrix.load.reset_mock();matrix.cache.reset_mock()
        source=SimpleNamespace(poll=Mock(side_effect=[[name] for name in [*clips,'quit']]))
        with contextlib.redirect_stdout(io.StringIO()):animations.interactive(player,clips,source)
        self.assertEqual([c.args[0] for c in matrix.play_cached.call_args_list],list(range(1,10)))
        self.assertTrue(all(c.kwargs['repeat']==0 for c in matrix.play_cached.call_args_list))
        matrix.load.assert_not_called();matrix.cache.assert_not_called();matrix.play.assert_not_called()
        self.assertTrue(all(c.kwargs['timeout']==0.01 for c in source.poll.call_args_list))

    def test_old_controller_falls_back_before_preloading(self):
        matrix=SimpleNamespace(load=Mock(),cache=Mock(),play_cached=Mock(),play=Mock())
        player=animations.Player(SimpleNamespace(matrix=matrix,capability=lambda name:None),25)
        clips={'half-helix':animations.render_frames()}
        with contextlib.redirect_stdout(io.StringIO()):self.assertFalse(player.prepare(clips))
        matrix.load.assert_not_called();matrix.cache.assert_not_called()
        player.start(clips['half-helix'],repeat=0)
        self.assertEqual(matrix.load.call_count,1)
        matrix.play.assert_called_once_with(repeat=0)
    def run_example(self, source):
        events = []
        names = {tuple(animations.render_frames(animation=name)): name for name in animations.ANIMATIONS}
        matrix = SimpleNamespace(load=lambda frames, **kwargs: events.append(('load', names[tuple(frames)])),
                                 play=lambda **kwargs: events.append(('play', kwargs['repeat'])),
                                 status=lambda: {'playing':False}, clear=lambda: events.append(('clear',)))
        with tempfile.TemporaryDirectory() as temp, patch.object(animations, 'Board') as board, \
             patch.object(animations, 'detect_keyboard', return_value=source), \
             patch.object(animations.signal, 'signal'), contextlib.redirect_stdout(io.StringIO()):
            board.return_value.__enter__.return_value = SimpleNamespace(matrix=matrix)
            self.assertEqual(animations.main(['--play','--output-dir',temp]), 0)
        return events

    def test_no_keyboard_runs_full_gallery_in_order_for_three_rounds_then_clears(self):
        events = self.run_example(None)
        self.assertEqual([event[1] for event in events if event[0]=='load'], list(animations.KEYPAD_ANIMATIONS)*3)
        self.assertEqual([event[1] for event in events if event[0]=='play'], [1]*27)
        self.assertEqual(events[-1], ('clear',))

    def test_keyboard_each_selection_loops_then_exits_and_closes_input(self):
        source = SimpleNamespace(poll=Mock(side_effect=[[name] for name in [*animations.KEYPAD_ANIMATIONS, 'quit']]),
                                 close=Mock())
        events = self.run_example(source)
        self.assertEqual([event[1] for event in events if event[0]=='load'], list(animations.KEYPAD_ANIMATIONS))
        self.assertEqual([event[1] for event in events if event[0]=='play'], [0]*9)
        source.close.assert_called_once()

    def test_infinite_clip_has_no_finite_observation_deadline_and_same_selection_does_not_reload(self):
        matrix = SimpleNamespace(load=Mock(), play=Mock(), status=lambda: {'playing':True}, clear=Mock())
        player = animations.Player(SimpleNamespace(matrix=matrix), 25)
        clips = {name: animations.render_frames(animation=name) for name in animations.KEYPAD_ANIMATIONS}
        source = SimpleNamespace(poll=Mock(side_effect=[['half-helix'],['half-helix'],['neon-drift'],['quit']]))
        with patch.object(animations.time, 'monotonic', return_value=100000), contextlib.redirect_stdout(io.StringIO()):
            animations.interactive(player, clips, source)
            self.assertTrue(player.playing())
        self.assertIsNone(player.deadline)
        self.assertEqual(matrix.load.call_count, 2)
        self.assertEqual([c.kwargs['repeat'] for c in matrix.play.call_args_list], [0,0])

    def test_disconnect_falls_back_to_finite_gallery_and_closes_input(self):
        source = SimpleNamespace(poll=Mock(side_effect=[['half-helix'],animations.KeyboardDisconnected('lost')]), close=Mock())
        events = self.run_example(source)
        self.assertEqual([event[1] for event in events if event[0]=='load'], ['half-helix']+list(animations.KEYPAD_ANIMATIONS)*3)
        source.close.assert_called_once()

    def test_heart_pulse_runs_by_name_without_keyboard_or_gallery_preload(self):
        from torque.animations import heart_pulse
        self.assertIs(animations.heart_pulse, heart_pulse)
        with tempfile.TemporaryDirectory() as temp, patch.object(animations,'play') as play, \
             patch.object(animations,'detect_keyboard',side_effect=AssertionError('Keyboard opened')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(animations.main(['--play','--animation','heart-pulse','--peak','5',
                                             '--frame-ms','50','--repeat','2','--output-dir',temp]),0)
            self.assertTrue((Path(temp)/'heart-pulse.svg').exists())
        play.assert_called_once_with(heart_pulse(5),50,2)

    def test_input_is_closed_when_board_connection_fails(self):
        source = SimpleNamespace(close=Mock())
        with tempfile.TemporaryDirectory() as temp, patch.object(animations, 'TerminalKeys', return_value=source), \
             patch.object(animations, 'Board') as board, contextlib.redirect_stdout(io.StringIO()), \
             patch.object(animations.signal, 'signal'):
            board.return_value.__enter__.side_effect = RuntimeError('Controller unavailable')
            with self.assertRaisesRegex(RuntimeError, 'Controller unavailable'):
                animations.main(['--play','--input','terminal','--output-dir',temp])
        source.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
