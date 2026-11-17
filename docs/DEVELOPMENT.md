# 개발 및 릴리즈

## 소스 실행

Python 3.13과 Node.js 22를 설치합니다. Ollama와 모델 준비는 [사용 안내](../README.md)를 따릅니다.

```sh
git clone https://github.com/Sleepingoff/Notes.git
cd Notes
python3 -m venv .venv-web
source .venv-web/bin/activate
python -m pip install -r requirements-build.txt
npm ci
npm start
```

Windows PowerShell에서는 가상환경을 다음과 같이 만들고 활성화합니다.

```powershell
py -3.13 -m venv .venv-web
.\.venv-web\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
npm ci
npm start
```

가상환경을 다른 이름으로 만들었다면 `NOTES_PYTHON` 환경 변수에 Python 실행 파일 경로를 지정합니다. 브라우저에서 실행하려면 `python server.py` 실행 후 `http://127.0.0.1:8765`를 엽니다. 브라우저 실행 데이터는 프로젝트의 `workspace`에, 데스크톱 실행 데이터는 사용자 앱 데이터 폴더에 저장됩니다.

## 검증과 패키징

```sh
python -B -m unittest discover -s tests -q
npm test
python tools/build_backend.py
npm run build:dir
npm run dist
```

운영체제별로 해당 운영체제에서 빌드합니다. Python 처리 엔진과 HWP 변환기를 앱에 포함하므로 배포본 사용자는 Python이나 Node.js를 별도 설치할 필요가 없습니다. Ollama와 모델은 별도로 설치합니다.

`build:dir`은 실행 가능한 앱 폴더를 만들고, `dist`는 macOS DMG·ZIP 또는 Windows 설치 파일을 `release`에 만듭니다. 사용자 데이터, 로컬 모델, 인증서와 빌드 결과는 Git에 포함하지 않습니다.

## GitHub Actions

`main` 푸시와 Pull Request에서는 macOS Apple Silicon, macOS Intel, Windows x64에서 테스트·패키징·실제 앱 시작 검사를 실행합니다.

`package.json` 버전과 일치하는 `v*` 태그를 푸시하면 세 플랫폼의 설치 파일을 빌드합니다. 모든 빌드가 성공하면 GitHub Release에 설치 파일과 SHA-256 체크섬을 게시합니다.

```sh
npm version 0.1.1 --no-git-tag-version
git add package.json package-lock.json
git commit -m "Release 0.1.1"
git tag v0.1.1
git push origin main
git push origin v0.1.1
```

## 인증서 없이 릴리즈

Secrets를 등록하지 않아도 릴리즈할 수 있습니다. macOS는 임시 서명(ad-hoc)으로 빌드하고 공증을 건너뜁니다. Windows는 인증서 없이 설치 파일을 만듭니다. macOS 임시 서명은 서명 무결성 검사만 수행하며 Apple의 배포 인증이나 공증을 의미하지 않습니다. 사용 시 운영체제의 보안 경고가 나타날 수 있습니다.

## macOS 정식 서명과 공증 활성화

저장소의 **Settings → Secrets and variables → Actions**에 다음 Secrets를 모두 등록합니다. 다섯 값이 모두 준비되면 릴리즈 워크플로가 정식 서명과 공증을 자동 활성화합니다. 일부만 등록된 상태에서는 임시 서명으로 릴리즈합니다.

| Secret | 값 |
| --- | --- |
| `MAC_CSC_LINK` | Developer ID Application 인증서와 개인 키를 내보낸 `.p12` 파일의 Base64 문자열 |
| `MAC_CSC_KEY_PASSWORD` | `.p12` 내보내기 비밀번호 |
| `APPLE_API_KEY` | 공증 권한이 있는 App Store Connect API `.p8` 키 파일의 Base64 문자열 |
| `APPLE_API_KEY_ID` | API Key ID |
| `APPLE_API_ISSUER` | API Issuer ID |

macOS에서 파일을 Base64 문자열로 변환하려면 다음 명령을 사용할 수 있습니다. 출력은 GitHub Secret에만 등록하고 소스나 이슈에 남기지 마세요.

```sh
base64 < DeveloperID.p12 | tr -d '\n'
base64 < AuthKey.p8 | tr -d '\n'
```

서명된 릴리즈는 Developer ID 서명, Apple 공증, 공증 티켓 부착과 검증이 모두 성공해야 게시합니다. 인증서 유효성이나 공증에 문제가 있으면 해당 빌드가 실패하며 임시 서명으로 자동 우회하지 않습니다.

Windows 코드 서명은 선택 사항입니다. `WIN_CSC_LINK`에 Windows 서명용 인증서의 Base64 값, `WIN_CSC_KEY_PASSWORD`에 인증서 비밀번호를 등록할 수 있습니다.

## 라이선스

Notes는 AGPL-3.0-only로 배포합니다. 앱을 수정하거나 재배포할 때는 [LICENSE](../LICENSE)를 확인하세요. 외부 라이브러리와 정답 데이터의 권리는 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)에 안내합니다. Ollama 모델은 각 모델의 라이선스를 따릅니다.
