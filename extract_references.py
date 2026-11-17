"""추가 AI 호출 없이 참고자료를 자르고 문제별 Markdown을 조립합니다."""
import json
from pathlib import Path

import pymupdf

from extraction_format import render_questions

output = Path('output')
result = json.loads(Path('blocks.json').read_text(encoding='utf-8'))
questions = result['questions']
Path('exam-metadata.json').write_text(json.dumps(result.get('exam',{}),ensure_ascii=False),encoding='utf-8')
used = {identifier for q in questions for identifier in q['image_ids']}
images = {}
captions = {}
references = []
with pymupdf.open('input.pdf') as document:
    page = document[0]
    rect = page.rect
    for reference in result['references']:
        if reference['id'] not in used:
            continue
        x0, y0, x1, y1 = reference['page_bbox']
        clip = pymupdf.Rect(
            rect.x0 + rect.width*x0/1000 - 2,
            rect.y0 + rect.height*y0/1000 - 2,
            rect.x0 + rect.width*x1/1000 + 2,
            rect.y0 + rect.height*y1/1000 + 2,
        ) & rect
        filename = f'reference-{len(references) + 1:02d}.png'
        page.get_pixmap(dpi=300, clip=clip, alpha=False).save(output / filename)
        images[reference['id']] = filename
        captions[reference['id']] = reference['caption']
        references.append({
            'id': reference['id'], 'caption': reference['caption'],
            'questions': [q['number'] for q in questions if reference['id'] in q['image_ids']],
            'page_bbox': reference['page_bbox'], 'image': filename, 'page': 1,
        })
        print(f'참고자료 저장: {filename}', flush=True)

markdown = render_questions(questions, images, captions)
if '<!-- 참고자료:' in markdown:
    raise RuntimeError('저장되지 않은 참고자료가 있습니다.')
(output / 'questions-with-images.md').write_text(markdown, encoding='utf-8')
Path('reference-regions.json').write_text(json.dumps(references, ensure_ascii=False, indent=2), encoding='utf-8')
print('문제별 Markdown 조립 완료. 추가 AI 호출 없음.', flush=True)
