"""Page-level manual recovery without replacing successful pages or quiz records."""
import json
from pathlib import Path
import re


def page_folder(job, page):
    return Path(job) / f'page-{page:03d}'


def completed_page(job, page):
    folder = page_folder(job, page)
    state = folder / 'state.json'
    return (state.exists() and json.loads(state.read_text(encoding='utf-8')).get('references')
            and (folder / 'output/questions-with-images.md').exists())


def read_page(job, page):
    folder = page_folder(job, page)
    for name in ('output/questions-with-images.md', 'output/questions.md'):
        path = folder / name
        if path.exists():
            return path.read_text(encoding='utf-8')
    return ''


def validate_page(text):
    headings = list(re.finditer(r'(?m)^(\d+)[.)][ \t]+(.+)$', text))
    if not headings or text[:headings[0].start()].strip():
        raise ValueError('각 문제를 원본 번호와 함께 입력해 주세요. 예: 12) 문제 내용')
    numbers = [int(match.group(1)) for match in headings]
    if min(numbers) < 1 or len(numbers) != len(set(numbers)):
        raise ValueError('문제 번호는 양수이며 페이지 안에서 중복될 수 없습니다.')
    for i, match in enumerate(headings):
        block = text[match.end():headings[i + 1].start() if i + 1 < len(headings) else len(text)]
        choices = re.findall(r'(?m)^- \[[ xX]\][ \t]*(.*)$', block)
        if len(choices) < 2 or any(not choice.strip() for choice in choices):
            raise ValueError(f'{numbers[i]}번 문제의 보기를 두 개 이상 입력해 주세요. 예: - [ ] 보기 내용')
    return numbers


def save_page(catalog, task, page, text):
    numbers = validate_page(text)
    root = Path(task['output_path'])
    folder = page_folder(root, page)
    with catalog.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT * FROM extraction_jobs WHERE id=?', (task['id'],)).fetchone()
        if current is None:
            raise ValueError('추출 작업을 찾을 수 없습니다.')
        if current['status'] in ('queued', 'running') and not completed_page(root, page):
            raise ValueError('이 페이지를 추출 중입니다. 추출이 끝나거나 실패한 후 직접 작성해 주세요.')
        (folder / 'output').mkdir(parents=True, exist_ok=True)
        target = folder / 'output/questions-with-images.md'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(text.strip() + '\n', encoding='utf-8')
        temporary.replace(target)
        state_path = folder / 'state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        state.update(text=True, references=True, manual=True)
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(state_path)
        remaining = [n for n in range(1, current['total'] + 1) if not completed_page(root, n)]
        completed = current['total'] - len(remaining)
        if not remaining and current['status'] not in ('running', 'queued'):
            db.execute("UPDATE extraction_jobs SET status='done',completed=?,error='',error_code='',error_message='',updated_at=CURRENT_TIMESTAMP WHERE id=?", (completed, task['id']))
        elif current['status'] == 'failed':
            message = f"미완료 페이지: {', '.join(map(str, remaining))}. 직접 작성하거나 추출을 다시 시도해 주세요."
            db.execute("UPDATE extraction_jobs SET completed=?,current_page=?,error_code='INCOMPLETE_EXTRACTION',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (completed, remaining[0], message, task['id']))
        else:
            db.execute('UPDATE extraction_jobs SET completed=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (completed, task['id']))
    return numbers
