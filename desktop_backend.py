"""One frozen executable, with explicit entry points for every child process."""
import json
from pathlib import Path
import runpy
import sys


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2 or sys.argv[1] not in ('server', 'worker', 'extract', 'extract_references', 'self-test'):
        raise SystemExit('Usage: notes-backend server|worker|extract|extract_references|self-test [arguments]')
    mode = sys.argv.pop(1)
    if mode == 'self-test':
        import pymupdf
        import ollama
        from answer_archive import load_archive
        from runtime_paths import workspace_path
        base = Path(__file__).resolve().parent
        assert (base / 'web/index.html').is_file()
        assert (base / 'vendor/hwp/vendor/rhwp/rhwp_bg.wasm').is_file()
        print(json.dumps({'ok': True, 'answer_keys': len(load_archive().records), 'workspace': str(workspace_path(base))}))
        return
    runpy.run_module(mode, run_name='__main__')


if __name__ == '__main__':
    main()
