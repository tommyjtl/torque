"""Stage one pinned English model only after the hardware calculation gate."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
from evidence import parse_rows, probe_passed

ROOT = Path(__file__).resolve().parent
MODEL = 'marcoyang/sherpa-ncnn-streaming-zipformer-20M-2023-02-17'
REVISION = '20af696d92a32438db47fb7d4bd961b36fb07021'


def main():
    gates = [p for p in (ROOT / 'results').glob('*-probe') if (p / 'result.json').is_file()]
    accepted = [p for p in gates if json.loads((p / 'result.json').read_text()).get('passed') is True
                and probe_passed(parse_rows((p / 'stdout.jsonl').read_text()))]
    if not accepted:
        raise RuntimeError('No passed hardware computation gate; model staging refused')
    url = f'https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true'
    metadata = json.load(urllib.request.urlopen(url, timeout=30))
    assert metadata['sha'] == REVISION
    assert metadata.get('cardData', {}).get('license') == 'apache-2.0'
    files = [f for f in metadata['siblings'] if f['rfilename'].endswith(('.ncnn.param', '.ncnn.bin'))
             or f['rfilename'] == 'tokens.txt']
    assert len(files) == 7 and sum(f['size'] for f in files) < 100 * 1024**2
    target = ROOT / 'models'
    target.mkdir(exist_ok=True)
    locked = {}
    for info in files:
        name = info['rfilename']
        assert Path(name).name == name
        source = f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}'
        path = target / name
        temporary = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(source, timeout=60) as response, temporary.open('wb') as output:
            size = 0
            while chunk := response.read(1024**2):
                size += len(chunk)
                if size > info['size']:
                    raise RuntimeError('Asset size limit exceeded')
                output.write(chunk)
        assert size == info['size']
        data = temporary.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if info.get('lfs'):
            assert digest == info['lfs']['sha256']
        else:
            assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == info['blobId']
        temporary.replace(path)
        locked[name] = {'sha256': digest, 'bytes': size, 'url': source}
        print('Verified model asset: ' + name, flush=True)
    header = (target / 'encoder_jit_trace-pnnx.ncnn.param').read_text().splitlines()[2]
    assert '15=1' in header, 'Model must use current Zipformer metadata version'
    (ROOT / 'model-lock.json').write_text(json.dumps({'model': MODEL, 'revision': REVISION,
        'license': 'Apache-2.0', 'gate': sorted(accepted)[-1].name,
        'files': locked, 'bytes': sum(r['bytes'] for r in locked.values())}, indent=2))
    baseline = ROOT.parent / 'moonshine-tiny-benchmark'
    fixture_manifest = json.loads((baseline / 'fixtures.json').read_text())
    for clip in fixture_manifest['clips']:
        source = baseline / clip['path']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == clip['sha256']
        destination = ROOT / clip['path']
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, destination)
    (ROOT / 'fixtures.json').write_text(json.dumps(fixture_manifest, indent=2))
    print('PINNED_ENGLISH_MODEL_AND_FIXTURES_READY', flush=True)


if __name__ == '__main__':
    main()
