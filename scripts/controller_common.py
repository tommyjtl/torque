"""Build provenance and board checks; no credentials or device writes."""
import hashlib
import os
from pathlib import Path
import platform
import re

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / 'firmware/uno-q/controller'
CACHE = ROOT / '.cache/base-controller'


def require_board():
    compatible = Path('/sys/firmware/devicetree/base/compatible')
    if (platform.system() != 'Linux' or platform.machine() != 'aarch64' or
            not compatible.exists() or b'arduino,imola' not in compatible.read_bytes().split(b'\0')):
        raise RuntimeError('Run this on an Arduino UNO Q running Linux ARM64.')


def clean_env():
    env = os.environ.copy()
    env.pop('MODULAR_API_KEY', None)
    return env


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(FIRMWARE.rglob('*')):
        relative = path.relative_to(FIRMWARE)
        if any(part.startswith('.') or part in ('build', '__pycache__') for part in relative.parts):
            continue
        if path.is_file() and path.suffix in ('.ino', '.h', '.hpp', '.c', '.cc', '.cpp', '.yaml', '.py', '.txt'):
            digest.update(relative.as_posix().encode() + b'\0')
            digest.update(path.read_bytes())
    return digest.hexdigest()


def firmware_version():
    text = (FIRMWARE / 'sketch/src/protocol.cpp').read_text()
    version = re.search(r'constexpr const char\* VERSION = "([0-9]+\.[0-9]+\.[0-9]+)";', text)
    if version is None:
        raise RuntimeError('Firmware version declaration is missing.')
    return version.group(1)
