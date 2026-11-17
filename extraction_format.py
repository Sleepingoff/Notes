"""문제를 독립 항목으로 저장하고 체크박스 Markdown으로 출력합니다."""
import math
import re

CACHE_VERSION = 3

SCHEMA = {
    'type': 'object',
    'properties': {
        'exam_year': {'type': 'integer'},
        'exam_term': {'type': 'string'},
        'questions': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'number': {'type': 'integer'},
                'stem': {'type': 'string'},
                'choices': {'type': 'array', 'items': {'type': 'string'}},
                'image_ids': {'type': 'array', 'items': {'type': 'string', 'pattern': '^img_[1-9][0-9]*$'}},
            },
            'required': ['number', 'stem', 'choices', 'image_ids'],
        }},
        'shared_passages': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'source_label': {'type': 'string'},
                'questions': {'type': 'array', 'items': {'type': 'integer'}},
                'text': {'type': 'string'},
                'image_ids': {'type': 'array', 'items': {'type': 'string', 'pattern': '^img_[1-9][0-9]*$'}},
            },
            'required': ['source_label', 'questions', 'text', 'image_ids'],
        }},
        'references': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'id': {'type': 'string', 'pattern': '^img_[1-9][0-9]*$'},
                'caption': {'type': 'string'},
                'questions': {'type': 'array', 'items': {'type': 'integer'}},
                'bbox': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
            },
            'required': ['id', 'caption', 'questions', 'bbox'],
        }},
    },
    'required': ['questions', 'references', 'shared_passages', 'exam_year', 'exam_term'],
}

PROMPT = '''
한국어 객관식 시험지의 한쪽 단 이미지입니다. 기존 문제를 원문 그대로 구조화하세요.
문제를 풀거나 정답을 추측하지 마세요. 문장을 교정·요약하거나 새 문제를 만들지 마세요.

questions의 항목 하나가 문제 하나입니다. 위에서 아래로 원문 순서대로 기록하세요.
- number: 원본 문제 번호. 새 번호를 부여하지 마세요.
- stem: 문제 번호와 선택지를 제외한 해당 문제의 지문.
- 공통 설명은 개별 문제 지문에 섞지 말고 shared_passages에만 기록하세요.
- choices: 선택지를 원문 순서대로 기록합니다. ①/②/③ 같은 선택지 앞 번호만 제외하세요.
  선택지 내용 안에 있는 도형 번호·기호·수식은 반드시 보존하세요.
  보기가 4개면 4개, 5개면 5개입니다. 누락된 보기를 새로 만들지 마세요.
- image_ids: img_1, img_2 같은 references.id만 넣습니다. 코드나 문장 자체를 절대 넣지 마세요.
  해당 문제 자체에 있는 개별 그림만 연결합니다.
  공통 그림은 shared_passages의 image_ids에만 연결하세요.

shared_passages는 공통 지문과 공통 그림을 묶는 별도 목록입니다.
- source_label: 원문 적용 범위를 그대로 복사합니다. 예: "※ (7~8)".
- questions: 해당 범위에 포함되는 문제 번호만 기록합니다.
- text: 범위 표제를 제외한 공통 설명 원문. A/B/C/D 설명문도 포함합니다.
- image_ids: 공통 그림의 references id 목록.
공통 지문이 없으면 빈 배열입니다. (7~8) 지문은 7번과 8번에만 적용하며,
9번이 바로 아래에 있어도 절대 적용하지 않습니다. 각 문제에 공통 글을 직접 복사하지 마세요.

references의 id는 반드시 img_1, img_2 형식으로 지정하세요.
references는 그림·회로도·자료 표·도표·상자 속 코드·상자 속 수식입니다.
이미지의 내부 글자·코드·수식·표는 stem/shared_text/choices에 중복 전사하지 마세요.
단, 문장 속 짧은 수식과 선택지의 수식은 텍스트로 보존하세요.
문제 지문이나 선택지 전체, 일반 문장만 있는 상자를 참고 이미지로 만들지 마세요.
공통 그림은 references에 한 번만 기록하고 shared_passages의 image_ids에 연결하세요.
각 참고자료의 questions에는 사용하는 문제 번호를 모두 넣으세요.
자료에 속한 제목·테두리·레이블을 포함하되, 문제 지문과 선택지는 영역에서 제외하세요.
bbox는 전달된 단 이미지 기준 [왼쪽, 위, 오른쪽, 아래], 0~1000 좌표입니다.
왼쪽 위=[0,0], 오른쪽 아래=[1000,1000].

학년도와 학기는 별도 exam_year와 exam_term에 기록하세요. 예: 2016, "2학기".
보이지 않으면 exam_year=0, exam_term=""입니다. 추측하지 마세요.
과목명, 학년도, 학기, 학년, 교시, 출제위원, 출제범위, 안내문, 수험자 정보는 문제 본문에서 제외하고,
머리말·꼬리말·쪽번호는 출력하지 마세요. 판독 불가 글자만 [판독 불가]로 표시하세요.
최종적으로 각 문제만 떼어 보아도 공통 지문과 그림이 함께 있어야 합니다.
'''


def validate_result(result):
    questions = result.get('questions')
    references = result.get('references')
    if not isinstance(questions, list) or not isinstance(references, list):
        raise ValueError('문제 또는 참고자료 형식이 잘못되었습니다.')
    reference_ids = set()
    for reference in references:
        identifier = reference.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in reference_ids:
            raise ValueError('참고자료 식별자가 없거나 중복되었습니다.')
        reference_ids.add(identifier)
        box = reference.get('bbox', [])
        if len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
            raise ValueError('참고자료 좌표가 잘못되었습니다.')
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
            raise ValueError(f'참고자료 좌표가 범위를 벗어났습니다: {box}')
    repair_image_links(result)
    for question in questions:
        number = question.get('number')
        if not isinstance(number, int) or number <= 0:
            raise ValueError('문제 번호가 잘못되었습니다.')
        if not isinstance(question.get('stem'), str) or not question['stem'].strip():
            raise ValueError(f'{number}번 지문이 없습니다.')
        if 'shared_text' not in question:
            question['shared_text'] = ''
        if not isinstance(question['shared_text'], str):
            raise ValueError(f'{number}번 공통 지문 형식이 잘못되었습니다.')
        choices = question.get('choices')
        if not isinstance(choices, list) or not all(isinstance(c, str) for c in choices):
            raise ValueError(f'{number}번 보기 형식이 잘못되었습니다.')
        if not isinstance(question.get('image_ids'), list):
            raise ValueError(f'{number}번 이미지 연결 형식이 잘못되었습니다.')
        unknown = set(question['image_ids']) - reference_ids
        if unknown:
            raise ValueError(f'{number}번에 존재하지 않는 이미지가 연결되었습니다: {unknown}')
        # 모델이 한쪽에만 연결을 기록해도 양쪽 정보를 합칩니다.
        for reference in references:
            if number in reference.get('questions', []) and reference['id'] not in question['image_ids']:
                question['image_ids'].append(reference['id'])
    apply_shared_passages(result)
    return result


def repair_image_links(result):
    """명시된 문제 연결로만 복구하고, 복구할 수 없는 값은 검토 정보로 남깁니다."""
    refs = result['references']
    known = {r['id'] for r in refs}
    warnings = result.setdefault('_warnings', [])
    for item in result['questions'] + result.get('shared_passages', []):
        ids = item.get('image_ids')
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError('이미지 연결은 식별자 목록이어야 합니다.')
        invalid = [i for i in ids if i not in known]
        if not invalid:
            continue
        numbers = {item['number']} if 'number' in item else set(item.get('questions', []))
        scope = explicit_range(item.get('source_label', ''))
        if scope is not None:
            numbers = scope
        candidates = [r['id'] for r in refs if numbers and numbers.issubset(set(r.get('questions', [])))]
        fixed = [i for i in ids if i in known]
        if len(candidates) == 1:
            if candidates[0] not in fixed:
                fixed.append(candidates[0])
            message = '잘못된 이미지 식별자를 명시된 문제 연결로 복구했습니다.'
        else:
            message = '존재하지 않는 이미지 식별자를 분리했습니다. 원본 참고자료를 확인해 주세요.'
        item['image_ids'] = fixed
        warning = {'questions': sorted(numbers), 'message': message, 'original_values': invalid}
        if warning not in warnings:
            warnings.append(warning)


def renumber_questions(questions, references, start=1):
    """읽기 순서대로 번호를 부여하며 원문 번호는 별도 보존합니다."""
    mapping = {}
    changes = []
    for position, question in enumerate(questions, start):
        old = question['number']
        question['source_number'] = old
        question['number'] = position
        mapping.setdefault(old, []).append(position)
        if old != position:
            changes.append({'source_number': old, 'number': position})
    # 그림 연결은 문제의 image_ids가 기준입니다. 번호 변경 후 연결표를 다시 만듭니다.
    for reference in references:
        reference['questions'] = [q['number'] for q in questions if reference['id'] in q['image_ids']]
    return changes


def explicit_range(label):
    # 원문에 적힌 범위가 모델이 반환한 문제 번호보다 우선합니다.
    label = label.replace('\\', '')
    match = re.search(r'(?<!\d)(\d{1,4})\s*[~～〜_–—-]\s*(\d{1,4})(?!\d)', label)
    if not match:
        single = re.fullmatch(r'\s*(?:※\s*)?(?:제\s*)?[([（]?\s*(\d{1,4})\s*(?:번(?:\s*문제)?)?\s*[)\]）]?\s*', label)
        return {int(single.group(1))} if single and int(single.group(1)) > 0 else None
    start, end = map(int, match.groups())
    if start > end or end - start > 500:
        raise ValueError('공통 지문의 적용 범위를 확인해야 합니다.')
    return set(range(start, end + 1))


def apply_shared_passages(result):
    groups = result.get('shared_passages')
    questions = result['questions']
    references = result['references']
    known_ids = {r['id'] for r in references}
    if groups is None:
        # 이전 형식의 캐시를 검토할 때도 명시된 범위 밖 텍스트를 차단합니다.
        for question in questions:
            scope = explicit_range(question.get('shared_text', ''))
            if scope is not None and question['number'] not in scope:
                question['shared_text'] = ''
        return
    if not isinstance(groups, list):
        raise ValueError('공통 지문 형식이 잘못되었습니다.')
    scopes = {}
    assignments = []
    for group in groups:
        label = group.get('source_label', '')
        if not isinstance(label, str) or not isinstance(group.get('text'), str):
            raise ValueError('공통 지문 원문 또는 범위 표제가 잘못되었습니다.')
        scope = explicit_range(label)
        if scope is None:
            numbers = group.get('questions')
            if not isinstance(numbers, list) or not numbers or not all(isinstance(n, int) and n > 0 for n in numbers):
                if not group['text'].strip() and not group.get('image_ids'):
                    continue
                warning = {'questions': sorted({q['number'] for q in questions}),
                           'message': '공통 지문의 적용 문제 번호가 없어 자동 연결하지 않았습니다. 원본을 확인하고 직접 수정해 주세요.',
                           'original_values': dict(group)}
                warnings = result.setdefault('_warnings', [])
                if warning not in warnings:
                    warnings.append(warning)
                continue
            scope = set(numbers)
        ids = group.get('image_ids')
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError('공통 그림 연결이 잘못되었습니다.')
        if set(ids) - known_ids:
            raise ValueError('공통 지문에 존재하지 않는 그림이 연결되었습니다.')
        for identifier in ids:
            scopes.setdefault(identifier, set()).update(scope)
        text = group['text'].strip()
        # 모델이 범위 표제를 본문에도 반복했으면 제거합니다.
        if label and text.startswith(label):
            text = text[len(label):].strip()
        assignments.append((scope, text, ids))
    for question in questions:
        number = question['number']
        # 공통 지문은 중앙 그룹 정보에서만 조립합니다.
        question['shared_text'] = ''
        question['image_ids'] = [i for i in question['image_ids'] if i not in scopes]
        texts = []
        for scope, text, ids in assignments:
            if number not in scope:
                continue
            if text and text not in texts:
                texts.append(text)
            question['image_ids'].extend(i for i in ids if i not in question['image_ids'])
        question['shared_text'] = '\n\n'.join(texts)
    for reference in references:
        if reference['id'] in scopes:
            reference['questions'] = sorted(scopes[reference['id']])


def clean_choice(text):
    # 보기 내용의 내부 기호는 보존하고, 맨 앞 선택지 번호만 정리합니다.
    return re.sub(r'^\s*(?:[①-⑳]\s*|\d+[.)]\s+)', '', text).strip()


def render_questions(questions, images=None, captions=None):
    images = images or {}
    captions = captions or {}
    sections = []
    for question in questions:
        parts = [f"{question['number']}) {question['stem'].strip()}"]
        if question['shared_text'].strip():
            parts.append(question['shared_text'].strip())
        for identifier in dict.fromkeys(question['image_ids']):
            if identifier in images:
                caption = re.sub(r'[\[\]\n]', ' ', captions.get(identifier) or '참고자료')
                parts.append(f'![{caption}]({images[identifier]})')
            else:
                parts.append(f'<!-- 참고자료:{identifier} -->')
        choices = []
        for choice in question['choices']:
            text = clean_choice(choice)
            choices.append('- [ ] ' + text.replace('\n', '\n      '))
        if choices:
            parts.append('\n'.join(choices))
        sections.append('\n\n'.join(parts))
    return '\n\n'.join(sections) + '\n'
