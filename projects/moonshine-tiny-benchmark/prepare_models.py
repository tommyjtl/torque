"""Download the explicitly selected Tiny Streaming assets into this project."""
import hashlib
import json
from pathlib import Path
from moonshine_voice import ModelArch
from moonshine_voice.download import get_model_for_language


def main():
    root = Path(__file__).resolve().parent
    expected = json.loads((root / 'model-lock.json').read_text())
    path, arch = get_model_for_language('en', ModelArch.TINY_STREAMING, cache_root=root / 'models')
    assert arch == ModelArch.TINY_STREAMING
    for name, value in expected['files'].items():
        data = (root / 'models' / name).read_bytes()
        assert len(data) == value['bytes'] and hashlib.sha256(data).hexdigest() == value['sha256'], name
    expected['model_path'] = str(path)
    (root / 'model-lock.json').write_text(json.dumps(expected, indent=2) + '\n')


if __name__ == '__main__':
    main()
