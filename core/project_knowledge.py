"""Local source retrieval, restricted to public project code and documentation."""
import re
from pathlib import Path
from core.policy import redact

ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = ('core', 'actions', 'providers', 'tests', 'knowledge')
SUFFIXES = {'.py', '.md', '.txt'}


def search(query, root=ROOT, limit=6):
    root = Path(root).resolve()
    terms = set(re.findall(r'[a-z0-9_]{2,}', str(query).lower()))
    if not terms:
        return []
    paths = list(root.glob('*.md'))
    for directory in DIRECTORIES:
        paths.extend((root / directory).rglob('*'))
    hits = []
    for path in sorted(set(paths)):
        if path.suffix.lower() not in SUFFIXES or not path.is_file():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        relative = path.relative_to(root)
        if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
            continue
        if path.stat().st_size > 250_000:
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeError):
            continue
        for start in range(0, len(lines), 24):
            text = '\n'.join(lines[start:start + 32])
            words = set(re.findall(r'[a-z0-9_]{2,}', text.lower()))
            score = len(terms & words)
            if score:
                hits.append((score / len(terms), str(relative), start + 1, redact(text)[:2400]))
    hits.sort(key=lambda hit: (-hit[0], hit[1], hit[2]))
    return [{'path': p, 'line': line, 'text': text} for _, p, line, text in hits[:limit]]


def context(query):
    hits = search(query)
    return '\n\n'.join(f'{hit["path"]}:{hit["line"]}\n{hit["text"]}' for hit in hits)
