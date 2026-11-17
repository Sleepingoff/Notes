"""시험 출처 정보는 문제 본문과 분리합니다."""
import re


def normalize_exam(year=0, term=''):
    try:
        year=int(year)
    except (ValueError,TypeError):
        year=0
    if not 1900 <= year <= 2100:
        year=0
    term=str(term).strip()
    if re.fullmatch(r'[12](?:\s*학기)?',term):
        term=term[0]+'학기'
    elif term not in ('하계','동계','계절학기'):
        term=''
    return {'year':year,'term':term}


def detect_exam(text):
    year=re.search(r'(19\d{2}|20\d{2}|2100)\s*(?:학년도|년도|년)',text)
    term=re.search(r'([12])\s*학기',text)
    return normalize_exam(year.group(1) if year else 0,term.group(1) if term else '')
