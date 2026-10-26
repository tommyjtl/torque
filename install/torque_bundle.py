"""The coordinated controller identity selected by this source release."""
import re
import tomllib

FIRMWARE_VERSION = '0.4.0'
FIRMWARE_PROTOCOL = (1, 3)
SUPPORTED_CONTROLLERS = {('0.2.0', (1, 1)), ('0.3.0', (1, 2)), (FIRMWARE_VERSION, FIRMWARE_PROTOCOL)}


def application_version(root):
    with (root/'pyproject.toml').open('rb') as stream:
        version = tomllib.load(stream)['project']['version']
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Unsupported Torque application version')
    return version


def bundle_identity():
    return {'firmware': FIRMWARE_VERSION, 'protocol': list(FIRMWARE_PROTOCOL)}


def supported_controller(identity):
    return (isinstance(identity, dict) and isinstance(identity.get('protocol'), list) and
            all(type(value) is int for value in identity['protocol']) and
            (identity.get('version'), tuple(identity['protocol'])) in SUPPORTED_CONTROLLERS)
