"""Decode a GitHub secret without writing key material to logs."""
import base64
import os
from pathlib import Path

key = base64.b64decode(os.environ['APPLE_API_KEY_BASE64'], validate=True)
if b'-----BEGIN PRIVATE KEY-----' not in key:
    raise SystemExit('APPLE_API_KEY must contain the single-line base64 representation of an App Store Connect .p8 key')
path = Path(os.environ['RUNNER_TEMP']) / 'notes-notarization.p8'
path.write_bytes(key)
path.chmod(0o600)
with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as stream:
    stream.write(f'APPLE_API_KEY={path}\n')
print('Apple 공증 키 파일 준비 완료')
