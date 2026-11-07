"""Small diagnostic events without dictated text, credentials, URLs or screen data."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

_lock = threading.Lock()
LOG_PATH = Path(__file__).resolve().parent.parent / 'logs' / 'interaction.jsonl'


def record(action, status, *, backend='', error_type='', attempted=False):
    event = {'at': datetime.now(timezone.utc).isoformat(), 'action': str(action)[:40],
             'status': str(status)[:40], 'backend': str(backend)[:24],
             'error_type': str(error_type)[:64], 'attempted': bool(attempted)}
    try:
        with _lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if LOG_PATH.exists() and LOG_PATH.stat().st_size > 1_000_000:
                LOG_PATH.replace(LOG_PATH.with_suffix('.previous.jsonl'))
            with LOG_PATH.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event) + '\n')
    except OSError:
        pass
