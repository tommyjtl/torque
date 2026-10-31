"""Summarize saved measurements without loading a recognizer or microphone."""
import json
from pathlib import Path
import statistics
import sys


def main(root):
    output = ['# UNO Q Whisper tiny.en measurements', '',
              'CPU-only prebuilt pywhispercpp 1.5.1, original Tiny English weights. '
              'Six complete LibriSpeech test-clean utterances from two speakers; this is a small smoke test.', '']
    for directory in sorted((root / 'results').iterdir()):
        if not (directory / 'completed.json').exists():
            continue
        if (directory / 'measurements.json').exists():
            rows = json.loads((directory / 'measurements.json').read_text())
            output += ['## ' + directory.name, '',
                       'Corrected segment joining; one new accuracy pass per clip and thread setting. '
                       'Historical timing measurements are unchanged.', '',
                       '| Threads | Word errors / reference words | Corrected WER |', '| --- | --- | --- |']
            for threads in (2, 4):
                selected = [r for r in rows if r['threads'] == threads]
                errors = sum(r['score']['errors'] for r in selected)
                words = sum(r['score']['reference_words'] for r in selected)
                output.append(f'| {threads} | {errors}/{words} | {errors/words:.1%} |')
            output += ['']
            continue
        rows = [json.loads(line) for line in (directory / 'metrics.jsonl').read_text().splitlines()]
        output += ['## ' + directory.name, '']
        invalid_accuracy = (directory / 'accuracy-note.json').exists()
        if invalid_accuracy:
            output += ['Historical WER is invalid: stripped segment texts were joined without spaces. '
                       'Raw results are preserved; see the separate corrected accuracy pass. Latency remains valid.', '']
        files = [r for r in rows if r['kind'] == 'file']
        if files:
            output += ['| Threads | Warm median / range (s) | Aggregate RTF | WER, six unique clips | Worker peak RSS (MiB) |',
                       '| --- | --- | --- | --- | --- |']
            for threads in (2, 4):
                selected = [r for r in files if r['threads'] == threads]
                times = [r['decode_seconds'] for r in selected]
                first = [r for r in selected if r['repeat'] == 0]
                wer = sum(r['score']['errors'] for r in first) / sum(r['score']['reference_words'] for r in first)
                rtf = sum(times) / sum(r['audio_seconds'] for r in selected)
                rss = max(r['peak_rss_kib'] for r in selected) / 1024
                accuracy = 'invalid (segment join)' if invalid_accuracy else f'{wer:.1%}'
                output.append(f'| {threads} | {statistics.median(times):.3f} / {min(times):.3f}–{max(times):.3f} | {rtf:.3f} | {accuracy} | {rss:.1f} |')
            output += ['', 'Warm inference excludes model initialization; three repetitions per utterance. '
                       'WER uses the first repetition of each unique clip, not repeated copies as independent speech.', '',
                       '| Threads | Clip duration (s) | Warm median (s) | WER |', '| --- | --- | --- | --- |']
            for threads in (2, 4):
                for clip in dict.fromkeys(r['clip'] for r in files):
                    selected = [r for r in files if r['threads'] == threads and r['clip'] == clip]
                    accuracy = 'invalid (segment join)' if invalid_accuracy else f"{selected[0]['score']['wer']:.1%}"
                    output.append(f"| {threads} | {selected[0]['audio_seconds']:.3f} | {statistics.median(r['decode_seconds'] for r in selected):.3f} | {accuracy} |")
            for row in rows:
                if row['kind'] == 'initialization':
                    output.append(f"\n{row['threads']} threads: imports {row['import_seconds']:.3f}s; model load {row['model_load_seconds']:.3f}s; process to ready {row['process_start_to_ready_seconds']:.3f}s.")
                if row['kind'] == 'silence':
                    output.append(f"\n{row['threads']}-thread silence control returned: {row['text']!r}.")
        for kind in ('replay', 'microphone'):
            selected = [r for r in rows if r['kind'] == kind]
            if selected:
                output += ['', '| Trial | Endpoint to final (s) | VAD estimated end to final (s) | WER |', '| --- | --- | --- | --- |']
                for row in selected:
                    def value(name):
                        if row.get('truncated'):
                            return 'not established (truncated)'
                        number = row.get(name)
                        return 'unavailable' if number is None else f'{number:.3f}'
                    wer = row['score']['wer'] if not row.get('truncated') else None
                    accuracy = 'invalid (segment join)' if invalid_accuracy else f'{wer:.1%}' if wer is not None else 'not scored'
                    output.append(f"| {row.get('clip', row.get('prompt_id'))} | {value('endpoint_to_final_seconds')} | {value('vad_estimated_end_to_final_seconds')} | {accuracy} |" if wer is not None else '| Incomplete/no accepted utterance | not established | not established | not scored |')
                output += ['', 'VAD-estimated end is not an independently annotated human speech end. '
                           'Live audio-clock anchoring uses PCM arrival; transport/buffer delay is not independently measured. '
                           'Microphone samples and transcript text are not saved in these results.']
                if any(r.get('truncated') for r in selected):
                    output += ['', 'Truncated listening windows are excluded from recognition-quality and post-speech latency conclusions.']
        for row in rows:
            if row['kind'] in ('ipc_baseline', 'ipc_under_load'):
                values = [s['ms'] for s in row['samples'] if 'ms' in s]
                if values:
                    output.append(f"\n{row['kind']} ({row.get('threads', 'baseline')}): {len(values)} status IPC samples; median {statistics.median(values):.2f}ms, maximum {max(values):.2f}ms.")
        output += ['']
    output += ['## Interpretation', '',
               'A completed run establishes measurement and cleanup, not acceptable voice-interface latency. '
               'Compare total post-speech delay against the one-second target, including endpoint silence and capture cleanup. '
               'No automatic board commands or cloud inference are part of this benchmark.', '']
    (root / 'report.md').write_text('\n'.join(output))
    print('\n'.join(output))


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
