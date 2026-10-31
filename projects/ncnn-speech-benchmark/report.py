"""Generate a report from retained evidence without running a recognizer."""
import json
from pathlib import Path
import statistics
import sys


def read(path):
    return json.loads(path.read_text())


def main(root):
    runs = []
    for directory in sorted((root / 'results').iterdir()):
        if not (directory / 'result.json').is_file():
            continue
        runs.append((directory, read(directory / 'result.json'), read(directory / 'manifest.json'),
                     read(directory / 'measurements.json') if (directory / 'measurements.json').is_file() else []))
    gate = any(r['mode'] == 'probe' and r['passed'] for _, r, _, _ in runs)
    lines = ['# UNO Q ncnn GPU and streaming speech experiment', '',
             ('The real Adreno 702 passed direct Vulkan vector addition and three dense matrix tests, '
              'with zero measured error against CPU arithmetic references.' if gate else
              'The hardware calculation gate has not passed. No speech-acceleration claim is accepted.'), '',
             'The initial generic MatMul probe found no Vulkan implementation in the pinned engine. '
             'The successful matrix tests use its supported InnerProduct layer with batch inputs and '
             'explicit GPU weight upload. This is a different runtime from the earlier failed GGML experiment.', '',
             '| Run | Device / pacing / profiling | Execution / endpoint acceptance | Measured transcripts | GPU timed operators |',
             '| --- | --- | --- | --- | --- |']
    for directory, result, manifest, measured in runs:
        args = manifest.get('arguments', {})
        label = result['mode'] + (' / bulk' if args.get('bulk') else ' / paced' if result['mode'] != 'probe' else '')
        if args.get('profile'):
            label += ' / diagnostic profile'
        status = 'passed' if result['passed'] else 'not accepted; native exit ' + str(result['exit_code'])
        lines.append(f"| {directory.name} | {label} | {status} | {len(measured)} | {result.get('gpu_timed_operations', 0)} |")
    main_runs = [(d, r, m, rows) for d, r, m, rows in runs
                 if r['mode'] != 'probe' and not m['arguments'].get('bulk') and not m['arguments'].get('profile')]
    if main_runs:
        lines += ['', '## Paced streaming measurements', '',
                  'Same six hashed LibriSpeech test-clean clips as Moonshine. One excluded warm-up. '
                  'Three measured repetitions per clip for complete sweeps. Model stays loaded; '
                  'English greedy decoding, four CPU threads, FP32 compute and a 0.3-second '
                  'nonempty-utterance silence rule are used in both device modes. Audio arrives '
                  'in ordered 20 ms chunks with three seconds of trailing silence.', '',
                  '| Mode | Accepted natural finals | Median final delay | Range | Under 1 s | WER, first repetition | Peak process RSS |',
                  '| --- | --- | --- | --- | --- | --- | --- |']
        details = []
        for directory, result, manifest, rows in main_runs:
            valid = [r for r in rows if r['natural_final_proven'] and r['file_end_to_final_seconds'] is not None]
            times = [r['file_end_to_final_seconds'] for r in valid]
            first = [r for r in rows if r['repeat'] == 0]
            errors = sum(r['score']['errors'] for r in first)
            words = sum(r['score']['reference_words'] for r in first)
            median = f'{statistics.median(times):.3f} s' if times else 'not established'
            spread = f'{min(times):.3f}–{max(times):.3f} s' if times else 'none accepted'
            memory = max((r['peak_rss_kib'] for r in rows), default=0) / 1024
            accuracy = f'{errors}/{words} = {errors/words:.1%}' if words else 'not established'
            lines.append(f"| {result['mode']} | {len(valid)}/{len(rows)} | {median} | {spread} | {sum(t < 1 for t in times)}/{len(rows)} | {accuracy} | {memory:.1f} MiB |")
            details += ['', '### ' + directory.name, '', '| Clip | Duration | Median final delay | First-pass WER |',
                        '| --- | --- | --- | --- |']
            for clip in dict.fromkeys(r['clip'] for r in rows):
                selected = [r for r in rows if r['clip'] == clip]
                accepted = [r['file_end_to_final_seconds'] for r in selected if r in valid]
                delay = f'{statistics.median(accepted):.3f} s' if accepted else 'not established'
                details.append(f"| {clip} | {selected[0]['audio_seconds']:.3f} s | {delay} | {selected[0]['score']['wer']:.1%} |")
            details += ['', f"Total worker CPU time: {sum(r['cpu_seconds'] for r in rows):.2f} CPU-s; "
                        f"largest processing call: {max(r['maximum_processing_call_seconds'] for r in rows):.3f} s; "
                        f"largest scheduled-input lag: {max(r['maximum_input_lag_seconds'] for r in rows):.3f} s."] if rows else []
            ipc = read(directory / 'ipc.json')
            values = [r['ms'] for r in ipc if 'ms' in r]
            if values:
                details.append(f'Status IPC: median {statistics.median(values):.2f} ms; observed maximum {max(values):.2f} ms; {len(values)} samples.')
        lines += details
    lines += ['', '## Interpretation and limits', '',
              'Paced latency is file-end to the last natural endpoint with no pending later text; '
              'InputFinished is not called to manufacture an endpoint. There are no independently '
              'annotated human speech ends. Capture/ALSA cleanup and live microphone accuracy were '
              'not measured in this phase. A six-clip result is not a production p95 or accuracy guarantee.', '',
              'Diagnostic profiling is separate from main timings. A small private patch makes only '
              'ncnn timestamp/query/log instrumentation opt-in; it does not change tensor operations. '
              'GPU diagnostic microsecond rows come from Vulkan timestamp queries. CPU fallback '
              'millisecond rows remain distinct. GPU-enabled speech is a hybrid execution mode; '
              'an initialization message is not evidence that every operator ran on the GPU.', '',
              'CPU-s sums time across threads; process RSS excludes some driver/GPU allocations and '
              'is not whole-board memory. Backlog overlaps the final delay and must not be added '
              'to it. The endpoint rule and recognizer differ from Moonshine, so comparisons describe '
              'whole tested pipelines, not a GPU-only improvement to the Moonshine model.', '',
              'Reference inputs: LibriSpeech/OpenSLR 12, CC BY 4.0, Vassil Panayotov, Daniel Povey, '
              'Guoguo Chen and Sanjeev Khudanpur. Source/model/package pins, raw logs and result '
              'snapshots are retained. No firmware upload, service restart or microphone capture '
              'is part of this experiment.', '']
    (root / 'report.md').write_text('\n'.join(lines))
    print('\n'.join(lines))


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
