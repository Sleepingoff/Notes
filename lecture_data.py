"""강의 원본과 편집 순서를 보관하고 PDF·목차를 자동 갱신합니다."""
import hashlib
import json
import threading
import uuid

import pymupdf


class LectureStore:
    def __init__(self, catalog):
        self.catalog = catalog
        self.lock = threading.RLock()
        with catalog.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS lecture_plans (
                subject_id TEXT PRIMARY KEY REFERENCES subjects(id), sources TEXT NOT NULL
            )''')

    def _persist(self, db, subject, sources):
        db.execute('INSERT INTO lecture_plans VALUES(?,?) ON CONFLICT(subject_id) DO UPDATE SET sources=excluded.sources',
                   (subject, json.dumps(sources, ensure_ascii=False)))

    def _directory(self, subject):
        return self.catalog.root / 'subjects' / subject / 'lecture-sources'

    def _source(self, subject, identifier, data):
        directory = self._directory(subject)
        directory.mkdir(parents=True, exist_ok=True)
        name = f'{identifier}-{hashlib.sha256(data).hexdigest()[:20]}.pdf'
        path = directory / name
        if not path.exists():
            temporary = path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
            temporary.write_bytes(data)
            temporary.replace(path)
        return name

    def _load(self, subject):
        with self.catalog.connect() as db:
            if not db.execute('SELECT 1 FROM subjects WHERE id=?', (subject,)).fetchone():
                raise ValueError('과목을 먼저 선택해 주세요.')
            row = db.execute('SELECT sources FROM lecture_plans WHERE subject_id=?', (subject,)).fetchone()
        if row:
            return json.loads(row['sources'])
        sources = []
        bundle = self.catalog.bundle(subject)
        if bundle:
            with pymupdf.open(bundle['path']) as original:
                for chapter in bundle['chapters']:
                    with pymupdf.open() as pdf:
                        pdf.insert_pdf(original, from_page=chapter['start'] - 1, to_page=chapter['end'] - 1)
                        filename = self._source(subject, chapter['id'], pdf.tobytes(garbage=4, deflate=True))
                    sources.append({'chapter': chapter['id'], 'title': chapter['title'], 'included': True, 'source': filename})
        else:
            for item in self.catalog.materials(subject, 'lecture'):
                filename = self._source(subject, item['id'], self.catalog.pdf_path(item).read_bytes())
                sources.append({'chapter': item['id'], 'title': item['title'], 'included': True, 'source': filename})
        with self.catalog.connect() as db:
            self._persist(db, subject, sources)
        return sources

    @staticmethod
    def _public(sources):
        return [{key: row[key] for key in ('chapter', 'title', 'included')} for row in sources]

    def plan(self, subject):
        with self.lock:
            return self._public(self._load(subject))

    def save(self, subject, order, uploads):
        with self.lock:
            existing = {row['chapter']: row for row in self._load(subject)}
            sources, seen, uploaded = [], set(), {}
            for row in order:
                title = str(row.get('title', '')).strip()
                if not title:
                    raise ValueError('목차 이름을 입력해 주세요.')
                if 'upload' in row:
                    index = int(row['upload'])
                    if not 0 <= index < len(uploads):
                        raise ValueError('업로드한 강의자료를 확인해 주세요.')
                    identifier = uuid.UUID(row['client_id']).hex
                    source = existing.get(identifier)
                    if source is None:
                        source = {'source': self._source(subject, identifier, uploads[index])}
                    uploaded[str(index)] = identifier
                else:
                    identifier = row.get('chapter')
                    source = existing.get(identifier)
                    if source is None:
                        raise ValueError('강의자료가 변경되었습니다. 화면을 새로고침해 주세요.')
                if identifier in seen:
                    raise ValueError('같은 강의자료를 중복해서 포함할 수 없습니다.')
                seen.add(identifier)
                sources.append({'chapter': identifier, 'title': title,
                                'included': bool(row.get('included', True)), 'source': source['source']})
            if set(existing) - seen:
                raise ValueError('강의 목록이 변경되었습니다. 화면을 새로고침해 주세요.')
            parts = [{'chapter_id': row['chapter'], 'title': row['title'],
                      'path': self._directory(subject) / row['source']} for row in sources if row['included']]
            if parts:
                self.catalog.merge_lectures(subject, parts, plan=sources)
            else:
                old = self.catalog.bundle(subject)
                with self.catalog.connect() as db:
                    db.execute('DELETE FROM lecture_bundles WHERE subject_id=?', (subject,))
                    self._persist(db, subject, sources)
                if old:
                    old['path'].unlink(missing_ok=True)
            bundle = self.catalog.bundle(subject)
            return {'plan': self._public(sources), 'upload_chapters': uploaded,
                    'bundle': {k: v for k, v in bundle.items() if k != 'path'} if bundle else None}
