"""Conservative GPU evidence checks, independent of model timing."""
import re
import json


def parse_rows(text):
    rows, errors = [], []
    for line in text.splitlines():
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError('Expected a native result object')
            rows.append(value)
        except (ValueError, TypeError) as error:
            errors.append(str(error))
    return rows, errors


def adreno_device(rows):
    return any(device.get('gpu') and 'Adreno' in device.get('description', '')
               for row in rows if row.get('kind') == 'devices'
               for device in row.get('devices', []))


def gpu_execution(rows, log, *, require_profile=False):
    selected = bool(re.search(r'whisper_backend_init_gpu: using Vulkan\d* backend', log))
    allocated = bool(re.search(r'Vulkan\d*(?:_Host)?\s+total size\s*=\s*[1-9]', log))
    lower = log.lower()
    failed = any(text in lower for text in ('failed to initialize vulkan', 'device lost',
                                           'devicelost', 'shared memory size too small'))
    times = re.findall(r'\d+ x [0-9.eE+-]+ us = ([0-9.eE+-]+) us', log)
    profile = 'Vulkan Timings:' in log and any(float(value) > 0 for value in times)
    return {'hardware_adreno_enumerated': adreno_device(rows),
            'vulkan_backend_selected': selected, 'vulkan_model_buffer': allocated,
            'gpu_kernel_timings_present': profile, 'backend_failure_seen': failed,
            'accepted': adreno_device(rows) and selected and allocated and not failed and
                        (profile or not require_profile)}
