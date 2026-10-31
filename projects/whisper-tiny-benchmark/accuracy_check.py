"""Recheck fixed-clip WER after preserving stripped segment word boundaries."""
import hashlib
import json
from pathlib import Path
import time
from common import score
from runner import ROOT, Worker, status


def main():
    before = status()
    if before['active'] or before['pending'] or before['maintenance'] or before['device']['owner']:
        raise RuntimeError('Torque is busy; nothing was cancelled')
    clips = json.loads((ROOT / 'fixtures.json').read_text())['clips']
    model = json.loads((ROOT / 'model-lock.json').read_text())
    assert hashlib.sha256((ROOT / 'models/ggml-tiny.en.bin').read_bytes()).hexdigest() == model['sha256']
    output = ROOT / 'results' / (time.strftime('%Y%m%dT%H%M%S') + '-accuracy-correction')
    output.mkdir(parents=True, mode=0o700)
    (output / '.keep').touch()
    (output / 'manifest.json').write_text(json.dumps({
        'purpose': 'Segment-boundary accuracy correction; earlier timing records remain unchanged',
        'fixtures': clips, 'model': model, 'repeats': 1,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (ROOT / 'common.py', ROOT / 'worker.py', Path(__file__))}}, indent=2))
    rows = []
    for threads in (2, 4):
        worker = Worker(threads, output / f'threads-{threads}.stderr.log')
        try:
            worker.call('file', path=str(ROOT / clips[0]['path']), sha256=clips[0]['sha256'])
            for clip in clips:
                row = worker.call('file', path=str(ROOT / clip['path']), sha256=clip['sha256'])
                row.update(threads=threads, clip=clip['id'], reference=clip['reference'],
                           score=score(clip['reference'], row['text']))
                rows.append(row)
                (output / 'measurements.json').write_text(json.dumps(rows, indent=2))
                print(json.dumps({'threads': threads, 'clip': clip['id'], 'score': row['score']}), flush=True)
        finally:
            worker.close()
    after = status()
    passed = (before['epoch'] == after['epoch'] and before['release_id'] == after['release_id'] and
              before['device']['snapshot']['boot_id'] == after['device']['snapshot']['boot_id'] and
              after['device']['ready'])
    (output / 'completed.json').write_text(json.dumps({'passed': passed, 'accuracy_only': True}))
    assert passed
    print('RESULT_DIRECTORY: ' + str(output), flush=True)


if __name__ == '__main__':
    main()
