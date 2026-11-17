"""Launch a packaged Electron app and check real renderer/API startup."""
import os
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='notes-desktop-smoke-') as directory:
    env = {**os.environ, 'NOTES_DATA_DIR': directory}
    env.pop('ELECTRON_RUN_AS_NODE', None)
    result = subprocess.run([sys.argv[1], '--smoke-test'], env=env, capture_output=True, text=True, timeout=90)
    print(result.stdout)
    print(result.stderr)
    if result.returncode or 'NOTES_DESKTOP_SMOKE_OK' not in result.stdout:
        raise SystemExit('Desktop smoke test failed')
