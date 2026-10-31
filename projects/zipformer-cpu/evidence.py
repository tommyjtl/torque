"""Validate CPU execution without importing GPU experiment code."""
import json


def parse_rows(text):
    values = [json.loads(line) for line in text.splitlines()]
    if any(not isinstance(value, dict) for value in values):
        raise ValueError('Native output must be JSON objects')
    return values


def cpu_completed(rows, expected):
    init = [r for r in rows if r.get('kind') == 'initialization']
    trials = [r for r in rows if r.get('kind') == 'file']
    return (len(init) == 1 and init[0].get('gpu_requested') is False
            and len(trials) == expected
            and all(r.get('natural_final_proven') is True and r.get('text', '').strip() for r in trials)
            and any(r.get('kind') == 'speech_complete' and r.get('passed') is True for r in rows))
