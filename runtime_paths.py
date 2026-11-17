"""Separate read-only bundled resources from writable personal data."""
import os
from pathlib import Path
import sys


def workspace_path(base):
    root = Path(os.environ['NOTES_DATA_DIR']).expanduser() if os.environ.get('NOTES_DATA_DIR') else Path(base)
    return root / 'workspace'


def runtime_command(base, mode, *args):
    if getattr(sys, 'frozen', False):
        return [sys.executable, mode, *map(str, args)]
    return [sys.executable, '-u', str(Path(base) / f'{mode}.py'), *map(str, args)]


def background_options():
    return {'creationflags': 0x08000000} if os.name == 'nt' else {}
