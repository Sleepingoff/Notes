# 포함 구성요소

이 앱에는 hwpkit의 hwp-preview.mjs, rhwp-init.mjs와 rhwp의 JavaScript/WebAssembly 렌더러만 포함합니다. hwpkit의 쓰기 도구, CFB, HOP, node_modules는 포함하지 않습니다.

- hwpkit: https://github.com/yuyu04/hwpkit (MIT, LICENSE-hwpkit.txt)
- rhwp: https://github.com/edwardkim/rhwp (MIT, vendor/rhwp/LICENSE)

Node.js 18 이상에서 실행하며 문서는 외부로 업로드하지 않습니다. 이 앱은 SVG 페이지를 PyMuPDF로 PDF에 삽입합니다. upstream의 --png/Chrome 경로는 사용하지 않습니다.
