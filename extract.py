"""문제와 참고자료 위치를 같은 응답에서 추출합니다."""
import json
import os
from pathlib import Path

import ollama
import pymupdf
from exam_info import normalize_exam
from ai_settings import load as load_ai_settings, check_model
from runtime_paths import workspace_path

from extraction_format import PROMPT, SCHEMA, CACHE_VERSION, renumber_questions, render_questions, validate_result

settings = load_ai_settings(workspace_path(Path(__file__).resolve().parent))
client = ollama.Client(host=settings['host'], timeout=600)
model_checked = False

output = Path('output')
output.mkdir(exist_ok=True)
questions = []
references = []
warnings = []
exam = {"year":0,"term":""}
with pymupdf.open('input.pdf') as document:
    page = document[0]
    rect = page.rect
    middle = (rect.x0 + rect.x1) / 2
    regions = [
        ('left', pymupdf.Rect(rect.x0, rect.y0, middle, rect.y1)),
        ('right', pymupdf.Rect(middle, rect.y0, rect.x1, rect.y1)),
    ]
    for side, region in regions:
        cache = Path(f'questions-{side}.json')
        result = None
        if cache.exists():
            try:
                cached = json.loads(cache.read_text(encoding='utf-8'))
                if cached.get('_cache_version') == CACHE_VERSION:
                    result = validate_result(cached)
                    print(f'{side}: 완료된 추출 결과 재사용', flush=True)
                else:
                    cache.unlink(missing_ok=True)
                    print(f'{side}: 이전 형식 캐시를 갱신합니다.', flush=True)
            except (ValueError, TypeError, KeyError):
                cache.unlink(missing_ok=True)
        if result is None:
            print(f'{side}: 문제와 참고자료 위치를 함께 추출 중...', flush=True)
            image = page.get_pixmap(dpi=300, clip=region, alpha=False).tobytes('png')
            if not model_checked:
                check_model(client.show(settings['model']))
                model_checked = True
            response = client.chat(
                model=settings['model'],
                messages=[{'role': 'user', 'content': PROMPT, 'images': [image]}],
                format=SCHEMA,
                options={'temperature': 0, 'num_ctx': settings['num_ctx'], 'num_predict': settings['num_predict']},
            )
            if response.get('done_reason') == 'length':
                raise RuntimeError('출력 길이 제한에 도달했습니다.')
            result = validate_result(json.loads(response['message']['content']))
            result['_cache_version'] = CACHE_VERSION
            cache.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        warnings.extend(result.get('_warnings', []))
        found = normalize_exam(result.get('exam_year'),result.get('exam_term'))
        if found['year']:
            exam['year']=found['year']
        if found['term']:
            exam['term']=found['term']
        for reference in result['references']:
            reference['id'] = side + '-' + reference['id']
            x0, y0, x1, y1 = reference['bbox']
            reference['page_bbox'] = [
                (region.x0 - rect.x0 + region.width*x0/1000)/rect.width*1000,
                (region.y0 - rect.y0 + region.height*y0/1000)/rect.height*1000,
                (region.x0 - rect.x0 + region.width*x1/1000)/rect.width*1000,
                (region.y0 - rect.y0 + region.height*y1/1000)/rect.height*1000,
            ]
            references.append(reference)
        for question in result['questions']:
            question['image_ids'] = [side + '-' + identifier for identifier in question['image_ids']]
            questions.append(question)
        print(f"{side}: 문제 {len(result['questions'])}개 완료", flush=True)

if not questions:
    raise RuntimeError('문제가 추출되지 않았습니다. 원본과 페이지 범위를 확인하세요.')
start = int(os.environ.get('QUESTION_START', questions[0]['number']))
changes = renumber_questions(questions, references, start)
if changes:
    print(f'문제 순서에 맞춰 번호 {len(changes)}개를 조정했습니다.', flush=True)
Path('question-number-map.json').write_text(json.dumps([{'number':q['number'],'source_number':q['source_number']} for q in questions],ensure_ascii=False),encoding='utf-8')
Path('extraction-warnings.json').write_text(json.dumps(warnings,ensure_ascii=False,indent=2),encoding='utf-8')
Path('blocks.json').write_text(json.dumps({'questions': questions, 'references': references, 'exam':exam}, ensure_ascii=False), encoding='utf-8')
(output / 'questions.md').write_text(render_questions(questions), encoding='utf-8')
print('문제 추출 완료', flush=True)
