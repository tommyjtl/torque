"""Audio discovery, routing rollback, leases and parent-death cleanup."""
import asyncio
import copy
import json
import os
from pathlib import Path
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'packages/session/src'), str(ROOT/'packages/device/src')]
from torque import audio
from torque import _audio_worker as worker
from torque import policy
from torque.daemon import Daemon


def controls():
    result = {}
    for name, target in audio.ROUTE:
        kind = 'ENUMERATED' if isinstance(target, str) else ('INTEGER' if name.endswith('Volume') else 'BOOLEAN')
        value = '84' if name == 'TX_DEC0 Volume' else '0' if kind != 'BOOLEAN' else 'off'
        if name.startswith('MultiMedia3'):
            value = 'on'  # Preserve this pre-existing state, not a blanket "off".
        result[name] = {'kind': kind, 'value': value, 'items': {target: '2'} if isinstance(target, str) else {}}
    return result


class FakeAlsa:
    def __init__(self):
        self.controls = controls()
        self.before = copy.deepcopy(self.controls)
        self.writes = []

    def get(self, name):
        return copy.deepcopy(self.controls[name])

    def set(self, name, value):
        self.writes.append((name, value))
        self.controls[name]['value'] = value

    def idle(self):
        pass


class DiscoveryTests(unittest.TestCase):
    def test_discovery_selects_stable_card_and_never_opens_pcm_or_changes_mixer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'cards').write_text(' 7 [ArduinoImolaHPH]: qcm2290 - Arduino-Imola-HPH-LOUT\n')
            with patch.object(audio.sys, 'platform', 'linux'), patch.object(audio.shutil, 'which', return_value='/fake/tool'), \
                 patch.object(Path, 'is_char_device', return_value=True), patch.object(audio.os, 'access', return_value=True), \
                 patch.object(audio.subprocess, 'Popen', side_effect=AssertionError('Started capture')), \
                 patch.object(audio.subprocess, 'run', side_effect=AssertionError('Changed route')):
                info = audio.audio_capabilities(proc=root, dev=root)
                self.assertTrue(info['available'])
                self.assertEqual(info['sources'][0]['alsa_device'], 'plughw:CARD=ArduinoImolaHPH,DEV=2')
                self.assertEqual(info['sources'][0]['card_index'], 7)
                self.assertFalse(info['capture_started'])
                self.assertFalse(info['signal_verified'])
                self.assertFalse(audio.audio_capabilities(card='another', proc=root, dev=root)['available'])

    def test_non_linux_and_bad_selectors_are_bounded_metadata_only(self):
        with patch.object(audio.sys, 'platform', 'darwin'):
            self.assertFalse(audio.audio_capabilities()['available'])
        for card in ('', '0;injection', '../card', 'a'*33, 1):
            with self.assertRaises(ValueError):
                audio.audio_capabilities(card=card)
        for duration in (0, 301, True, 1.5):
            with self.assertRaises(ValueError):
                audio.Microphone(seconds=duration)
        with patch.object(audio.subprocess, 'Popen') as opened:
            audio.Microphone(seconds=2)
            opened.assert_not_called()


class LevelTests(unittest.TestCase):
    def test_silence_and_signed_full_scale_are_normalized_without_printing_pcm(self):
        silence = audio.AudioChunk(b'\0'*16)
        self.assertEqual((silence.rms, silence.peak, silence.frames), (0, 0, 4))
        self.assertEqual(silence.dbfs, -float('inf'))
        chunk = audio.AudioChunk(struct.pack('<ii', -2147483648, 2147483647))
        self.assertAlmostEqual(chunk.rms, 1)
        self.assertEqual(chunk.peak, 1)
        self.assertNotIn('pcm=', repr(chunk))
        for value in (b'', b'123', b'0'*(48000*4+4), bytearray(4)):
            with self.assertRaises(ValueError):
                audio.AudioChunk(value)


class DiscoveryToolTests(unittest.TestCase):
    def test_host_discovery_is_read_only_and_cannot_request_capture(self):
        for mode in policy.MODES:
            self.assertFalse(policy.needs_approval('audio_capabilities', mode))
        with self.assertRaises(ValueError):
            policy.validate('audio_capabilities', {'record':True})
        with patch.object(audio, 'audio_capabilities', return_value={'capture_started':False}) as inspect:
            daemon = object.__new__(Daemon)
            self.assertEqual(asyncio.run(daemon.execute('audio_capabilities', {})), {'capture_started':False})
            inspect.assert_called_once_with()


class RoutingTests(unittest.TestCase):
    def test_successful_cleanup_restores_exact_original_controls(self):
        alsa = FakeAlsa()
        route = worker.Routing(alsa)
        route.setup(threading.Event())
        self.assertNotEqual(alsa.controls, alsa.before)
        route.restore()
        self.assertEqual(alsa.controls, alsa.before)
        self.assertFalse(any(name.startswith('MultiMedia3') for name, value in alsa.writes))

    def test_missing_profile_choice_fails_before_any_write(self):
        alsa = FakeAlsa()
        alsa.controls['ADC2 MUX']['items'] = {}
        with self.assertRaises(audio.AudioError):
            worker.Routing(alsa).setup(threading.Event())
        self.assertEqual(alsa.writes, [])

    def test_failed_acknowledgement_is_rolled_back_even_if_write_happened(self):
        alsa = FakeAlsa()
        normal = alsa.set
        failed = False
        def fail_once(name, value):
            nonlocal failed
            normal(name, value)
            if name == 'ADC2 Switch' and not failed:
                failed = True
                raise audio.AudioError('lost acknowledgement')
        alsa.set = fail_once
        with self.assertRaisesRegex(audio.AudioError, 'acknowledgement'):
            worker.run(alsa, 1, threading.Event())
        self.assertEqual(alsa.controls, alsa.before)

    def test_cleanup_preserves_a_control_changed_by_another_consumer(self):
        alsa = FakeAlsa()
        route = worker.Routing(alsa)
        route.setup(threading.Event())
        alsa.controls['ADC2 Volume']['value'] = '3'
        with self.assertRaisesRegex(audio.AudioError, 'another consumer'):
            route.restore()
        self.assertEqual(alsa.controls['ADC2 Volume']['value'], '3')
        for name in alsa.controls:
            if name != 'ADC2 Volume':
                self.assertEqual(alsa.controls[name], alsa.before[name])

    def test_busy_capture_is_refused_without_mixer_writes(self):
        alsa = FakeAlsa()
        alsa.idle = Mock(side_effect=audio.MicrophoneBusy('busy'))
        with self.assertRaises(audio.MicrophoneBusy):
            worker.run(alsa, 1, threading.Event())
        self.assertEqual(alsa.writes, [])

    def test_alsa_control_parser_understands_real_mixer_reply_formats(self):
        alsa = worker.Alsa(audio.CARD_ID, 0)
        for text, kind, value in [
            ('; type=BOOLEAN,access=rw------,values=1\n : values=on\n', 'BOOLEAN', 'on'),
            ("; type=ENUMERATED,access=rw------,values=1,items=2\n ; Item #0 'ZERO'\n ; Item #1 'SWR_MIC'\n : values=1\n", 'ENUMERATED', '1'),
            ('; type=INTEGER,access=rw---R--,values=1,min=0,max=124\n : values=84\n', 'INTEGER', '84'),
        ]:
            with patch.object(alsa, 'command', return_value=text):
                parsed = alsa.get('control')
                self.assertEqual((parsed['kind'], parsed['value']), (kind, value))
        with patch.object(alsa, 'command', return_value='; type=BOOLEAN,values=2\n : values=on,off\n'):
            with self.assertRaises(audio.AudioError):
                alsa.get('stereo')

    def test_audio_lease_is_exclusive_and_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'audio'
            lease = worker.claim(audio.CARD_ID, path)
            try:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
                with self.assertRaises(audio.MicrophoneBusy):
                    worker.claim(audio.CARD_ID, path)
            finally:
                os.close(lease)
            os.close(worker.claim(audio.CARD_ID, path))


class ClientTests(unittest.TestCase):
    def test_latest_skips_old_samples_but_preserves_partial_tail_and_ordered_default(self):
        mic = audio.Microphone()
        read, write = os.pipe()
        mic.process = Mock(stdout=os.fdopen(read,'rb',buffering=0))
        samples = struct.pack('<iiiii',1,2,3,4,5)
        try:
            os.write(write, samples+b'\x06')
            latest = mic.read(frames=2, latest=True)
            self.assertEqual(latest.pcm, struct.pack('<ii',4,5))
            self.assertEqual(mic.buffer, b'\x06')
            os.write(write,b'\0\0\0'+struct.pack('<ii',7,8))
            self.assertEqual(mic.read(frames=2).pcm,struct.pack('<ii',6,7))
            self.assertEqual(mic.read(frames=1).pcm,struct.pack('<i',8))
        finally:
            mic.process.stdout.close();os.close(write)

    def producer(self, body):
        real_popen = subprocess.Popen
        return lambda *args, **kwargs: real_popen([sys.executable,'-u','-c',body], **kwargs)

    def source(self):
        return {'available':True,'sources':[{'accessible':True,'card':audio.CARD_ID}]}

    def test_client_start_reads_pcm_and_normal_eof_reaps_helper(self):
        body = ("import os,json,struct,sys;"
                "os.write(1,(json.dumps({'ready':True,'sample_rate':48000,'channels':1,'format':'S32_LE'})+'\\n').encode());"
                "os.write(1,struct.pack('<iii',1,-2,3));os.close(1);sys.stdin.buffer.read()")
        with patch.object(audio, 'audio_capabilities', return_value=self.source()), \
             patch.object(audio.subprocess, 'Popen', side_effect=self.producer(body)):
            with audio.Microphone(seconds=1) as mic:
                self.assertEqual(mic.read(frames=2).pcm, struct.pack('<ii',1,-2))
                self.assertEqual(mic.read(frames=2).pcm, struct.pack('<i',3))
                self.assertIsNone(mic.read())
            self.assertIsNone(mic.process)

    def test_worker_busy_error_is_typed_and_closed_before_readiness(self):
        body = "import sys;sys.stderr.write('Another project owns audio');sys.exit(3)"
        with patch.object(audio, 'audio_capabilities', return_value=self.source()), \
             patch.object(audio.subprocess, 'Popen', side_effect=self.producer(body)):
            mic = audio.Microphone(seconds=1)
            with self.assertRaisesRegex(audio.MicrophoneBusy, 'owns audio'):
                mic.start()
            self.assertIsNone(mic.process)

    def test_fragmented_pcm_timeout_retains_samples_and_eof_returns_last_chunk(self):
        mic = audio.Microphone()
        mic.process = Mock()
        with patch.object(mic, '_receive', side_effect=[b'\x01', TimeoutError(), b'\0\0\0', b'']), \
             patch.object(mic, 'close', side_effect=lambda: setattr(mic, 'process', None)):
            with self.assertRaises(TimeoutError):
                mic.read(frames=2)
            chunk = mic.read(frames=2)
            self.assertEqual(chunk.pcm, b'\x01\0\0\0')
            self.assertIsNone(mic.read())

    def test_no_source_fails_before_starting_a_worker(self):
        with patch.object(audio, 'audio_capabilities', return_value={'available':False,'reason':'missing'}), \
             patch.object(audio.subprocess, 'Popen') as opened:
            with self.assertRaisesRegex(audio.MicrophoneUnavailable, 'missing'):
                audio.Microphone().start()
            opened.assert_not_called()


class SupervisorTests(unittest.TestCase):
    def test_parent_sigkill_closes_control_pipe_and_restores_route(self):
        # Real processes/pipes; a fake ALSA backend supplies synthetic zero PCM.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root/'state.json'
            initial = controls()
            state.write_text(json.dumps(initial))
            helper = root/'helper.py'
            helper.write_text('''import json,os,subprocess,sys
from pathlib import Path
from torque import audio
from torque import _audio_worker as w
state=Path(sys.argv[1]);lease=Path(sys.argv[2])
class Fake:
    def __init__(self,*_): pass
    def get(self,name): return json.loads(state.read_text())[name]
    def set(self,name,value):
        data=json.loads(state.read_text());data[name]['value']=value;state.write_text(json.dumps(data))
    def idle(self): pass
    def capture(self,seconds,diagnostic):
        return subprocess.Popen([sys.executable,'-u','-c',"import os,time\\nwhile True: os.write(1,b'\\\\0'*9600);time.sleep(.02)"],stdout=subprocess.PIPE,stderr=diagnostic)
w.Alsa=Fake
w.audio_capabilities=lambda **_: {'available':True,'sources':[{'accessible':True,'card_index':0}]}
claim=w.claim;w.claim=lambda card:claim(card,lease)
raise SystemExit(w.main(['--card',audio.CARD_ID,'--seconds','30']))
''')
            parent = root/'parent.py'
            parent.write_text('''import subprocess,sys,time
p=subprocess.Popen([sys.executable,sys.argv[1],*sys.argv[2:]],stdin=subprocess.PIPE,start_new_session=True)
while True: time.sleep(1)
''')
            env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT/'packages/session/src'),str(ROOT/'packages/device/src')])}
            p = subprocess.Popen([sys.executable,str(parent),str(helper),str(state),str(root/'lease')],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
            try:
                import select
                self.assertTrue(select.select([p.stdout],[],[],5)[0], 'helper did not start')
                header = p.stdout.readline()
                self.assertTrue(json.loads(header)['ready'], header)
                self.assertNotEqual(json.loads(state.read_text()), initial)
                p.kill()
                _, errors = p.communicate(timeout=8)
                self.assertEqual(json.loads(state.read_text()), initial, errors.decode())
                os.close(worker.claim(audio.CARD_ID, root/'lease'))
            finally:
                if p.poll() is None:
                    p.kill()
                    p.communicate(timeout=8)


if __name__ == '__main__':
    unittest.main()
