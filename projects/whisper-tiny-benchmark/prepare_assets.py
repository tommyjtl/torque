"""Prepare a small attributed fixture pack off-board; no microphone access."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen
import wave

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    fixtures = ROOT / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    url = 'https://www.openslr.org/resources/12/test-clean.tar.gz'
    chosen, references, counts = [], {}, [0, 0, 0]
    speakers = set()
    with tempfile.TemporaryDirectory(prefix='whisper-fixtures-') as tmp, urlopen(url, timeout=60) as response:
        with tarfile.open(fileobj=response, mode='r|gz') as archive:
            for member in archive:
                if member.name.endswith('.trans.txt'):
                    for line in archive.extractfile(member).read(1024 * 1024).decode().splitlines():
                        key, text = line.split(' ', 1)
                        references[key] = text
                elif member.name.endswith('.flac'):
                    name = Path(member.name).stem
                    if not re.fullmatch(r'\d+-\d+-\d+', name) or member.size > 3 * 1024**2:
                        continue
                    speaker = name.split('-')[0]
                    source = Path(tmp) / (name + '.flac')
                    source.write_bytes(archive.extractfile(member).read())
                    output = fixtures / (name + '.wav')
                    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-ar', '16000',
                                    '-ac', '1', '-c:a', 'pcm_s16le', str(output)], check=True)
                    with wave.open(str(output)) as wav:
                        n = wav.getnframes()
                    seconds = n / 16000
                    bucket = next((i for i, (lo, hi) in enumerate(((2, 4), (5, 8), (10, 15)))
                                   if lo <= seconds <= hi), None)
                    # At most one utterance per speaker in each duration bucket.
                    if (bucket is not None and counts[bucket] < 2 and
                            not any(c['bucket'] == bucket and c['speaker'] == speaker for c in chosen)):
                        chosen.append({'id': name, 'speaker': speaker, 'bucket': bucket,
                                       'path': 'fixtures/' + output.name, 'samples': n,
                                       'seconds': seconds, 'sha256': sha(output),
                                       'source_sha256': sha(source), 'source_member': member.name})
                        counts[bucket] += 1
                        speakers.add(speaker)
                    else:
                        output.unlink()
                if counts == [2, 2, 2] and all(c['id'] in references for c in chosen):
                    break
    assert counts == [2, 2, 2] and len(speakers) >= 2, 'Fixture selection incomplete'
    for clip in chosen:
        clip['reference'] = references[clip['id']]
    (ROOT / 'fixtures.json').write_text(json.dumps({
        'source_url': url, 'corpus': 'LibriSpeech test-clean', 'license': 'CC BY 4.0',
        'attribution': 'Vassil Panayotov, Daniel Povey, Guoguo Chen and Sanjeev Khudanpur; OpenSLR SLR12 / LibriVox',
        'conversion': 'ffmpeg -ar 16000 -ac 1 -c:a pcm_s16le; complete utterances',
        'selection': 'First eligible per-speaker/duration buckets in archive order, before recognition',
        'clips': chosen}, indent=2) + '\n')
    print(json.dumps({'clips': len(chosen), 'speakers': sorted(speakers), 'durations': [c['seconds'] for c in chosen]}))


if __name__ == '__main__':
    main()
