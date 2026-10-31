"""Summarize completed CPU measurements and GPU failures without inventing times."""
import json
from pathlib import Path
import statistics
import sys


def main(root):
    body = ['# UNO Q Whisper Vulkan experiment', '',
            '**No accepted GPU transcription timing was obtained.** The stock backend '
            'rejected the GPU at initialization. A private compatibility patch allowed '
            'model allocation, but profiled, unprofiled and conservative FP32/fusion-off '
            'inference all aborted with Vulkan device loss before a completed transcript.', '',
            'The actual Adreno 702 was selected through the Freedreno ICD. llvmpipe '
            'was excluded. Enumeration, context initialization and GPU model-buffer '
            'allocation are not treated as completed GPU inference.', '',
            '| Run | Configuration | Result | Valid measured transcripts |',
            '| --- | --- | --- | --- |']
    cpu_runs = []
    for directory in sorted((root / 'results').iterdir()):
        path = directory / 'result.json'
        if not path.exists():
            continue
        result = json.loads(path.read_text())
        manifest = json.loads((directory / 'manifest.json').read_text())
        measured = json.loads((directory / 'measurements.json').read_text())
        label = result['mode'] + (' / profile' if result['profiled'] else '')
        tuning = manifest.get('backend_tuning', {})
        if tuning:
            label += ' / ' + ', '.join(k + '=' + v for k, v in tuning.items())
        if result['mode'] == 'gpu':
            log = (directory / 'stderr.log').read_text()
            reason = 'Shared-memory initialization refused' if 'Shared memory size too small' in log else 'ErrorDeviceLost'
        else:
            reason = 'passed' if result['passed'] else 'failed'
        body.append(f"| {directory.name} | {label} | {reason} | {len(measured)} |")
        if result['mode'] == 'cpu' and result['passed'] and len(measured) == 18:
            cpu_runs.append((directory, measured))
    for directory, rows in cpu_runs:
        times = [r['seconds'] for r in rows]
        first = [r for r in rows if r['repeat'] == 0]
        errors = sum(r['score']['errors'] for r in first)
        words = sum(r['score']['reference_words'] for r in first)
        body += ['', 'Matched-build CPU control: original Tiny English weights, four threads, '
                 'one excluded warm-up and three warm repetitions for each of the same six clips.', '',
                 f'Median full decode: **{statistics.median(times):.3f} s**, range '
                 f'{min(times):.3f}–{max(times):.3f} s. Aggregate RTF: '
                 f'{sum(times)/sum(r["audio_seconds"] for r in rows):.3f}. '
                 f'WER on six unique clips: {errors}/{words} = {errors/words:.1%}. '
                 f'Peak native-process RSS: {max(r["peak_rss_kib"] for r in rows)/1024:.1f} MiB.', '',
                 '| Clip duration | CPU median decode | WER |', '| --- | --- | --- |']
        for clip in dict.fromkeys(r['clip'] for r in rows):
            selected = [r for r in rows if r['clip'] == clip]
            body.append(f"| {selected[0]['audio_seconds']:.3f} s | {statistics.median(r['seconds'] for r in selected):.3f} s | {selected[0]['score']['wer']:.1%} |")
    body += ['', 'The GPU shared-memory limit is 16 KiB **per workgroup**, not the total '
             'memory available for the model. The reviewed small IQ1 tile needs 16,512 '
             'bytes, while the conservative F16 check needs 4,224 bytes. The private '
             'patch disables unsupported dtypes and adds CPU scheduling fallback; it '
             'does not raise the hardware limit or alter shader/model bytes.', '',
             'A 140 MB generated C++ shader-literal file exceeded build memory with '
             'parallel compilation. Large literal arrays were instead embedded from '
             'their original SPIR-V files, with per-array SHA-256 identity checks and '
             'a native link/byte test. This is build packaging, not a math optimization.', '',
             'No microphone was opened. This experiment does not demonstrate '
             'sub-one-second final speech recognition or a GPU speedup. Further GPU '
             'work requires backend/driver kernel compatibility debugging, rather '
             'than changing MCU firmware or merely enabling a GPU option.', '']
    (root / 'report.md').write_text('\n'.join(body))
    print('\n'.join(body))


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
