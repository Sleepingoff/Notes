"""한 번에 한 PDF만 처리하는 분리 프로세스 작업자."""
import argparse
from file_lock import acquire
from runtime_paths import workspace_path
import time
import shutil
from pathlib import Path

from background_jobs import init_jobs, process_job, update_job
from extraction_errors import failure_fields


def main(base):
    catalog = init_jobs(base)
    with (workspace_path(base)/'worker.lock').open('a+b') as lock:
        try:
            acquire(lock)
        except BlockingIOError:
            return
        # 비정상 종료됐던 작업은 페이지별 완료 지점에서 재개합니다.
        with catalog.connect() as db:
            db.execute("UPDATE extraction_jobs SET status='queued' WHERE status='running'")
        while True:
            with catalog.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute("SELECT * FROM extraction_jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE extraction_jobs SET status='running',error='',error_code='',error_message='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['id'],))
            if row:
                task = dict(row)
                try:
                    process_job(base,task)
                except Exception as error:
                    update_job(catalog,task['id'],status='failed',**failure_fields(error))
                finally:
                    with catalog.connect() as db:
                        exists = db.execute('SELECT 1 FROM subjects WHERE id=?',(task['subject_id'],)).fetchone()
                    if not exists:
                        shutil.rmtree(catalog.root/'subjects'/task['subject_id'],ignore_errors=True)
            else:
                # 잠금을 유지한 채 대기하므로 화면 이동·새 등록과 종료 사이의 경합이 없습니다.
                time.sleep(1)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',required=True)
    main(Path(parser.parse_args().base).resolve())
