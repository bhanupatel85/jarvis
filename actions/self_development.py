import json
from core import self_development as dev


def self_development(parameters, **kwargs):
    p = parameters
    try:
        action = p['action']
        if action == 'prepare':
            result = dev.start()
        elif action == 'check':
            result = dev.check(p.get('workspace_id'), p.get('test_modules', []))
        elif action == 'apply':
            result = dev.apply(p.get('workspace_id'), p.get('review_token'))
        elif action == 'rollback':
            result = dev.rollback(p.get('workspace_id'))
        else:
            return 'Unknown development action'
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f'Development action failed: {exc}'


TOOL = {
    'name': 'self_development',
    'description': 'Develop Jarvis through prepare, check, apply, rollback. Prepare returns a working source copy; edit it with code_helper. Check runs selected unittest modules with a deadline, generates changes.diff and a review token. Present changes and test evidence before requesting apply. Apply requires on-screen approval and unchanged verified source. Rollback restores backups only if no later edits occurred. Source-only copies are not OS sandboxes.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['prepare', 'check', 'apply', 'rollback']},
        'workspace_id': {'type': 'STRING'},
        'review_token': {'type': 'STRING'},
        'test_modules': {'type': 'ARRAY', 'items': {'type': 'STRING'}, 'maxItems': 20}}, 'required': ['action']},
    'handler': self_development,
}
