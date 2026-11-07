from core import outcome
from core.api_catalog import search


def directory_action(parameters, player=None, session_memory=None):
    try:
        result = search(query=parameters.get('query', ''), category=parameters.get('category', ''),
                        auth=parameters.get('auth', 'any'), limit=parameters.get('limit', 10),
                        refresh=parameters.get('refresh', False), action=parameters.get('action', 'search'))
    except (ValueError, TypeError) as exc:
        return outcome.failed('api_directory', f'API directory: {exc}')
    except Exception:
        return outcome.failed('api_directory', 'API directory is unavailable; no provider was connected.')
    if player:
        try:
            player.show_content('PUBLIC API DIRECTORY', result)
        except Exception:
            pass
    return outcome.untrusted('api_directory', result)


TOOL = {
    'name': 'api_directory',
    'tier': 'extra',
    'brief': 'Search the public-apis catalog by topic and authentication requirement; lists docs, never keys.',
    'description': 'Search all bundled public-apis directory listings or list categories. Reports provider documentation and authentication requirements. It does not supply API keys, create accounts, or activate providers. Use dedicated data tools for actual weather, currency, news and air quality.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['search', 'categories']},
        'query': {'type': 'STRING', 'description': 'API name or topic, e.g. weather, transport, finance'},
        'category': {'type': 'STRING', 'description': 'Optional category filter'},
        'auth': {'type': 'STRING', 'enum': ['any', 'no_key', 'key_required']},
        'limit': {'type': 'INTEGER', 'description': 'Number of results, 1 to 25; default 10'},
        'refresh': {'type': 'BOOLEAN', 'description': 'Fetch the latest directory from GitHub; offline snapshot used on failure'}}},
    'handler': directory_action,
}
