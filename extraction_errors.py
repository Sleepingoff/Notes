"""추출 오류의 상세 로그와 화면에 표시할 코드·안내를 분리합니다."""
import json
import re


class ExtractionError(RuntimeError):
    def __init__(self, code, message, detail='', page=None):
        self.code = code
        self.message = message
        self.page = page
        super().__init__(detail or message)


def failure_fields(error, *, stage=None, page=None):
    detail = str(error)
    text = f'{type(error).__name__}: {detail}'.lower()
    if isinstance(error, ExtractionError):
        code, message = error.code, error.message
        page = error.page or page
    elif 'modulenotfounderror' in text or 'no module named' in text or isinstance(error, ImportError):
        code, message = 'DEPENDENCY_MISSING', '필요한 Python 패키지가 없습니다. requirements-web.txt의 패키지를 설치해 주세요.'
    elif ('model' in text and ('not found' in text or 'does not exist' in text)):
        code, message = 'MODEL_NOT_FOUND', '설정한 추출 모델이 없습니다. AI 설정의 모델 이름과 ollama list 결과를 확인해 주세요.'
    elif any(value in text for value in ('connection refused', 'failed to connect', 'connecterror', 'connectionerror', 'ollama is running')) or isinstance(error, ConnectionError):
        code, message = 'OLLAMA_UNAVAILABLE', 'Ollama에 연결할 수 없습니다. Ollama를 실행한 뒤 다시 시도해 주세요.'
    elif any(value in text for value in ('out of memory', 'requires more system memory', 'cannot allocate memory', 'memoryerror')) or isinstance(error, MemoryError):
        code, message = 'OUT_OF_MEMORY', '추출에 사용할 메모리가 부족합니다. 다른 앱을 종료한 뒤 다시 시도해 주세요.'
    elif 'timed out' in text or 'timeoutex' in text or 'timeout' in text or isinstance(error, TimeoutError):
        code, message = 'EXTRACTION_TIMEOUT', '추출 응답 시간이 초과되었습니다. Ollama 상태를 확인한 뒤 다시 시도해 주세요.'
    elif '출력 길이 제한' in detail:
        code, message = 'OUTPUT_LIMIT', 'AI 응답이 출력 길이 제한을 초과했습니다. 해당 페이지를 확인한 뒤 다시 시도해 주세요.'
    elif '문제가 추출되지 않았습니다' in detail:
        code, message = 'NO_QUESTIONS', '페이지에서 문제를 찾지 못했습니다. 원본 PDF에 문제가 있는지 확인해 주세요.'
    elif isinstance(error, json.JSONDecodeError) or 'jsondecodeerror' in text:
        code, message = 'INVALID_EXTRACTION_DATA', '추출 데이터 형식이 올바르지 않습니다. 해당 페이지를 확인한 뒤 다시 시도해 주세요.'
    elif isinstance(error, FileNotFoundError) or 'filenotfounderror' in text or 'no such file or directory' in text or '문제은행 원본을 찾을 수 없습니다' in detail:
        code, message = 'SOURCE_MISSING', '추출에 필요한 파일이 없습니다. 원본 PDF와 프로그램 파일을 확인해 주세요.'
    elif any(value in text for value in ('filedataerror', 'emptyfileerror', 'cannot open broken document', '암호')):
        code, message = 'INVALID_PDF', 'PDF를 읽을 수 없습니다. 파일 손상이나 암호 설정을 확인해 주세요.'
    elif isinstance(error, PermissionError) or 'permissionerror' in text:
        code, message = 'FILE_ACCESS_DENIED', '파일을 읽거나 저장할 권한이 없습니다. workspace 폴더의 접근 권한을 확인해 주세요.'
    elif '결과 파일이 없습니다' in detail:
        code, message = 'OUTPUT_MISSING', '추출 결과 파일이 생성되지 않았습니다. 다시 시도해 주세요.'
    elif stage == 'references':
        code, message = 'REFERENCE_EXTRACTION_FAILED', '참고 이미지와 문제 문서를 만드는 중 오류가 발생했습니다. 해당 페이지를 확인해 주세요.'
    elif stage == 'text' or 'valueerror:' in text:
        code, message = 'QUESTION_EXTRACTION_FAILED', 'AI 문제 추출 중 오류가 발생했습니다. 해당 페이지를 확인한 뒤 다시 시도해 주세요.'
    else:
        code, message = 'EXTRACTION_FAILED', '문제 추출 중 오류가 발생했습니다. 아래 오류 상세 내용을 확인해 주세요.'
    if page is None:
        match = re.search(r'(\d+)페이지 (?:처리 실패|결과 파일)', detail)
        if match:
            page = int(match.group(1))
    if page:
        message = f'{page}페이지: {message}'
    return {'error_code': code, 'error_message': message, 'error': detail[-3000:]}


def job_record(row):
    task = dict(row)
    if task['status'] == 'failed' and not task.get('error_code'):
        task.update(failure_fields(task.get('error') or '', page=task.get('current_page') or None))
    if task.get('error_message'):
        task['error_message'] = task['error_message'].replace('추출 현황에서 상세 내용을 확인해 주세요.', '아래 오류 상세 내용을 확인해 주세요.')
    return task
