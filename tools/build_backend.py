"""Build on the target OS/architecture: Python runtime and all app resources."""
from pathlib import Path
import subprocess
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--name', 'notes-backend', '--exclude-module', 'numpy', '--exclude-module', 'PIL', '--distpath', str(ROOT / 'desktop-resources'),
        '--workpath', str(ROOT / 'build/backend'), '--specpath', str(ROOT / 'build')]
for name in ('web', 'annotation_component', 'data', 'vendor/hwp'):
    args += ['--add-data', f'{ROOT / name}:{name}']
# Extraction scripts are also included as data so cache keys are versioned by content.
for name in ('extract.py', 'extract_references.py', 'extraction_format.py', 'exam_info.py'):
    args += ['--add-data', f'{ROOT / name}:.']
for name in ('server', 'worker', 'extract', 'extract_references'):
    args += ['--hidden-import', name]
args += [str(ROOT / 'desktop_backend.py')]
subprocess.run(args, cwd=ROOT, check=True, env={**os.environ, 'PYINSTALLER_CONFIG_DIR': str(ROOT / 'build/pyinstaller-cache')})
source = ROOT / 'desktop-resources/notes-backend'
target = ROOT / 'desktop-resources/backend'
# PyInstaller's output directory name follows the executable name.
import shutil
if target.exists():
    shutil.rmtree(target)
source.rename(target)
print(target)

# Preserve license notices for the Python components in the distributable.
from importlib.metadata import distribution
for name in ('pymupdf', 'ollama', 'httpx', 'httpcore', 'anyio', 'h11', 'idna', 'pydantic', 'pydantic_core', 'certifi', 'typing_extensions', 'typing_inspection', 'annotated_types'):
    dist = distribution(name)
    for entry in dist.files or []:
        if any(word in entry.name.lower() for word in ('license', 'copying', 'notice')):
            dest = target / 'licenses' / name / entry.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dist.locate_file(entry), dest)
