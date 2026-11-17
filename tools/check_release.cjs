const {readFileSync, appendFileSync} = require('node:fs');
const version = JSON.parse(readFileSync('package.json', 'utf8')).version;
const tag = process.env.GITHUB_REF_NAME || '';
if (tag !== `v${version}`) throw new Error(`태그 ${tag}와 package.json 버전 ${version}이 다릅니다.`);
const credentials = ['CSC_LINK', 'CSC_KEY_PASSWORD', 'APPLE_API_KEY', 'APPLE_API_KEY_ID', 'APPLE_API_ISSUER'];
const signed = process.platform === 'darwin' && credentials.every(name => Boolean(process.env[name]));
if (process.env.GITHUB_ENV) appendFileSync(process.env.GITHUB_ENV, `NOTES_RELEASE_SIGNING=${signed ? '1' : '0'}\n`);
console.log(`릴리즈 설정 확인: ${tag}; ${signed ? 'macOS 정식 서명 및 공증' : process.platform === 'darwin' ? 'macOS 임시 서명 (인증서·공증 없음)' : 'Windows 빌드'}`);
