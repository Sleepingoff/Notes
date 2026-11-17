"""Per-user Ollama settings; only locally installed vision models are used."""
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULTS = {'host': 'http://127.0.0.1:11434', 'model': 'qwen3-vl:8b-instruct',
            'num_ctx': 16384, 'num_predict': 11000}


def validate(settings):
    result = {**DEFAULTS, **{key: value for key, value in settings.items() if key in DEFAULTS}}
    host = str(result['host']).strip().rstrip('/')
    parsed = urlparse(host)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Ollama 주소는 이 컴퓨터의 주소여야 합니다. 예: http://127.0.0.1:11434')
    try:
        parsed.port
    except ValueError as error:
        raise ValueError('Ollama 포트를 확인해 주세요.') from error
    model = str(result['model']).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}', model) or 'cloud' in model.lower():
        raise ValueError('로컬에 설치한 이미지 지원 모델 이름을 입력해 주세요. 클라우드 모델은 지원하지 않습니다.')
    result.update(host=host, model=model)
    for key, minimum, maximum in (('num_ctx', 4096, 131072), ('num_predict', 1024, 32768)):
        try:
            result[key] = int(result[key])
        except (ValueError, TypeError) as error:
            raise ValueError(f'{key}는 정수여야 합니다.') from error
        if not minimum <= result[key] <= maximum:
            raise ValueError(f'{key} 범위는 {minimum}~{maximum}입니다.')
    if result['num_predict'] >= result['num_ctx']:
        raise ValueError('최대 출력 길이는 컨텍스트 길이보다 작아야 합니다.')
    return result


def load(workspace):
    path = Path(workspace) / 'ai-settings.json'
    return validate(json.loads(path.read_text(encoding='utf-8')) if path.exists() else {})


def save(workspace, settings):
    result = validate(settings)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=workspace, suffix='.tmp', delete=False) as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        temporary = Path(stream.name)
    try:
        os.replace(temporary, workspace / 'ai-settings.json')
    finally:
        temporary.unlink(missing_ok=True)
    return result


def request(settings, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = Request(settings['host'] + '/api/' + path, data=body, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def check_model(info):
    if info.get('remote_host') or info.get('remote_model'):
        raise ValueError('클라우드 모델 대신 이 컴퓨터에 다운로드한 모델을 선택해 주세요.')
    if 'vision' not in (info.get('capabilities') or []):
        raise ValueError('이미지 입력을 지원하지 않는 모델입니다. qwen3-vl 같은 vision 모델을 설치해 주세요.')


def status(workspace):
    settings = load(workspace)
    version = request(settings, 'version').get('version', '')
    models = [m['name'] for m in request(settings, 'tags').get('models', [])]
    try:
        check_model(request(settings, 'show', {'model': settings['model']}))
        return {'ok': True, 'version': version, 'models': models, 'message': '연결되었습니다. 선택한 이미지 모델로 문제를 추출할 수 있습니다.'}
    except (OSError, ValueError) as error:
        return {'ok': False, 'version': version, 'models': models, 'message': f'선택한 모델을 확인해 주세요: {error}'}
