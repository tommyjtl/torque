"""Private CPU worker. PCM and microphone transcripts are never written to disk."""
import time
START = time.monotonic()
import base64
import importlib.metadata
import json
import os
import resource
import sys
import numpy as np
import soxr
import webrtcvad
from pywhispercpp.model import Model
from common import read_wav, join_segments

IMPORTED = time.monotonic()
PARENT = os.getppid()


class Endpoint:
    def __init__(self, rate, max_seconds=16):
        if rate not in (16000, 48000) or max_seconds not in (16, 32):
            raise ValueError('Unsupported bounded capture format')
        self.rate = rate
        self.limit = rate * max_seconds
        self.resampler = soxr.ResampleStream(48000, 16000, 1, dtype='float32', quality='HQ') if rate == 48000 else None
        self.vad = webrtcvad.Vad(2)
        self.parts, self.pending = [], np.zeros(0, dtype=np.float32)
        self.frames = self.input_frames = self.processed = self.voiced = 0
        self.first = self.last = None
        self.endpoint = False
        self.peak = 0.
        self.clipped = 0
        self.sum = self.squares = 0.

    def consume(self, raw):
        kind, scale = ('<i4', 2147483648.) if self.rate == 48000 else ('<i2', 32768.)
        data = np.frombuffer(raw, dtype=kind).astype(np.float32) / scale
        if self.input_frames + len(data) > self.limit:
            raise ValueError('PCM buffer limit exceeded')
        self.input_frames += len(data)
        self.sum += float(np.sum(data, dtype=np.float64))
        self.squares += float(np.dot(data, data))
        self.peak = max(self.peak, float(np.max(np.abs(data))) if len(data) else 0.)
        self.clipped += int(np.count_nonzero(np.abs(data) >= .999))
        self._add(self.resampler.resample_chunk(data) if self.resampler else data)
        return self.summary()

    def _add(self, data):
        self.parts.append(data)
        self.frames += len(data)
        self.pending = np.concatenate((self.pending, data))
        while len(self.pending) >= 320 and not self.endpoint:
            block, self.pending = self.pending[:320], self.pending[320:]
            pcm = (np.clip(block, -1, .999969) * 32768).astype('<i2').tobytes()
            speech = self.vad.is_speech(pcm, 16000)
            self.processed += 320
            if speech:
                self.voiced += 320
                if self.first is None:
                    self.first = self.processed - 320
                self.last = self.processed
            if self.voiced >= 3200 and self.processed - self.last >= 11200:
                self.endpoint = True

    def summary(self):
        mean = self.sum / self.input_frames if self.input_frames else 0.
        rms = (self.squares / self.input_frames) ** .5 if self.input_frames else 0.
        return {'endpoint': self.endpoint, 'has_speech': self.voiced >= 3200,
                'last_speech_sample': self.last, 'first_speech_sample': self.first,
                'input_frames': self.input_frames, 'output_frames': self.frames,
                'peak': self.peak, 'clipped_samples': self.clipped, 'input_mean': mean,
                'input_rms': rms, 'input_ac_rms': max(0., rms * rms - mean * mean) ** .5,
                'vad_voiced_seconds': self.voiced / 16000}

    def finish(self):
        if self.resampler:
            self._add(self.resampler.resample_chunk(np.zeros(0, dtype=np.float32), last=True))
        samples = np.concatenate(self.parts) if self.parts else np.zeros(0, dtype=np.float32)
        start = max(0, (self.first or 0) - 4800)
        end = self.processed if self.endpoint else len(samples)
        return np.ascontiguousarray(samples[start:end]), self.summary()


def decode(model, samples):
    start, cpu = time.monotonic(), resource.getrusage(resource.RUSAGE_SELF)
    first = []
    def callback(segment):
        if segment.text.strip() and not first:
            first.append(time.monotonic() - start)
    segments = model.transcribe(samples, new_segment_callback=callback,
        abort_callback=lambda: os.getppid() != PARENT or time.monotonic() - start > 60)
    end, usage = time.monotonic(), resource.getrusage(resource.RUSAGE_SELF)
    return {'text': join_segments(s.text for s in segments), 'decode_seconds': end - start,
            'first_output_seconds': first[0] if first else None, 'audio_seconds': len(samples) / 16000,
            'rtf': (end - start) / (len(samples) / 16000) if len(samples) else None,
            'cpu_user_seconds': usage.ru_utime - cpu.ru_utime,
            'cpu_system_seconds': usage.ru_stime - cpu.ru_stime,
            'peak_rss_kib': usage.ru_maxrss, 'final_monotonic': end}


def main():
    model = endpoint = None
    for line in sys.stdin:
        if len(line) > 65536:
            raise ValueError('Oversized request')
        request = json.loads(line)
        op = request['op']
        if op == 'load':
            start = time.monotonic()
            model = Model(request['model'], n_threads=request['threads'], language='en',
                params_sampling_strategy=0, no_context=True, temperature=0., temperature_inc=0.,
                greedy={'best_of': 1}, print_progress=False, print_realtime=False,
                print_timestamps=False, context_params={'use_gpu': False})
            reply = {'import_seconds': IMPORTED - START, 'model_load_seconds': time.monotonic() - start,
                     'backend': str(Model.system_info()),
                     'versions': {n: importlib.metadata.version(n) for n in
                                  ('pywhispercpp', 'numpy', 'soxr', 'webrtcvad-wheels')}}
        elif op == 'file':
            start = time.monotonic()
            samples = np.frombuffer(read_wav(__import__('pathlib').Path(request['path']), request.get('sha256')),
                                    dtype='<i2').astype(np.float32) / 32768
            prep = time.monotonic() - start
            reply = {**decode(model, samples), 'pcm_prepare_seconds': prep}
        elif op == 'silence':
            reply = decode(model, np.zeros(16000, dtype=np.float32))
        elif op == 'begin':
            endpoint = Endpoint(request['rate'], request.get('max_seconds', 16))
            reply = {'ready': True}
        elif op == 'chunk':
            reply = endpoint.consume(base64.b64decode(request['pcm'], validate=True))
        elif op == 'finish':
            samples, summary = endpoint.finish()
            reply = ({**decode(model, samples), **summary} if summary['has_speech'] else
                     {**summary, 'text': '', 'status': 'no_speech'})
        elif op == 'close':
            return
        else:
            raise ValueError('Unknown operation')
        print(json.dumps(reply), flush=True)


if __name__ == '__main__':
    main()
