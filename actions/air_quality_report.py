from core import outcome
from core.public_data import air_quality


def air_quality_action(parameters, player=None, session_memory=None):
    try:
        result = air_quality(parameters.get('city', ''), parameters.get('country_code', ''), parameters.get('refresh', False))
    except (ValueError, TypeError) as exc:
        return outcome.failed('air_quality_report', f'Air quality unavailable: {exc}')
    except Exception:
        return outcome.failed('air_quality_report', 'Air-quality provider is unavailable; no current reading was verified.')
    if player:
        try:
            player.show_content('AIR QUALITY', result)
        except Exception:
            pass
    return outcome.untrusted('public_data', result)


TOOL = {
    'name': 'air_quality_report',
    'description': 'Get air pollution, US AQI, PM2.5 and PM10 for a city directly from Open-Meteo/CAMS. Model estimates, not Indian CPCB station readings. Includes resolved location and timestamps.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'city': {'type': 'STRING', 'description': 'City, optionally with region, e.g. Hyderabad, Telangana'},
        'country_code': {'type': 'STRING', 'description': 'Optional two-letter country filter, e.g. IN for India'},
        'refresh': {'type': 'BOOLEAN', 'description': 'Bypass recent reading cache only if the user asks for a refresh'}}, 'required': ['city']},
    'handler': air_quality_action,
}
