"""Fetch only the pinned public tiny.en weights, verifying the publisher's hash."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parent
    record = json.loads((root / 'model-lock.json').read_text())
    expected, url = record['sha256'], record['url']
    path = root / 'models/ggml-tiny.en.bin'
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix('.part')
    digest, size = hashlib.sha256(), 0
    try:
        with urlopen(url, timeout=60) as response, temporary.open('wb') as output:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 100 * 1024**2:
                    raise RuntimeError('Unexpected model size')
                digest.update(block)
                output.write(block)
        assert digest.hexdigest() == expected and size == record['bytes'], 'Model hash/size mismatch'
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    (root / 'model.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
