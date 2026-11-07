import json
from core.development_workspace import prepare, review


def development_review(parameters, **kwargs):
    try:
        action = parameters.get('action')
        if action == 'prepare':
            return json.dumps(prepare(), indent=2)
        if action == 'review':
            return json.dumps(review(parameters.get('workspace_id')), indent=2)
        return 'Choose prepare or review.'
    except (ValueError, OSError) as exc:
        return f'Development workspace unavailable: {exc}'


TOOL = {
    'name': 'development_review',
    'description': 'Prepare a source-only Jarvis development copy, or review its changed files and Python syntax. Returns a diff and report. Does not execute tests or apply updates. Use code_helper to edit the returned working path; retain baseline for comparison.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['prepare', 'review']},
        'workspace_id': {'type': 'STRING'}}, 'required': ['action']},
    'handler': development_review,
}
