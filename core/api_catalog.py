"""Search the public-apis directory; never execute URLs or obtain credentials."""
import base64
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from core.public_data import fetch

SOURCE = 'https://github.com/public-apis/public-apis'
README_API = 'https://api.github.com/repos/public-apis/public-apis/readme'
SNAPSHOT = Path(__file__).parent / 'data' / 'public_api_catalog.json'
_updated_catalog = None


def parse_readme(text):
    entries, seen, category = [], set(), ''
    for line in text.splitlines():
        if line.startswith('### '):
            category = line[4:].strip()
        if not category or not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in re.split(r'(?<!\\)\|', line.strip().strip('|'))]
        if len(cells) != 5 or cells[3] not in ('Yes', 'No'):
            continue
        link = re.fullmatch(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', cells[0])
        if not link:
            continue
        name, url = link.groups()
        identity = (category, name, url)
        if identity in seen:
            continue
        seen.add(identity)
        entries.append(dict(name=name, url=url, description=cells[1].replace('\\|', '|'),
                            category=category, auth=cells[2].strip('` '),
                            https=cells[3], cors=cells[4]))
    return entries


@lru_cache(maxsize=1)
def bundled_catalog():
    data = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    if not data.get('entries'):
        raise ValueError('Bundled API directory is empty')
    return data


def catalog(refresh=False):
    global _updated_catalog
    if refresh:
        try:
            payload, stamp, _ = fetch(README_API, ttl=86400, refresh=True)
            content = base64.b64decode(payload['content']).decode('utf-8')
            entries = parse_readme(content)
            if not entries:
                raise ValueError('No API entries found in the updated directory')
            _updated_catalog = {'entries': entries, 'retrieved_at': stamp, 'source': SOURCE}
            return _updated_catalog, ''
        except Exception:
            return bundled_catalog(), 'Refresh unavailable; using the bundled directory snapshot. '
    return _updated_catalog or bundled_catalog(), ''


def search(query='', category='', auth='any', limit=10, refresh=False, action='search'):
    if action not in ('search', 'categories'):
        raise ValueError('Action must be search or categories')
    if not isinstance(query, str) or len(query) > 200 or not isinstance(category, str) or len(category) > 100:
        raise ValueError('Use a short API name, topic or category')
    if auth not in ('any', 'no_key', 'key_required'):
        raise ValueError('Auth filter must be any, no_key, or key_required')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
        raise ValueError('Limit must be between 1 and 25')
    data, warning = catalog(refresh)
    entries = data['entries']
    header = (f'{warning}Public API directory: {len(entries)} listings; snapshot retrieved {data["retrieved_at"]}. '
              'Directory listings are not activated integrations. Auth labels describe requirements, not supplied keys; '
              'pricing, availability and terms must be checked with each provider.\n')
    if action == 'categories':
        counts = Counter(e['category'] for e in entries)
        return header + '\n'.join(f'{name}: {count}' for name, count in sorted(counts.items())) + f'\nSource: {SOURCE}'
    tokens = re.findall(r'\w+', query.casefold())
    matches = []
    for entry in entries:
        auth_label = entry['auth'].casefold()
        no_key = auth_label in ('no', 'user-agent')
        credential = auth_label in ('apikey', 'oauth', 'x-mashape-key')
        if (auth == 'no_key' and not no_key) or (auth == 'key_required' and not credential):
            continue
        if category and category.casefold() not in entry['category'].casefold():
            continue
        haystack = ' '.join(entry[k] for k in ('name', 'description', 'category')).casefold()
        if not all(token in haystack for token in tokens):
            continue
        score = sum(3 if token in entry['name'].casefold() else 1 for token in tokens)
        matches.append((score, entry))
    matches.sort(key=lambda pair: (-pair[0], pair[1]['name'].casefold()))
    lines = [header, f'{len(matches)} matching listings; showing up to {limit}.']
    for _, entry in matches[:limit]:
        lines.append(f'{entry["name"]} [{entry["category"]}] — {entry["description"]}\n'
                     f'Auth: {entry["auth"]}; HTTPS: {entry["https"]}; CORS: {entry["cors"]}\n{entry["url"]}')
    if not matches:
        lines.append('Try a broader topic or list categories.')
    return '\n'.join(lines) + f'\nSource: {SOURCE}'
