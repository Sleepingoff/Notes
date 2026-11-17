"""업데이트 후 기존 작업자와 그 자식 프로세스를 종료하고 대기 작업을 재개합니다."""
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

from background_jobs import ensure_worker, list_jobs

base=Path(__file__).resolve().parent
target=str(base/'worker.py')
listing=subprocess.check_output(['ps','-axo','pid=,pgid=,command='],text=True)
stopped=0
for line in listing.splitlines():
    parts=line.strip().split(None,2)
    if len(parts)!=3:
        continue
    try:
        arguments=shlex.split(parts[2])
    except ValueError:
        continue
    if target not in arguments:
        continue
    pid,group=map(int,parts[:2])
    # 이 앱이 분리 세션으로 시작한 작업자만 종료합니다.
    if pid!=group:
        continue
    try:
        os.killpg(group,signal.SIGTERM)
        stopped+=1
    except ProcessLookupError:
        pass
if stopped:
    time.sleep(0.5)
tasks=list_jobs(base)
if any(t['status'] in ('running','queued') for t in tasks):
    ensure_worker(base)
    print('업데이트된 작업자로 대기·진행 작업을 재개합니다.')
else:
    print('작업자 업데이트 완료. 실패한 작업은 앱에서 이어서 실행을 눌러주세요.')
