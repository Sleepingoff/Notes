"""과목 및 PDF 등록 정보를 로컬에 보관합니다."""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import shutil
import uuid
from pathlib import Path

import pymupdf

from exam_info import detect_exam, normalize_exam


class Catalog:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'catalog.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS subjects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS lecture_bundles (
                    subject_id TEXT PRIMARY KEY REFERENCES subjects(id),
                    filename TEXT NOT NULL, pages INTEGER NOT NULL,
                    chapters TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS materials (
                    id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES subjects(id),
                    kind TEXT NOT NULL CHECK(kind IN ('lecture','bank')),
                    title TEXT NOT NULL, filename TEXT NOT NULL,
                    digest TEXT NOT NULL, pages INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(subject_id, kind, digest)
                );
            ''')

        with self.connect() as db:
            columns={row['name'] for row in db.execute('PRAGMA table_info(materials)')}
            if 'source_digest' not in columns:
                db.execute("ALTER TABLE materials ADD COLUMN source_digest TEXT NOT NULL DEFAULT ''")
                db.execute("UPDATE materials SET source_digest=digest WHERE source_digest=''")
            if 'exam_year' not in columns:
                db.execute('ALTER TABLE materials ADD COLUMN exam_year INTEGER NOT NULL DEFAULT 0')
            if 'exam_term' not in columns:
                db.execute("ALTER TABLE materials ADD COLUMN exam_term TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def subjects(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM subjects ORDER BY created_at, rowid')]

    def add_subject(self, name):
        name = name.strip()
        if not name:
            raise ValueError('과목명을 입력해 주세요.')
        identifier = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute('INSERT INTO subjects(id,name) VALUES(?,?)', (identifier, name))
        except sqlite3.IntegrityError as error:
            raise ValueError('같은 이름의 과목이 이미 있습니다.') from error
        return identifier

    def rename_subject(self, identifier, name):
        name = name.strip()
        if not name:
            raise ValueError('과목명을 입력해 주세요.')
        try:
            with self.connect() as db:
                if not db.execute('UPDATE subjects SET name=? WHERE id=?', (name, identifier)).rowcount:
                    raise ValueError('과목을 찾을 수 없습니다.')
        except sqlite3.IntegrityError as error:
            raise ValueError('같은 이름의 과목이 이미 있습니다.') from error

    def delete_subject(self, identifier):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM subjects WHERE id=?', (identifier,)).fetchone():
                raise ValueError('과목을 찾을 수 없습니다.')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            running = 'extraction_jobs' in tables and db.execute(
                "SELECT 1 FROM extraction_jobs WHERE subject_id=? AND status='running'", (identifier,)).fetchone()
            if 'practice_attempts' in tables and 'practice_rounds' in tables:
                db.execute('DELETE FROM practice_attempts WHERE round_id IN (SELECT id FROM practice_rounds WHERE material IN (SELECT id FROM materials WHERE subject_id=?))', (identifier,))
            for table in ('answer_keys', 'quiz_attempts', 'practice_rounds', 'practice_migrations', 'explanations', 'explanation_notes'):
                if table in tables:
                    db.execute(f'DELETE FROM {table} WHERE material IN (SELECT id FROM materials WHERE subject_id=?)', (identifier,))
            for table, field in (('extraction_jobs', 'subject_id'), ('page_annotations', 'subject'),
                                 ('lecture_plans', 'subject_id'), ('lecture_bundles', 'subject_id'), ('materials', 'subject_id')):
                if table in tables:
                    db.execute(f'DELETE FROM {table} WHERE {field}=?', (identifier,))
            db.execute('DELETE FROM subjects WHERE id=?', (identifier,))
        directory = self.root / 'subjects' / identifier
        try:
            if directory.exists():
                shutil.rmtree(directory)
        except OSError:
            # An active worker also removes any remaining files when cancellation completes.
            if not running:
                raise

    def materials(self, subject, kind):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM materials WHERE subject_id=? AND kind=? ORDER BY position, created_at, rowid', (subject, kind))]

    def pdf_path(self, item):
        return self.root / 'subjects' / item['subject_id'] / 'pdfs' / (item['digest'] + '.pdf')

    def job_root(self, subject):
        return self.root / 'subjects' / subject / 'jobs'

    def register(self, subject, kind, filename, data, source_digest=None):
        if kind not in ('lecture', 'bank'):
            raise ValueError('자료 종류가 잘못되었습니다.')
        with pymupdf.open(stream=data, filetype='pdf') as pdf:
            if pdf.needs_pass or len(pdf) == 0:
                raise ValueError('암호가 없고 페이지가 있는 PDF를 등록해 주세요.')
            pages = len(pdf)
            exam = detect_exam(pdf[0].get_text())
        digest = hashlib.sha256(data).hexdigest()
        source_digest = source_digest or digest
        with self.connect() as db:
            if not db.execute('SELECT id FROM subjects WHERE id=?', (subject,)).fetchone():
                raise ValueError('과목을 먼저 선택해 주세요.')
            existing = db.execute('SELECT * FROM materials WHERE subject_id=? AND kind=? AND (digest=? OR source_digest=?)', (subject,kind,digest,source_digest)).fetchone()
            if existing:
                return dict(existing), False
            position = db.execute('SELECT COALESCE(MAX(position),0)+1 FROM materials WHERE subject_id=? AND kind=?', (subject,kind)).fetchone()[0]
            item = {'id': uuid.uuid4().hex, 'subject_id':subject, 'kind':kind,
                    'title':Path(filename).stem, 'filename':Path(filename).name,
                    'digest':digest, 'pages':pages, 'position':position, 'exam_year':exam['year'], 'exam_term':exam['term'],'source_digest':source_digest}
            path = self.pdf_path(item)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(data)
            db.execute('INSERT INTO materials(id,subject_id,kind,title,filename,digest,pages,position,exam_year,exam_term,source_digest) VALUES(:id,:subject_id,:kind,:title,:filename,:digest,:pages,:position,:exam_year,:exam_term,:source_digest)', item)
            return item, True

    def bundle(self, subject):
        with self.connect() as db:
            row = db.execute('SELECT * FROM lecture_bundles WHERE subject_id=?',(subject,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['chapters'] = json.loads(result['chapters'])
        result['path'] = self.root/'subjects'/subject/result['filename']
        return result

    def merge_lectures(self, subject, sources, plan=None):
        if not sources:
            raise ValueError('병합할 강의자료를 선택해 주세요.')
        old = self.bundle(subject)
        chapters = []
        with pymupdf.open() as merged:
            for source in sources:
                title = source['title'].strip()
                if not title:
                    raise ValueError('목차 이름을 입력해 주세요.')
                document = pymupdf.open(stream=source['data'],filetype='pdf') if 'data' in source else pymupdf.open(source['path'])
                with document:
                    if document.needs_pass:
                        raise ValueError('암호가 걸린 PDF는 병합할 수 없습니다.')
                    first = source.get('first',0)
                    last = source.get('last',len(document)-1)
                    if not 0 <= first <= last < len(document):
                        raise ValueError('병합할 페이지 범위가 잘못되었습니다.')
                    start = len(merged)+1
                    merged.insert_pdf(document,from_page=first,to_page=last)
                    chapters.append({'id':source.get('chapter_id') or uuid.uuid4().hex,'title':title,'start':start,'end':len(merged)})
            merged.set_toc([[1,c['title'],c['start']] for c in chapters])
            data = merged.tobytes(garbage=4,deflate=True)
        directory=self.root/'subjects'/subject
        directory.mkdir(parents=True,exist_ok=True)
        filename='lectures-'+hashlib.sha256(data).hexdigest()[:20]+'.pdf'
        path=directory/filename
        if not path.exists():
            temporary=path.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(path)
        with self.connect() as db:
            db.execute('INSERT INTO lecture_bundles(subject_id,filename,pages,chapters) VALUES(?,?,?,?) ON CONFLICT(subject_id) DO UPDATE SET filename=excluded.filename,pages=excluded.pages,chapters=excluded.chapters', (subject,filename,chapters[-1]['end'],json.dumps(chapters,ensure_ascii=False)))
            if plan is not None:
                db.execute('INSERT INTO lecture_plans VALUES(?,?) ON CONFLICT(subject_id) DO UPDATE SET sources=excluded.sources', (subject,json.dumps(plan,ensure_ascii=False)))
        if old and old['path'] != path:
            old['path'].unlink(missing_ok=True)
        return self.bundle(subject)

    def update_exam(self, material, year, term):
        exam=normalize_exam(year,term)
        with self.connect() as db:
            db.execute('UPDATE materials SET exam_year=?,exam_term=? WHERE id=?',(exam['year'],exam['term'],material))
