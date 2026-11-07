"""Bounded Windows accessibility requests; COM never runs on the voice thread."""
import json
from pathlib import Path
import subprocess
import sys


def request(action, **params):
    payload = {"action": action, **params}
    try:
        run = subprocess.run(
            [sys.executable, '-m', 'core.uia_worker'],
            input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
            cwd=Path(__file__).resolve().parent.parent, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result = json.loads(run.stdout)
        if not isinstance(result, dict):
            raise ValueError('Invalid accessibility response')
        return result
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'attempted': action not in {'inspect', 'diagnose'},
                'reason': 'Accessibility timed out. Observe before retrying; input outcome may be unknown.'}
    except (OSError, ValueError):
        return {'status': 'unavailable', 'attempted': False,
                'reason': 'Windows accessibility could not start. Check the installed pywinauto dependency and inspect the screen.'}
