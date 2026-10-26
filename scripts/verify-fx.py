#!/usr/bin/env python3
"""Two small real fx requests. Never disable permission checks or print a key."""
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from fx_common import SetupError, fx_path, run_fx, saved_key, validate_key


def verify(home):
    binary = fx_path(home)
    if not binary:
        raise SetupError('fx is not installed.')
    key = saved_key(home) or validate_key(os.environ.get('MODULAR_API_KEY', ''))
    config = json.loads((home / '.fx/settings.json').read_text())
    model = config.get('models', {}).get('modular')
    with tempfile.TemporaryDirectory(prefix='fx-unoq-verify-') as tmp:
        result = run_fx(binary, ['status', '--json'], home, key, tmp, 20)
        if result.returncode:
            raise SetupError('fx status failed: ' + result.stderr[:1000])
        status = json.loads(result.stdout)
        if (status.get('model_source') != 'modular' or status.get('model') != model or
                status.get('provider_endpoint') != 'https://api.modular.com/v1'):
            raise SetupError('fx selected a different connection/model. Check FX_PROVIDER, FX_MODEL and profile overrides.')
        if status.get('permission_mode') not in ['auto', 'ask']:
            raise SetupError('Verification requires fx permission checks (auto or ask). Existing settings were preserved.')
        print('Selected: modular / ' + model + '; permissions: ' + status['permission_mode'], flush=True)
        tests = [
            ('text', 'Reply exactly MODULAR_OK. Do not use tools.'),
            ('tool', 'Use your shell tool to run exactly uname -m once, then report its output. Do not read files or environment variables or run other commands.'),
        ]
        for label, prompt in tests:
            result = run_fx(binary, ['ask', '--json', '--no-save', prompt], home, key, tmp)
            try:
                output = json.loads(result.stdout)
            except ValueError:
                raise SetupError('fx returned invalid JSON: ' + result.stderr[:1200]) from None
            if result.returncode or output.get('exit_code') != 0:
                diagnostic = output.get('error') or output.get('output') or result.stderr
                raise SetupError('fx ' + label + ' test failed: ' + str(diagnostic)[:1500])
            if label == 'text':
                if output.get('final_output', '').strip() != 'MODULAR_OK':
                    raise SetupError('The text response did not match the verification prompt.')
                print('PASS: short prompt returned MODULAR_OK', flush=True)
            else:
                calls = output.get('tool_calls', [])
                commands = [c.get('command_result', {}) for c in calls if c.get('name') == 'shell' and c.get('status') == 'success']
                if not any(c.get('command', '').strip() == 'uname -m' and c.get('exit_code') == 0 for c in commands):
                    raise SetupError('No successful uname -m shell execution was recorded.')
                if platform.machine() not in output.get('final_output', ''):
                    raise SetupError('The model did not report the expected machine architecture.')
                print('PASS: shell ran uname -m and reported ' + platform.machine(), flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(verify(Path.home()))
    except (SetupError, ValueError, OSError) as error:
        # A bad settings file is never echoed; only controlled diagnostics appear.
        message = str(error) if isinstance(error, SetupError) else type(error).__name__
        print('Verification: ' + message, file=sys.stderr)
        sys.exit(1)
