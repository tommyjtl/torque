"""Small, dependency-free benchmark scoring and fixture validation."""
import hashlib
import unicodedata
import wave


def words(text):
    return ''.join(c for c in text.lower() if not unicodedata.category(c).startswith('P')).split()


def score(reference, hypothesis):
    ref, hyp = words(reference), words(hypothesis)
    previous = [(i, 0, 0, i) for i in range(len(hyp) + 1)]
    for i, a in enumerate(ref, 1):
        current = [(i, 0, i, 0)]
        for j, b in enumerate(hyp, 1):
            if a == b:
                current.append(previous[j - 1])
            else:
                c, s, d, ins = previous[j - 1]
                sub = (c + 1, s + 1, d, ins)
                c, s, d, ins = previous[j]
                delete = (c + 1, s, d + 1, ins)
                c, s, d, ins = current[j - 1]
                insert = (c + 1, s, d, ins + 1)
                current.append(min(sub, delete, insert))
        previous = current
    errors, substitutions, deletions, insertions = previous[-1]
    return {'reference_words': len(ref), 'errors': errors, 'substitutions': substitutions,
            'deletions': deletions, 'insertions': insertions,
            'wer': errors / len(ref) if ref else None, 'exact': ref == hyp}


def read_wav(path, expected=None):
    if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Fixture hash mismatch')
    with wave.open(str(path)) as stream:
        if (stream.getnchannels(), stream.getframerate(), stream.getsampwidth()) != (1, 16000, 2):
            raise ValueError('Expected mono 16 kHz S16_LE WAV')
        return stream.readframes(stream.getnframes())


GUIDE = {
    '3': ('#####', '....#', '....#', '.####', '....#', '....#', '#####'),
    '2': ('#####', '....#', '....#', '#####', '#....', '#....', '#####'),
    '1': ('..#..', '.##..', '..#..', '..#..', '..#..', '..#..', '.###.'),
    'speak': ('.###.', '#...#', '#...#', '#...#', '.###.'),
    'working': ('.....', '.....', '#.#.#', '.....', '.....'),
    'done': ('.....', '....#', '#..#.', '.##..', '.....'),
}


def guide_rows(name):
    pattern = GUIDE[name]
    top = 0 if len(pattern) == 7 else 1
    rows = ['.' * 13 for _ in range(8)]
    for y, row in enumerate(pattern):
        rows[top + y] = '.' * 4 + row + '.' * 4
    return rows
