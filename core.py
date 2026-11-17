import hashlib
import io
import re
import zipfile


def job_key(pdf, scripts):
    digest = hashlib.sha256(pdf)
    for script in scripts:
        digest.update(script.read_bytes())
    return digest.hexdigest()[:20]


def prefix_links(text, prefix):
    def replace(match):
        target = match.group(1)
        if target.startswith(('#', '/')) or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
            return match.group(0)
        return f']({prefix}/{target})'
    return re.sub(r'\]\(([^)\n]+)\)', replace, text)


def safe_image(folder, target):
    root = folder.resolve()
    path = (root / target).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
        return None
    return path if path.is_file() else None


def question_span(text, number):
    matches=list(re.finditer(r'(?m)^(\d+)[.)]\s+.+$',text))
    found=[i for i,match in enumerate(matches) if int(match.group(1))==number]
    if len(found)!=1:
        raise ValueError('수정할 문제를 하나로 찾을 수 없습니다. 전체 페이지를 확인해 주세요.')
    index=found[0]
    return matches[index].start(), matches[index+1].start() if index+1<len(matches) else len(text)


def replace_question(text, number, replacement):
    headings=list(re.finditer(r'(?m)^(\d+)[.)]\s+.+$',replacement))
    if len(headings)!=1 or int(headings[0].group(1))!=number:
        raise ValueError('문제 번호를 유지하고 한 문제만 입력해 주세요.')
    start,end=question_span(text,number)
    return text[:start]+replacement.strip()+'\n\n'+text[end:]


def export_zip(job, pages):
    buffer = io.BytesIO()
    combined = []
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for number in pages:
            folder = job / f'page-{number:03d}' / 'output'
            path = folder / 'questions-with-images.md'
            if not path.exists():
                continue
            text = path.read_text(encoding='utf-8')
            prefix = f'page-{number:03d}'
            combined.append(prefix_links(text, prefix))
            # 실제 Markdown이 참조한 이미지만 ZIP에 포함합니다.
            seen = set()
            for target in re.findall(r'!\[[^\]]*\]\(([^)\n]+)\)', text):
                image = safe_image(folder, target)
                if image is not None and image not in seen:
                    archive.write(image, f'{prefix}/{target}')
                    seen.add(image)
        archive.writestr('questions-all.md', '\n\n'.join(combined))
    return buffer.getvalue()
