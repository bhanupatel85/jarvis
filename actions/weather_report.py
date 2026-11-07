from core.public_data import weather


def weather_action(parameters, player=None, session_memory=None):
    try:
        result = weather(parameters.get('city', ''), parameters.get('time', 'today'), parameters.get('country_code', ''), parameters.get('refresh', False))
    except (ValueError, TypeError) as exc:
        return f'Weather unavailable: {exc}'
    except Exception:
        return 'Weather provider is unavailable. Please try again shortly; no current weather was verified.'
    if session_memory:
        try:
            session_memory.set_last_search(query=f'weather {parameters.get("city")}', response=result)
        except Exception:
            pass
    if player:
        try:
            player.write_log(f'JARVIS: {result}')
            player.show_content('WEATHER', result)
        except Exception:
            pass
    return result


TOOL = {
    'name': 'weather_report',
    'description': 'Fetch current weather estimates and today or tomorrow forecast directly from Open-Meteo, with source and timestamps.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'city': {'type': 'STRING', 'description': 'City name, optionally with region, e.g. Hyderabad, Telangana'},
        'country_code': {'type': 'STRING', 'description': 'Optional two-letter country filter, e.g. IN for India'},
        'refresh': {'type': 'BOOLEAN', 'description': 'Bypass recent forecast cache only if the user requests a refresh'},
        'time': {'type': 'STRING', 'enum': ['today', 'now', 'tomorrow']}}, 'required': ['city']},
    'handler': weather_action,
}
