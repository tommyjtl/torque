"""CPU-only Moonshine Tiny Streaming; custom PCM input, no audio device access."""
import time
START = time.monotonic()
import base64
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import sys
import numpy as np
import soxr
from moonshine_voice import Transcriber, ModelArch
from moonshine_voice.transcriber import TranscriptEventListener
from common import read_wav
from metrics import Events

IMPORTED = time.monotonic()
PARENT = os.getppid()


class Listener(TranscriptEventListener):
    def __init__(self, events):
        self.events = events
    def on_line_started(self, event):
        self.events.record('started', event.line)
    def on_line_text_changed(self, event):
        self.events.record('partial', event.line)
    def on_line_completed(self, event):
        self.events.record('completed', event.line)
    def on_error(self, event):
        self.events.errors.append(str(event.error))


class Trial:
    def __init__(self, transcriber, interval, rate=16000):
        self.events = Events()
        self.stream = transcriber.create_stream(update_interval=interval)
        self.listener = Listener(self.events)
        self.stream.add_listener(self.listener)
        self.stream.start()
        self.rate = rate
        self.resampler = soxr.ResampleStream(48000, 16000, 1, dtype='float32', quality='HQ') if rate == 48000 else None
        self.input_frames = self.output_frames = 0
        self.processing = self.max_call = 0.
        self.sum = self.squares = self.peak = 0.
        self.started = time.monotonic()
        self.cpu = resource.getrusage(resource.RUSAGE_SELF)

    def add(self, samples):
        if os.getppid() != PARENT:
            raise RuntimeError('Runner exited')
        self.output_frames += len(samples)
        if self.output_frames > 40 * 16000:
            raise ValueError('Bounded audio limit exceeded')
        start = time.monotonic()
        self.stream.add_audio(samples.tolist(), 16000)
        elapsed = time.monotonic() - start
        self.processing += elapsed
        self.max_call = max(self.max_call, elapsed)

    def chunk(self, raw):
        dtype, scale = ('<i4', 2147483648.) if self.rate == 48000 else ('<i2', 32768.)
        samples = np.frombuffer(raw, dtype=dtype).astype(np.float32) / scale
        self.input_frames += len(samples)
        if self.input_frames > self.rate * 35:
            raise ValueError('Capture exceeded limit')
        self.sum += float(np.sum(samples, dtype=np.float64))
        self.squares += float(np.dot(samples, samples))
        self.peak = max(self.peak, float(np.max(np.abs(samples))) if len(samples) else 0.)
        self.add(self.resampler.resample_chunk(samples) if self.resampler else samples)
        state = self.events.summary()
        return {'natural_final_proven': state['natural_final_proven'], 'active': bool(self.events.active),
                'text': state['text'], 'event_count': len(self.events.events),
                'natural_final_at': state['natural_final_at']}

    def finish(self):
        try:
            if self.resampler:
                self.add(self.resampler.resample_chunk(np.zeros(0, dtype=np.float32), last=True))
            before_stop = self.events.summary()
            # stop() can force a final line. Mark those events before invoking it.
            self.events.forcing = True
            self.stream.stop()
            state = self.events.summary()
            usage = resource.getrusage(resource.RUSAGE_SELF)
            mean = self.sum / self.input_frames if self.input_frames else 0.
            rms = (self.squares / self.input_frames) ** .5 if self.input_frames else 0.
            return {**state, 'natural_before_stop': before_stop['natural_final_proven'],
                    'input_frames': self.input_frames, 'output_frames': self.output_frames,
                    'processing_seconds': self.processing, 'max_add_audio_seconds': self.max_call,
                    'cpu_user_seconds': usage.ru_utime - self.cpu.ru_utime,
                    'cpu_system_seconds': usage.ru_stime - self.cpu.ru_stime,
                    'peak_rss_kib': usage.ru_maxrss, 'input_mean': mean, 'input_rms': rms,
                    'input_ac_rms': max(0., rms * rms - mean * mean) ** .5, 'peak': self.peak}
        finally:
            self.stream.close()


def run_file(transcriber, interval, path, expected):
    raw = read_wav(path, expected)
    samples = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768
    trial = Trial(transcriber, interval)
    start, max_lag = time.monotonic(), 0.
    full = np.concatenate((samples, np.zeros(3 * 16000, dtype=np.float32)))
    trial.input_frames = len(full)
    trial.sum = float(np.sum(full, dtype=np.float64))
    trial.squares = float(np.dot(full, full))
    trial.peak = float(np.max(np.abs(full)))
    for position in range(0, len(full), 320):
        block = full[position:position + 320]
        target = start + (position + len(block)) / 16000
        time.sleep(max(0, target - time.monotonic()))
        max_lag = max(max_lag, time.monotonic() - target)
        trial.add(block)
    result = trial.finish()
    final = result['natural_final_at']
    duration = len(samples) / 16000
    return {**result, 'audio_seconds': duration, 'audio_started_at': start,
            'file_end_to_final_seconds': final - (start + duration) if final is not None else None,
            'first_partial_from_start_seconds': result['first_partial_at'] - start if result['first_partial_at'] is not None else None,
            'paced_input_max_lag_seconds': max_lag,
            'compute_rtf_with_trailing_silence': result['processing_seconds'] / duration,
            'reference_speech_end_latency': None,
            'reference_speech_end_note': 'File end proxy; no independent speech-end annotation'}


def main():
    transcriber = trial = None
    interval = .5
    try:
        for line in sys.stdin:
            if len(line) > 65536:
                raise ValueError('Oversized request')
            request = json.loads(line)
            op = request['op']
            if op == 'load':
                interval = request.get('interval', .5)
                options = {'return_audio_data': 'false', 'log_output_text': 'false', 'ort_providers': 'CPU',
                           'vad_window_duration': str(request.get('vad_window', .5)),
                           'decode_incomplete_lines': 'false' if request.get('final_only') else 'true'}
                start = time.monotonic()
                transcriber = Transcriber(request['model'], ModelArch.TINY_STREAMING,
                                           update_interval=interval, options=options)
                result = {'model_load_seconds': time.monotonic() - start, 'import_seconds': IMPORTED - START,
                          'options': options, 'interval': interval, 'arch': ModelArch.TINY_STREAMING.value,
                          'versions': {n: importlib.metadata.version(n) for n in ('moonshine-voice', 'numpy', 'soxr')}}
            elif op == 'file':
                result = run_file(transcriber, interval, Path(request['path']), request['sha256'])
            elif op == 'begin':
                trial = Trial(transcriber, interval, request['rate'])
                result = {'ready': True}
            elif op == 'chunk':
                result = trial.chunk(base64.b64decode(request['pcm'], validate=True))
            elif op == 'finish':
                result = trial.finish()
                trial = None
            elif op == 'close':
                return
            else:
                raise ValueError('Unknown operation')
            print(json.dumps(result), flush=True)
    finally:
        if trial:
            trial.stream.close()
        if transcriber:
            transcriber.close()


if __name__ == '__main__':
    main()
