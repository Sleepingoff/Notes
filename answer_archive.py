"""Read the bundled final-exam keys without expanding them into the user database.

Each ordinary answer takes two bits. Multiple answers (and unknown cells) use
sparse four-bit masks: bit 0 = choice 1, ... bit 3 = choice 4. Nothing is inferred.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import lzma
from pathlib import Path
import struct
import unicodedata

DEFAULT_PATH = Path(__file__).resolve().parent / 'data' / 'final_answers.bin'
SYMBOL_MASKS = dict(zip('1234ABCDEFGHIJK', (1, 2, 4, 8, 3, 5, 9, 6, 10, 12, 7, 11, 13, 14, 15)))


def normalize_subject(value):
    return ''.join(unicodedata.normalize('NFC', value).split())


def pack_answers(masks):
    if not 0 <= len(masks) <= 255 or any(not 0 <= m <= 15 for m in masks):
        raise ValueError('Invalid answer masks')
    packed = bytearray((len(masks) + 3) // 4)
    exceptions = []
    for i, mask in enumerate(masks):
        if mask in (1, 2, 4, 8):
            packed[i // 4] |= (mask.bit_length() - 1) << (2 * (i % 4))
        else:
            exceptions.extend((i, mask))
    return bytes(packed) + bytes([len(exceptions) // 2]) + bytes(exceptions)


def encode(records, sources, issues):
    subjects = sorted({r['subject'] for r in records})
    subject_ids = {name: i for i, name in enumerate(subjects)}
    metadata = json.dumps({'subjects': subjects, 'sources': sources, 'issues': issues,
                           'records': len(records)}, ensure_ascii=False, separators=(',', ':')).encode()
    payload = bytearray(struct.pack('<I', len(metadata)) + metadata)
    headers, answers, exceptions = [], [], []
    for r in records:
        meta = (r['year'] - 2014) * 8 + (r['term'] - 1) * 4 + r['grade'] - 1
        if not (2014 <= r['year'] <= 2020 and r['term'] in (1, 2) and 1 <= r['grade'] <= 4):
            raise ValueError('Unsupported exam metadata')
        packed = pack_answers(r['masks'])
        size = (len(r['masks']) + 3) // 4
        headers.append(struct.pack('<HBBBB', subject_ids[r['subject']], meta, r['source'], len(r['masks']), packed[size]))
        answers.append(packed[:size])
        exceptions.append(packed[size + 1:])
    # Keep predictable metadata separate from near-random answer bits.
    payload.extend(b''.join(bytes(h[column] for h in headers) for column in range(6)))
    payload.extend(b''.join(answers))
    payload.extend(b''.join(exceptions))
    return b'AKB1' + lzma.compress(payload, preset=9 | lzma.PRESET_EXTREME)


@dataclass(frozen=True)
class AnswerKey:
    year: int
    term: int
    grade: int
    subject: str
    source: int
    masks: tuple
    issues: tuple

    def choices(self, number):
        """Return all accepted choices; an unknown answer returns an empty tuple."""
        if not 1 <= number <= len(self.masks):
            raise IndexError(number)
        return tuple(n for n in range(1, 5) if self.masks[number - 1] & (1 << (n - 1)))


class AnswerArchive:
    def __init__(self, path=DEFAULT_PATH):
        raw = Path(path).read_bytes()
        if raw[:4] != b'AKB1':
            raise ValueError('Unknown answer archive format')
        data = lzma.decompress(raw[4:])
        length, = struct.unpack_from('<I', data)
        metadata = json.loads(data[4:4 + length])
        self.sources = tuple(metadata['sources'])
        self.issues = tuple(metadata['issues'])
        by_record = {}
        for issue in self.issues:
            by_record.setdefault(issue['record'], []).append(issue)
        offset = 4 + length
        count = metadata['records']
        columns = [data[offset + c * count:offset + (c + 1) * count] for c in range(6)]
        headers = [struct.unpack('<HBBBB', bytes(column[i] for column in columns)) for i in range(count)]
        offset += count * 6
        exception_offset = offset + sum((header[3] + 3) // 4 for header in headers)
        records = []
        for i, (subject, meta, source, size, exceptions) in enumerate(headers):
            masks = [1 << ((data[offset + n // 4] >> (2 * (n % 4))) & 3) for n in range(size)]
            offset += (size + 3) // 4
            for _ in range(exceptions):
                number, mask = data[exception_offset:exception_offset + 2]
                if number >= size or mask > 15:
                    raise ValueError('Invalid exception')
                masks[number] = mask
                exception_offset += 2
            records.append(AnswerKey(2014 + meta // 8, (meta % 8) // 4 + 1, meta % 4 + 1,
                                     metadata['subjects'][subject], source, tuple(masks), tuple(by_record.get(i, ()))))
        if exception_offset != len(data):
            raise ValueError('Unexpected trailing answer data')
        self.records = tuple(records)

    def for_subject(self, subject):
        name = normalize_subject(subject)
        return tuple(sorted((r for r in self.records if normalize_subject(r.subject) == name),
                            key=lambda r: (-r.year, -r.term, r.grade)))

    def find(self, year, term, subject, grade=None):
        """Return every matching row; never silently choose an ambiguous subject."""
        return tuple(r for r in self.for_subject(subject) if r.year == year and r.term == term
                     and (grade is None or r.grade == grade))

    def tables(self, subject):
        """JSON-ready answer tables for the UI, including every accepted choice."""
        return [{'year': r.year, 'term': r.term, 'grade': r.grade, 'subject': r.subject,
                 'answers': [list(r.choices(n)) for n in range(1, len(r.masks) + 1)],
                 'issues': [{'questions': issue['questions'], 'raw': issue['raw']} for issue in r.issues]}
                for r in self.for_subject(subject)]


@lru_cache(maxsize=1)
def load_archive():
    return AnswerArchive()
