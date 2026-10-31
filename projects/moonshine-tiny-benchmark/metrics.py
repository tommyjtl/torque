"""Record native events without confusing forced stop with natural finalization."""
import time


class Events:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.events = []
        self.lines = {}
        self.active = set()
        self.forcing = False
        self.errors = []

    def record(self, kind, line):
        item = {'kind': kind, 'at': self.clock(), 'text': line.text, 'line_id': line.line_id,
                'start': line.start_time, 'duration': line.duration,
                'library_latency_ms': line.last_transcription_latency_ms,
                'forced': self.forcing, 'segment_limit_suspected': line.duration >= 14.98}
        self.events.append(item)
        self.lines[line.line_id] = item
        if kind == 'started':
            self.active.add(line.line_id)
        elif kind == 'completed':
            self.active.discard(line.line_id)

    def summary(self):
        ordered = sorted(self.lines.values(), key=lambda x: (x['start'], x['line_id']))
        text = ' '.join(x['text'].strip() for x in ordered if x['text'].strip())
        completed = [e for e in self.events if e['kind'] == 'completed' and e['text'].strip()]
        valid = bool(completed) and not self.active and not self.errors and not any(
            e['forced'] or e['segment_limit_suspected'] for e in completed)
        natural = [e for e in completed if not e['forced']]
        partials = [e for e in self.events if e['kind'] == 'partial' and e['text'].strip() and not e['forced']]
        return {'text': text, 'natural_final_proven': valid,
                'natural_final_at': max(e['at'] for e in natural) if valid else None,
                'first_partial_at': min(e['at'] for e in partials) if partials else None,
                'forced_nonempty_lines': sum(e['forced'] for e in completed), 'errors': self.errors,
                'events': self.events}
