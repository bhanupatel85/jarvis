"""Prepare source-only development workspaces and review without executing code."""
import ast
import difflib
import json
import uuid
from pathlib import Path
from core.storage import atomic_json, atomic_text

ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / 'development-workspaces'
FOLDERS = ('actions', 'core', 'providers', 'tests', 'knowledge', 'dashboard', 'memory', 'config', 'plugins')


def sources(root):
    root = Path(root).resolve()
    paths = list(root.glob('*.py')) + list(root.glob('*.md'))
    paths += [p for p in (root / 'requirements.txt', root / 'core' / 'prompt.txt') if p.is_file()]
    for name in FOLDERS:
        paths.extend((root / name).rglob('*.py'))
        paths.extend((root / name).rglob('*.md'))
    return [p for p in paths if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root)
            and '__pycache__' not in p.parts and p.stat().st_size < 1_000_000]


def prepare(root=ROOT, workspaces=WORKSPACES):
    root, workspaces = Path(root).resolve(), Path(workspaces).resolve()
    identifier = uuid.uuid4().hex[:16]
    target = workspaces / identifier
    target.mkdir(parents=True, exist_ok=False)
    baseline = target / 'baseline'
    working = target / 'working'
    count = 0
    for source in sources(root):
        relative = source.relative_to(root)
        payload = source.read_text(encoding='utf-8')
        atomic_text(baseline / relative, payload)
        atomic_text(working / relative, payload)
        count += 1
    atomic_json(target / 'checkpoint.json', {'id': identifier, 'stage': 'prepared', 'source_files': count,
                'source': str(root), 'working': str(working), 'note': 'Source-only copy. No credentials, personal JSON or runtime environment copied.'})
    return {'id': identifier, 'working': str(working), 'source_files': count}


def review(identifier, workspaces=WORKSPACES):
    if not isinstance(identifier, str) or len(identifier) != 16 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Use the workspace ID returned by prepare')
    base = Path(workspaces).resolve()
    target = base / identifier
    if target.is_symlink() or not target.resolve().is_relative_to(base):
        raise ValueError('Invalid workspace path')
    if not (target / 'checkpoint.json').is_file():
        raise ValueError('Workspace not found')
    baseline, working = target / 'baseline', target / 'working'
    if any(p.is_symlink() or not p.resolve().is_relative_to(target.resolve()) for p in (baseline, working)):
        raise ValueError('Workspace source folders cannot be symlinks')
    old = {str(p.relative_to(baseline)): p.read_text(encoding='utf-8') for p in sources(baseline)}
    new = {str(p.relative_to(working)): p.read_text(encoding='utf-8') for p in sources(working)}
    errors, changes, diffs = [], [], []
    for name in sorted(old.keys() | new.keys()):
        before, after = old.get(name, ''), new.get(name, '')
        if name not in old or name not in new or before != after:
            changes.append(name)
            diffs.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='before/' + name, tofile='after/' + name))
        if name in new and name.endswith('.py'):
            try:
                ast.parse(after, filename=name)
            except SyntaxError as exc:
                errors.append(f'{name}:{exc.lineno}: {exc.msg}')
    atomic_text(target / 'changes.diff', ''.join(diffs))
    report = {'id': identifier, 'stage': 'reviewed', 'changed_files': changes, 'syntax_errors': errors,
              'diff': str(target / 'changes.diff'), 'tests_run': False, 'applied': False,
              'note': 'Syntax and diff review only. Run relevant tests before approval. Running app source was not changed.'}
    atomic_json(target / 'review.json', report)
    return report
