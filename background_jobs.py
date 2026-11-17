"""브라우저와 분리된 로컬 추출 작업 대기열."""
from file_lock import acquire
from runtime_paths import workspace_path, runtime_command, background_options
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from catalog import Catalog
from core import job_key
from extraction_errors import ExtractionError, failure_fields, job_record


def init_jobs(base):
    catalog = Catalog(workspace_path(base))
    with catalog.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS extraction_jobs (
            id TEXT PRIMARY KEY, material_id TEXT NOT NULL, subject_id TEXT NOT NULL,
            output_path TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
            current_page INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        db.execute('BEGIN IMMEDIATE')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(extraction_jobs)')}
        for name in ('error_code', 'error_message'):
            if name not in columns:
                db.execute(f"ALTER TABLE extraction_jobs ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    return catalog


def enqueue(base, item):
    base = Path(base).resolve()
    catalog = init_jobs(base)
    paths = [base / name for name in ('extract.py','extract_references.py','extraction_format.py','exam_info.py')]
    key = item['subject_id'][:8] + '-' + job_key(catalog.pdf_path(item).read_bytes(), paths)
    output = catalog.job_root(item['subject_id']) / key
    with catalog.connect() as db:
        db.execute('INSERT OR IGNORE INTO extraction_jobs(id,material_id,subject_id,output_path,total) VALUES(?,?,?,?,?)', (key,item['id'],item['subject_id'],str(output),item['pages']))
    ensure_worker(base)
    return get_job(base,key)


def get_job(base, identifier):
    catalog = init_jobs(base)
    with catalog.connect() as db:
        row = db.execute('SELECT * FROM extraction_jobs WHERE id=?',(identifier,)).fetchone()
        return job_record(row) if row else None


def list_jobs(base, subject=None):
    catalog = init_jobs(base)
    with catalog.connect() as db:
        if subject:
            rows = db.execute('SELECT * FROM extraction_jobs WHERE subject_id=? ORDER BY created_at,rowid',(subject,))
        else:
            rows = db.execute('SELECT * FROM extraction_jobs ORDER BY created_at,rowid')
        return [job_record(row) for row in rows]


def retry_job(base, identifier):
    catalog = init_jobs(base)
    with catalog.connect() as db:
        db.execute("UPDATE extraction_jobs SET status='queued',error='',error_code='',error_message='',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='failed'",(identifier,))
    ensure_worker(base)


def ensure_worker(base):
    base = Path(base).resolve()
    root = workspace_path(base)
    root.mkdir(exist_ok=True)
    # 이미 실행 중인 작업자는 잠금을 계속 보유합니다.
    with (root / 'worker.lock').open('a+b') as lock:
        try:
            acquire(lock)
        except BlockingIOError:
            return
    subprocess.Popen(runtime_command(base,'worker','--base',base),
                     cwd=base,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,start_new_session=os.name!='nt' and os.environ.get('NOTES_DESKTOP')!='1',**background_options())


def update_job(catalog, identifier, **values):
    allowed = {'status','completed','current_page','error','error_code','error_message'}
    if not values or set(values)-allowed:
        raise ValueError('작업 상태 변경 항목이 잘못되었습니다.')
    fields = ','.join(f'{name}=?' for name in values)
    with catalog.connect() as db:
        return db.execute(f'UPDATE extraction_jobs SET {fields},updated_at=CURRENT_TIMESTAMP WHERE id=?',(*values.values(),identifier)).rowcount


def run_stage(catalog, identifier, command, folder, log, env):
    with subprocess.Popen(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT, env=env, **background_options()) as process:
        while True:
            with catalog.connect() as db:
                active = db.execute('SELECT 1 FROM extraction_jobs WHERE id=?', (identifier,)).fetchone()
            if not active:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                return None
            try:
                return process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                continue


def process_job(base, task):
    import pymupdf
    base = Path(base)
    catalog = init_jobs(base)
    with catalog.connect() as db:
        row = db.execute('SELECT * FROM materials WHERE id=?',(task['material_id'],)).fetchone()
    if row is None:
        raise ValueError('문제은행 원본을 찾을 수 없습니다.')
    source = catalog.pdf_path(dict(row))
    root = Path(task['output_path'])
    root.mkdir(parents=True,exist_ok=True)
    completed = 0
    next_number = 1
    review_pages = []
    with pymupdf.open(source) as document:
        for number in range(1,len(document)+1):
            if not update_job(catalog,task['id'],current_page=number):
                return
            folder = root / f'page-{number:03d}'
            folder.mkdir(exist_ok=True)
            state_path = folder/'state.json'
            state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
            final = folder/'output/questions-with-images.md'
            if not (state.get('references') and final.exists()):
                single_pdf = folder/'input.pdf'
                if not single_pdf.exists():
                    with pymupdf.open() as single:
                        single.insert_pdf(document,from_page=number-1,to_page=number-1)
                        single.save(single_pdf)
                for stage, script, filename in [
                    ('text','extract.py','questions.md'),
                    ('references','extract_references.py','questions-with-images.md'),
                ]:
                    if state.get(stage) and (folder/'output'/filename).exists():
                        continue
                    log_path = folder/f'{stage}.log'
                    with log_path.open('w',encoding='utf-8') as log:
                        result = run_stage(catalog,task['id'],runtime_command(base,Path(script).stem),folder,log,{**os.environ,'QUESTION_START':str(next_number)})
                    if result is None:
                        return
                    with catalog.connect() as db:
                        if not db.execute('SELECT 1 FROM extraction_jobs WHERE id=?',(task['id'],)).fetchone():
                            return
                    if result:
                        tail = log_path.read_text(encoding='utf-8',errors='replace')[-2500:]
                        fields = failure_fields(tail, stage=stage)
                        raise ExtractionError(fields['error_code'], fields['error_message'], f'{number}페이지 처리 실패\n{tail}', page=number)
                    if not (folder/'output'/filename).exists():
                        raise ExtractionError('OUTPUT_MISSING', '추출 결과 파일이 생성되지 않았습니다. 다시 시도해 주세요.', page=number)
                    state[stage] = True
                    temporary = state_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state),encoding='utf-8')
                    temporary.replace(state_path)
            metadata=folder/'exam-metadata.json'
            if metadata.exists():
                exam=json.loads(metadata.read_text(encoding='utf-8'))
                current=dict(row)
                if not current.get('exam_year') or not current.get('exam_term'):
                    catalog.update_exam(task['material_id'],current.get('exam_year') or exam.get('year',0),current.get('exam_term') or exam.get('term',''))
                    with catalog.connect() as db:
                        row=db.execute('SELECT * FROM materials WHERE id=?',(task['material_id'],)).fetchone()
            numbers=re.findall(r'(?m)^(\d+)[.)]\s+',final.read_text(encoding='utf-8'))
            next_number = max(next_number, max(map(int,numbers),default=next_number-1)+1)
            warning_file=folder/'extraction-warnings.json'
            if warning_file.exists() and json.loads(warning_file.read_text(encoding='utf-8')):
                review_pages.append(number)
            completed += 1
            update_job(catalog,task['id'],completed=completed)
            for name in ('input.pdf','blocks.json','questions-left.json','questions-right.json','output/questions.md'):
                (folder/name).unlink(missing_ok=True)
            for path in folder.glob('*.log'):
                path.unlink(missing_ok=True)
    update_job(catalog,task['id'],status='done',error_code='',error_message='',error=('참고자료 검토 필요 페이지: '+', '.join(map(str,review_pages))) if review_pages else '')
