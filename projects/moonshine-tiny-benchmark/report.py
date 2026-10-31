"""Summarize natural finalization measurements; no model or audio-device access."""
import json
from pathlib import Path
import statistics
import sys


def main(root):
    output = ['# UNO Q Moonshine Tiny Streaming CPU screening', '',
              'Same six hashed LibriSpeech test-clean clips as the Whisper baseline. '
              'One excluded warm-up and one measured paced replay per clip/configuration. '
              'No GPU acceleration or live microphone capture was used.', '',
              '**Latency is file-end to the last natural completed-line callback.** '
              'There are no independent human speech-end annotations. Forced-stop and '
              'suspected duration-limit completions are excluded. These six-clip screening '
              'results do not establish production accuracy or a p95 latency.', '',
              '| Update interval / VAD window | Decode incomplete lines | Median final delay | Range | Under 1 s | WER | Peak RSS |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    details = []
    for directory in sorted((root / 'results').iterdir()):
        for path in sorted(directory.glob('files-*.jsonl')):
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            manifest = json.loads(path.with_name(path.stem + '-manifest.json').read_text())
            args = manifest['arguments']
            values = [r for r in rows if r['kind'] == 'file']
            if len(values) != 6:
                continue
            valid = [r for r in values if r['natural_final_proven'] and r['file_end_to_final_seconds'] is not None]
            delays = [r['file_end_to_final_seconds'] for r in valid]
            wer = sum(r['score']['errors'] for r in values) / sum(r['score']['reference_words'] for r in values)
            label = f"{args['interval']} s / {args['vad_window']} s"
            partial = not args.get('final_only', False)
            memory = max(r['peak_rss_kib'] for r in values) / 1024
            median = f'{statistics.median(delays):.3f} s' if delays else 'not established'
            spread = f'{min(delays):.3f}–{max(delays):.3f} s' if delays else 'no accepted finals'
            output.append(f"| {label} | {partial} | {median} | {spread} | {sum(d < 1 for d in delays)}/{len(values)} | {wer:.1%} | {memory:.1f} MiB |")
            details += ['', f'## {label}; incomplete-line decoding {partial}', '',
                        '| Clip | Duration | Final delay | WER | Largest input lag |',
                        '| --- | --- | --- | --- | --- |']
            for row in values:
                delay = f"{row['file_end_to_final_seconds']:.3f} s" if row in valid else 'not accepted'
                details.append(f"| {row['clip']} | {row['audio_seconds']:.3f} s | {delay} | {row['score']['wer']:.1%} | {row['paced_input_max_lag_seconds']:.3f} s |")
            init = next(r for r in rows if r['kind'] == 'initialization')
            details += ['', f"Process/import/model to ready: {init['process_to_ready_seconds']:.3f} s; model load {init['model_load_seconds']:.3f} s."]
            calls = [r['max_add_audio_seconds'] for r in values]
            details.append(f"Largest observed blocking add-audio call: {max(calls):.3f} s. Input was preserved, with backlog measured rather than hidden by dropping samples.")
            ipc = [s['ms'] for r in rows if r['kind'] == 'ipc_under_load' for s in r['samples'] if 'ms' in s]
            if ipc:
                details.append(f"Status IPC: median {statistics.median(ipc):.2f} ms, maximum {max(ipc):.2f} ms ({len(ipc)} samples).")
    output += ['', 'The tested CPU configurations improved on the approximately 5.9-second Whisper '
               'paced-replay median, but none of these measured natural-final file-end delays met '
               'the one-second target. CPU defaults are library-managed; no unsupported thread '
               'option was supplied. Early text-change callbacks can also accompany completed '
               'clauses and are not proof of a stable whole-utterance transcript.']
    output += details
    (root / 'report.md').write_text('\n'.join(output) + '\n')
    print('\n'.join(output))


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
