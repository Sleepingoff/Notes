"""Rebuild the bundled archive from the original 2014–2020 HWP/PDF directory.

Usage: .venv-web/bin/python tools/import_answer_archive.py SOURCE_DIRECTORY
Needs the project's vendored rhwp, Node.js and PyMuPDF. Originals are read only.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from answer_archive import AnswerArchive, DEFAULT_PATH, SYMBOL_MASKS, encode

NS = {'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph'}


def text(cell):
    return unicodedata.normalize('NFC', ''.join(cell.itertext())).strip()


def hwp_rows(path):
    with tempfile.TemporaryDirectory(prefix='answer-import-') as directory:
        target = Path(directory) / 'document.hwpx'
        script = '''import {readFileSync,writeFileSync} from 'node:fs';
import {loadRhwp} from './vendor/hwp/scripts/rhwp-init.mjs';
const {HwpDocument}=await loadRhwp();
const doc=new HwpDocument(new Uint8Array(readFileSync(process.argv[1])));
doc.convertToEditable();writeFileSync(process.argv[2],doc.exportHwpx());doc.free();'''
        subprocess.run(['node', '--input-type=module', '-e', script, str(path), str(target)], cwd=ROOT, check=True, timeout=180)
        with zipfile.ZipFile(target) as archive:
            for name in sorted(archive.namelist()):
                if not re.fullmatch(r'Contents/section\d+\.xml', name):
                    continue
                root = ET.fromstring(archive.read(name))
                for table_no, table in enumerate(root.findall('.//hp:tbl', NS), 1):
                    if table.get('colCnt') != '9':
                        continue
                    for row_no, row in enumerate(table.findall('hp:tr', NS), 1):
                        cells = {int(c.find('hp:cellAddr', NS).get('colAddr')): text(c) for c in row.findall('hp:tc', NS)}
                        if cells.get(0) == '학년' or 0 not in cells or not any(cells.values()):
                            continue
                        if cells.get(0) not in ('1', '2', '3', '4') or not cells.get(1):
                            raise ValueError(f'Unrecognized row: {path.name}: {cells}')
                        yield int(cells[0]), cells[1], [cells.get(c, '') for c in range(2, 9)], f'{name}:table{table_no}:row{row_no}'


def pdf_rows(path):
    with pymupdf.open(path) as doc:
        for page_no, page in enumerate(doc, 1):
            lines = [line.strip() for line in page.get_text().splitlines() if line.strip()]
            start = lines.index('교과목명') + 1
            # Header labels end where the first grade is immediately followed by a course name.
            while start < len(lines) and not (lines[start] in ('1', '2', '3', '4') and re.search('[가-힣]', lines[start + 1])):
                start += 1
            end = lines.index('중복정답')
            i = start
            while i < end:
                grade, subject = int(lines[i]), unicodedata.normalize('NFC', lines[i + 1])
                i += 2
                symbols = ''
                while i < end and re.fullmatch('[1-4A-K]+', lines[i]):
                    if len(symbols) == 35:
                        break
                    symbols += lines[i]
                    i += 1
                if len(symbols) != 35 or grade not in (1, 2, 3, 4):
                    raise ValueError(f'Unrecognized PDF row: {path.name}: {subject}: {symbols}')
                yield grade, subject, [symbols[n:n + 5] for n in range(0, 35, 5)], f'page{page_no}:row{subject}'


def build(source, target=DEFAULT_PATH):
    files = sorted((p for p in source.rglob('*') if p.suffix.lower() in ('.hwp', '.pdf')),
                   key=lambda p: unicodedata.normalize('NFC', str(p.relative_to(source))))
    records, sources, issues = [], [], []
    for path in files:
        relative = unicodedata.normalize('NFC', str(path.relative_to(source)))
        year = int(path.parent.name)
        name = unicodedata.normalize('NFC', path.name)
        term_match = re.search(r'([12])(?:학기|기말)', name)
        if not term_match:
            raise ValueError(f'Missing term: {name}')
        term = int(term_match[1])
        source_id = len(sources)
        sources.append({'file': relative, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        count = 0
        for grade, subject, cells, location in (hwp_rows(path) if path.suffix.lower() == '.hwp' else pdf_rows(path)):
            masks = []
            for block, value in enumerate(cells):
                value = ''.join(value.split())
                if not value:
                    masks.extend([0] * 5)
                elif len(value) == 5 and all(c in SYMBOL_MASKS for c in value):
                    masks.extend(SYMBOL_MASKS[c] for c in value)
                else:
                    masks.extend([0] * 5)
                    issues.append({'record': len(records), 'source': source_id, 'location': location,
                                   'questions': [block * 5 + 1, block * 5 + 5], 'raw': value,
                                   'reason': 'Invalid five-answer cell; retained verbatim, no answer inferred'})
            while masks and masks[-1] == 0:
                # Keep unresolved final cells as explicit unknowns.
                if any(x['record'] == len(records) and x['questions'][1] == len(masks) for x in issues):
                    break
                masks.pop()
            records.append({'year': year, 'term': term, 'grade': grade, 'subject': subject,
                            'source': source_id, 'masks': masks})
            count += 1
        print(f'{year}-{term}: {count} rows ({name})')
    if not files:
        raise ValueError('No source documents found')
    target.parent.mkdir(parents=True, exist_ok=True)
    data = encode(records, sources, issues)
    target.write_bytes(data)
    restored = AnswerArchive(target)
    assert len(restored.records) == len(records)
    for original, decoded in zip(records, restored.records):
        assert tuple(original['masks']) == decoded.masks
        assert all(original[field] == getattr(decoded, field) for field in ('year', 'term', 'grade', 'subject', 'source'))
    assert list(restored.issues) == issues
    print(json.dumps({'sources': len(files), 'rows': len(records), 'answers': sum(len(r['masks']) for r in records),
                      'multiple_answers': sum(m.bit_count() > 1 for r in records for m in r['masks']),
                      'unknown_answers': sum(m == 0 for r in records for m in r['masks']),
                      'issues': issues, 'bytes': len(data)}, ensure_ascii=False, indent=2))
    return restored


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    build(args.source, args.output)
