"""Verified source updates with explicit dispatcher approval and guarded rollback."""
import hashlib
import json
import re
import sys
import threading
import tempfile
from pathlib import Path
from core.development_workspace import ROOT, WORKSPACES, prepare, review, sources
from core.execution import contained_path, run_process
from core.storage import atomic_json, atomic_text

_lock = threading.RLock()


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in sources(root)}


def folder(identifier, workspaces):
    if not re.fullmatch(r'[a-f0-9]{16}', str(identifier)):
        raise ValueError('Invalid workspace ID')
    base = Path(workspaces).resolve()
    target = base / identifier
    if target.is_symlink() or not target.resolve().is_relative_to(base):
        raise ValueError('Workspace escapes development directory')
    for name in ('baseline', 'working', 'rollback'):
        if (target / name).is_symlink() or not (target / name).resolve().is_relative_to(target.resolve()):
            raise ValueError('Workspace folders cannot be links')
    return target


def token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def start(root=ROOT, workspaces=WORKSPACES):
    item = prepare(root, workspaces)
    target = folder(item['id'], workspaces)
    atomic_json(target / 'original.json', digest(target / 'baseline'))
    return item


def check(identifier, modules, root=ROOT, workspaces=WORKSPACES):
    with _lock:
        target = folder(identifier, workspaces)
        report = review(identifier, workspaces)
        if report['syntax_errors']:
            raise ValueError('Fix syntax errors before tests: ' + str(report['syntax_errors']))
        if not modules or len(modules) > 20 or any(not re.fullmatch(r'tests\.test_[A-Za-z0-9_]+', m) for m in modules):
            raise ValueError('Supply 1–20 unittest module names, e.g. tests.test_public_data')
        before = digest(target / 'working')
        # A fresh bytecode directory prevents same-second/same-size edits from
        # reusing stale test or application bytecode.
        with tempfile.TemporaryDirectory(prefix='jarvis-test-cache-') as cache:
            result = run_process([sys.executable, '-X', 'pycache_prefix=' + cache, '-m', 'unittest', *modules, '-v'], target / 'working', timeout=120)
        after = digest(target / 'working')
        success = result.returncode == 0 and not result.timed_out and not result.cancelled and before == after
        # A zero exit with no discovered tests is not validation.
        match = re.search(r'Ran (\d+) tests?', result.stderr + result.stdout)
        success = bool(success and match and int(match[1]) > 0)
        report.update({'tests_run': True, 'passed': success, 'modules': modules, 'working_hashes': after,
                       'test_count': int(match[1]) if match else 0, 'result': result.describe()})
        report['review_token'] = token({'hashes': after, 'modules': modules, 'result': report['result']})
        atomic_json(target / 'verified.json', report)
        return report


def apply(identifier, review_token, root=ROOT, workspaces=WORKSPACES):
    with _lock:
        root = Path(root).resolve()
        target = folder(identifier, workspaces)
        report = json.loads((target / 'verified.json').read_text())
        if (target / 'applied.json').exists():
            raise ValueError('Workspace already applied')
        if not report['passed'] or report['review_token'] != review_token:
            raise ValueError('A passing test report and its reviewed token are required')
        new = digest(target / 'working')
        if new != report['working_hashes']:
            raise ValueError('Working source changed after testing; check again')
        old = json.loads((target / 'original.json').read_text())
        if digest(target / 'baseline') != old:
            raise ValueError('Baseline was modified')
        if digest(root) != old:
            raise ValueError('App source changed since preparation; prepare a new workspace')
        changed = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
        if not changed:
            raise ValueError('No source changes to apply')
        if any(k not in new for k in changed):
            raise ValueError('Source deletions require manual review; automatic apply supports additions and edits')
        payloads = {k: contained_path(target / 'working', k).read_text(encoding='utf-8') for k in changed}
        for k in changed:
            destination = contained_path(root, k)
            if k in old:
                atomic_text(contained_path(target / 'rollback', k), destination.read_text(encoding='utf-8'))
        state = {'id': identifier, 'stage': 'applying', 'files': changed, 'old': {k: old.get(k) for k in changed},
                 'new': {k: new[k] for k in changed}, 'written': []}
        atomic_json(target / 'applied.json', state)
        for k in changed:
            atomic_text(contained_path(root, k), payloads[k])
            state['written'].append(k)
            atomic_json(target / 'applied.json', state)
        state['stage'] = 'applied; restart required'
        atomic_json(target / 'applied.json', state)
        return state


def rollback(identifier, root=ROOT, workspaces=WORKSPACES):
    with _lock:
        root = Path(root).resolve()
        target = folder(identifier, workspaces)
        state = json.loads((target / 'applied.json').read_text())
        if state['stage'] == 'rolled_back':
            raise ValueError('Already rolled back')
        payloads = {}
        for k in state['files']:
            path = contained_path(root, k)
            current = hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest() if path.exists() else None
            if current not in (state['new'][k], state['old'][k]):
                raise ValueError('Later edits detected; rollback refused: ' + k)
            if state['old'][k] is not None:
                backup = contained_path(target / 'rollback', k)
                if hashlib.sha256(backup.read_text(encoding='utf-8').encode()).hexdigest() != state['old'][k]:
                    raise ValueError('Backup modified: ' + k)
                payloads[k] = backup.read_text(encoding='utf-8')
        for k in state['files']:
            path = contained_path(root, k)
            if k in payloads:
                atomic_text(path, payloads[k])
            elif path.exists():
                path.unlink()
        state['stage'] = 'rolled_back'
        atomic_json(target / 'applied.json', state)
        return state
