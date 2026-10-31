"""Acceptance requires completed hardware calculations, not initialization alone."""
import json
import math


def parse_rows(text):
    rows = []
    for line in text.splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('Native output must contain JSON objects')
        rows.append(value)
    return rows


def probe_passed(rows):
    devices = [r for r in rows if r.get('kind') == 'device']
    if len(devices) != 1 or devices[0].get('hardware') is not True or 'Adreno' not in devices[0].get('name', ''):
        return False
    if not any(r.get('kind') == 'probe_complete' and r.get('passed') is True for r in rows):
        return False
    operations = [r for r in rows if r.get('kind') == 'gpu_operation']
    expected = {('BinaryOp_ADD', 32), ('InnerProduct_MATRIX', 16), ('InnerProduct_MATRIX', 32), ('InnerProduct_MATRIX', 64)}
    if len(operations) != 4 or {(r.get('operation'), r.get('k')) for r in operations} != expected:
        return False
    for row in operations:
        error = row.get('max_error')
        if (row.get('direct_vkmat') is not True or row.get('submitted') is not True or row.get('passed') is not True
                or row.get('elements', 0) <= 0 or not isinstance(error, (int, float))
                or not math.isfinite(error) or not 0 <= error <= .0002):
            return False
    return True
