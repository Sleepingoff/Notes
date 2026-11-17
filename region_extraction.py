"""Re-extract one explicitly selected problem, using user-selected image regions."""
import json
import math
from pathlib import Path
import uuid

import ollama
import pymupdf

from ai_settings import load, check_model
from extraction_format import render_questions

SCHEMA = {'type': 'object', 'properties': {'stem': {'type': 'string'}, 'shared_text': {'type': 'string'},
          'choices': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['stem', 'shared_text', 'choices']}
PROMPT = '''첫 이미지는 사용자가 지정한 객관식 문제 한 개의 영역입니다. 원문 그대로 추출하세요.
문제를 풀거나 정답을 추측하거나 문장을 교정하지 마세요. 문제 번호는 제외하고 stem에 지문을 기록하세요.
choices에는 보기 번호만 제외한 원문 보기를 순서대로 기록하세요. 누락된 보기를 만들어 내지 마세요.
공통 설명이 이 영역에 명확히 있으면 shared_text에 기록하고 없으면 빈 문자열을 기록하세요.
두 번째 이미지부터는 사용자가 직접 지정한 참고 그림, 표, 코드의 영역입니다.
이 이미지의 내용은 별도로 삽입되므로 stem/shared_text/choices에 중복 전사하지 마세요.
학년도, 학기, 과목명, 쪽번호와 머리말은 제외하세요. 판독 불가 부분만 [판독 불가]로 표시하세요.'''


def validate_box(box):
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box):
        raise ValueError('선택 영역의 좌표를 확인해 주세요.')
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        raise ValueError('선택 영역은 페이지 안에서 왼쪽 위부터 오른쪽 아래 순서여야 합니다.')
    return box


def extract(pdf_path, page, number, problem_box, image_boxes, output, workspace):
    validate_box(problem_box)
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= 10000:
        raise ValueError('추출할 문제 번호를 확인해 주세요.')
    if not isinstance(image_boxes, list) or len(image_boxes) > 16:
        raise ValueError('이미지 영역은 최대 16개까지 지정할 수 있습니다.')
    for box in image_boxes:
        validate_box(box)
    images = []
    with pymupdf.open(pdf_path) as doc:
        if not 1 <= page <= len(doc):
            raise ValueError('페이지 범위를 확인해 주세요.')
        source = doc[page - 1]
        def crop(box):
            x0, y0, x1, y1 = box
            r = source.rect
            clip = pymupdf.Rect(r.x0 + r.width*x0/1000, r.y0 + r.height*y0/1000,
                                r.x0 + r.width*x1/1000, r.y0 + r.height*y1/1000)
            return source.get_pixmap(dpi=240, clip=clip, alpha=False).tobytes('png')
        problem = crop(problem_box)
        images = [crop(box) for box in image_boxes]
    settings = load(workspace)
    client = ollama.Client(host=settings['host'], timeout=600)
    check_model(client.show(settings['model']))
    response = client.chat(model=settings['model'], messages=[{'role': 'user', 'content': PROMPT, 'images': [problem, *images]}],
                           format=SCHEMA, options={'temperature': 0, 'num_ctx': settings['num_ctx'], 'num_predict': settings['num_predict']})
    if response.get('done_reason') == 'length':
        raise ValueError('추출 결과가 출력 길이를 초과했습니다. 문제 영역을 좁혀 다시 시도해 주세요.')
    result = json.loads(response['message']['content'])
    if not isinstance(result.get('stem'), str) or not result['stem'].strip():
        raise ValueError('문제 지문을 읽지 못했습니다. 문제 영역을 다시 지정해 주세요.')
    if not isinstance(result.get('shared_text'), str):
        raise ValueError('공통 지문 형식을 확인하지 못했습니다. 다시 추출해 주세요.')
    if not isinstance(result.get('choices'), list) or len(result['choices']) < 2 or not all(isinstance(choice, str) and choice.strip() for choice in result['choices']):
        raise ValueError('보기를 읽지 못했습니다. 지문과 보기를 포함하도록 문제 영역을 지정해 주세요.')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = [f'region-{uuid.uuid4().hex}.png' for _ in images]
    mapping = {f'manual_{i}': name for i, name in enumerate(names)}
    question = {'number': number, 'stem': result['stem'], 'shared_text': result['shared_text'],
                'choices': result['choices'], 'image_ids': list(mapping)}
    written = []
    try:
        for name, image in zip(names, images):
            target = output / name
            target.write_bytes(image)
            written.append(target)
        return {'number': number, 'text': render_questions([question], mapping), 'images': names}
    except Exception:
        for target in written:
            target.unlink(missing_ok=True)
        raise
