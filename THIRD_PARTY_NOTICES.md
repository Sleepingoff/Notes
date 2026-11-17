# 제삼자 구성요소

Notes의 애플리케이션 소스는 AGPL-3.0-only로 배포합니다. 전문은 [LICENSE](LICENSE)에 있습니다. 아래 구성요소의 권리와 라이선스는 각각의 저작권자에게 있습니다.

| 구성요소 | 라이선스 | 출처 |
| --- | --- | --- |
| Electron | MIT 및 Chromium 등 포함 구성요소의 개별 라이선스 | https://github.com/electron/electron |
| Python | Python Software Foundation License | https://www.python.org/psf/license/ |
| PyMuPDF / MuPDF | AGPL-3.0 또는 Artifex 상용 라이선스 | https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright |
| Ollama Python 클라이언트 | MIT | https://github.com/ollama/ollama-python |
| httpx / httpcore / anyio / h11 / idna | 각 프로젝트의 MIT/BSD 라이선스 | 번들 backend/licenses의 개별 고지 |
| pydantic / pydantic-core 및 타입 관련 의존성 | MIT | https://github.com/pydantic/pydantic |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| hwpkit 도구 | MIT | vendor/hwp/LICENSE-hwpkit.txt |
| rhwp JavaScript/WebAssembly | MIT | vendor/hwp/vendor/rhwp/LICENSE |

패키징 시 설치된 Python 런타임 의존성의 라이선스 파일을 `backend/licenses`에 복사합니다. Electron 배포본의 LICENSE 및 LICENSES.chromium.html도 앱 패키지에 포함됩니다. PyInstaller 자체는 GPL 및 배포 예외 조항을 따르는 빌드 도구입니다.

AI 모델과 Ollama 실행 프로그램은 앱에 포함하지 않습니다. 사용자가 직접 설치한 모델에는 모델 배포자가 정한 별도의 이용 조건이 적용됩니다. 모델의 다운로드·실행은 사용자의 PC에서 수행합니다.

내장 시험 정답 데이터는 사용자가 제공한 원본 정답표에서 추출한 것으로 원본 파일명과 SHA-256이 데이터 파일에 보존되어 있습니다. 애플리케이션 소스의 라이선스가 원본 시험 문서나 사용자가 올린 자료의 권리까지 부여하는 것은 아닙니다.
