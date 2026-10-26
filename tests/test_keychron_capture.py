"""Input discovery, binary event parsing and mapping behavior, without real input."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('keychron_capture', ROOT/'tools/keychron-capture/capture.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

# Synthetic fixture identity, unrelated to any paired physical device.
ADDRESS = '02:00:00:00:00:01'


class Names:
    def type(self, kind):
        return {0:'EV_SYN',1:'EV_KEY',2:'EV_REL',4:'EV_MSC'}.get(kind,str(kind))
    def code(self, kind, code):
        return {(1,29):'KEY_LEFTCTRL',(1,46):'KEY_C',(1,79):'KEY_KP1',
                (2,8):'REL_WHEEL',(4,4):'MSC_SCAN',(0,0):'SYN_REPORT',(0,3):'SYN_DROPPED'}.get((kind,code),str(code))


def event(kind,code,value):
    return (100,200,kind,code,value)


class CaptureTests(unittest.TestCase):
    def test_capture_requires_explicit_address_before_discovery(self):
        with patch.object(capture,'discover',side_effect=AssertionError('Input discovery attempted')), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:capture.main(['--list'])
        self.assertEqual(error.exception.code,2)

    def test_explicit_list_selects_only_the_requested_address_without_capture(self):
        with patch.object(capture.sys,'platform','linux'), \
             patch.object(capture,'discover',return_value=[]) as discover, \
             patch.object(capture,'capture',side_effect=AssertionError('Capture started')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(capture.main(['--address',ADDRESS,'--list']),0)
        discover.assert_called_once_with(ADDRESS)

    def test_binary_decoder_handles_fragmented_multiple_events_and_signed_delta(self):
        decoder=capture.Decoder()
        data=capture.EVENT.pack(*event(1,79,1))+capture.EVENT.pack(*event(2,8,-1))
        self.assertEqual(list(decoder.feed(data[:5])),[])
        self.assertEqual(list(decoder.feed(data[5:])),[event(1,79,1),event(2,8,-1)])
        self.assertEqual(decoder.buffer,b'')

    def test_identity_discovery_includes_companion_interface_but_excludes_other_keyboards(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for number,name,address in [(2,'Keychron K0 Max Keyboard',ADDRESS),
                                        (3,'Keychron K0 Max Mouse',ADDRESS),
                                        (4,'Other Keyboard',ADDRESS),
                                        (5,'Keychron K0 Max Keyboard','02:00:00:00:00:02')]:
                device=root/f'event{number}/device'
                (device/'id').mkdir(parents=True)
                for path,value in {'name':name,'uniq':address,'phys':'controller',
                                   'id/bustype':'0005','id/vendor':'3434','id/product':'0a06','id/version':'0204'}.items():
                    (device/path).write_text(value)
            found=capture.discover(ADDRESS,sysfs=root,dev=Path('/fixture'))
            self.assertEqual([item['node'] for item in found],['/fixture/event2','/fixture/event3'])

    def test_open_rechecks_identity_on_fd_and_closes_changed_device(self):
        identity=capture.INPUT_ID.pack(5,0x3434,0x0a06,0x0204)
        with patch.object(capture.os,'open',return_value=12), patch.object(capture.os,'close') as close, \
             patch.object(capture,'query',return_value=identity), \
             patch.object(capture,'text_query',side_effect=['Keychron K0 Max Keyboard','controller','02:00:00:00:00:02']):
            with self.assertRaisesRegex(RuntimeError,'identity changed'):
                capture.open_device({'node':'/fixture'},ADDRESS,Names())
            close.assert_called_once_with(12)

    def test_bitmaps_include_high_keycodes(self):
        data=bytearray(128);data[464//8]|=1<<(464%8)
        self.assertEqual(capture.set_bits(data),[464])

    def test_keyboard_repeat_capability_uses_repeat_settings_ioctl(self):
        def query(fd, number, size=512):
            if number==0x02:return capture.INPUT_ID.pack(5,0x3434,0x0a06,0x0204)
            if number==0x20:return (1<<20|1<<1|1).to_bytes(8,'little')
            if number==0x03:return capture.struct.pack('@II',250,33)
            if number==0x20+20:raise AssertionError('EV_REP is not a code bitmap')
            return bytearray(size)
        with patch.object(capture.os,'open',return_value=12), patch.object(capture.os,'close'), \
             patch.object(capture,'query',side_effect=query), \
             patch.object(capture,'text_query',side_effect=['Keychron K0 Max Keyboard','controller',ADDRESS]):
            fd,actual,held=capture.open_device({'node':'/fixture'},ADDRESS,Names())
        self.assertEqual(actual['repeat_settings_ms'],{'delay':250,'period':33})
        self.assertEqual(held,[])

    def test_press_repeat_release_counts_real_cycles_and_hold_time(self):
        recorder=capture.Recorder(Names())
        recorder.event('keyboard',event(4,4,0x70059),0)
        first=recorder.event('keyboard',event(1,79,1),1)
        recorder.event('keyboard',event(1,79,2),500)
        recorder.event('keyboard',event(1,79,0),650)
        key=recorder.summary()['keys'][0]
        self.assertEqual((key['presses'],key['releases'],key['repeats'],key['cycles']),(1,1,1,1))
        self.assertEqual(key['max_hold_ms'],649)
        self.assertEqual(first['scan_hex'],'0x70059')
        self.assertEqual(recorder.summary()['held_at_end'],{})

    def test_initially_held_keys_are_not_invented_as_presses(self):
        recorder=capture.Recorder(Names());recorder.sync('keyboard',[79])
        recorder.event('keyboard',event(1,79,0),10)
        key=recorder.summary()['keys'][0]
        self.assertEqual((key['presses'],key['releases'],key['cycles']),(0,1,0))

    def test_cross_interface_chord_and_signed_wheel_are_recorded(self):
        recorder=capture.Recorder(Names())
        recorder.event('keyboard',event(1,29,1),0)
        row=recorder.event('companion',event(1,46,1),1)
        self.assertEqual(row['held_keys'],['KEY_C','KEY_LEFTCTRL'])
        recorder.event('companion',event(2,8,1),2)
        recorder.event('companion',event(2,8,-1),3)
        axis=recorder.summary()['relative_axes'][0]
        self.assertEqual((axis['positive'],axis['negative'],axis['sum']),(1,1,0))
        self.assertEqual(len(recorder.summary()['chords']),1)

    def test_labels_keep_ordered_macro_sequences_and_quiet_trials(self):
        recorder=capture.Recorder(Names());recorder.mark('M1',0)
        for index,(code,value) in enumerate([(29,1),(46,1),(46,0),(29,0)]):
            recorder.event('keyboard',event(1,code,value),index+1)
        recorder.mark('Fn',10);recorder.mark(None,20)
        labels=recorder.summary()['labels']
        self.assertEqual(labels[0]['status'],'observed')
        self.assertEqual([item['value'] for item in labels[0]['sequence']],[1,1,0,0])
        self.assertEqual(labels[1]['status'],'no_linux_event_observed')

    def test_absolute_controls_preserve_zero_and_signed_values(self):
        recorder=capture.Recorder(Names());recorder.mark('axis',0)
        for index,value in enumerate([-10,20,0]):recorder.event('keyboard',event(3,0,value),index)
        axis=recorder.summary()['absolute_axes'][0]
        self.assertEqual((axis['minimum'],axis['maximum'],axis['last']),(-10,20,0))
        self.assertEqual([r['value'] for r in recorder.summary()['labels'][0]['sequence']],[-10,20,0])

    def test_syn_dropped_ignores_events_until_state_resync(self):
        recorder=capture.Recorder(Names());recorder.mark('key',0)
        recorder.event('keyboard',event(1,29,1),0)
        recorder.event('keyboard',event(0,3,0),1)
        row=recorder.event('keyboard',event(1,46,1),2)
        self.assertFalse(row['trusted_state'])
        self.assertEqual(len(recorder.summary()['keys']),1)
        self.assertEqual(recorder.summary()['labels'][0]['status'],'incomplete')
        recorder.sync('keyboard',[])
        recorder.event('keyboard',event(1,79,1),3)
        self.assertEqual(len(recorder.summary()['keys']),2)

    def test_disconnect_clears_stuck_held_state_without_synthetic_release(self):
        recorder=capture.Recorder(Names())
        recorder.event('keyboard',event(1,79,1),0)
        recorder.gap('keyboard','device_disconnected')
        self.assertEqual(recorder.summary()['held_at_end'],{})
        self.assertEqual(recorder.summary()['keys'][0]['releases'],0)
        self.assertEqual(recorder.summary()['keys'][0]['cycles'],0)

    def test_report_and_files_are_private_and_keep_unknown_numeric_codes(self):
        recorder=capture.Recorder(Names());recorder.event('keyboard',event(1,700,1),0)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'summary.json';capture.private_json(path,recorder.summary())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertEqual(json.loads(path.read_text())['keys'][0]['code'],700)
            with self.assertRaises(FileExistsError):capture.private_json(path,{})

    def test_guided_mode_rejects_non_tty_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'output'
            args=argparse.Namespace(guided=True,output=path)
            with patch.object(capture.sys.stdin,'isatty',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'interactive'):
                    capture.capture(args,Names())
            self.assertFalse(path.exists())


if __name__=='__main__':unittest.main()
