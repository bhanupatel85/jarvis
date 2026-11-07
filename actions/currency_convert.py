from core.public_data import currency


def currency_action(parameters, player=None, session_memory=None):
    try:
        result = currency(parameters.get('amount', 1), parameters.get('base', ''), parameters.get('quote', ''), parameters.get('refresh', False))
    except (ValueError, TypeError) as exc:
        return f'Currency conversion unavailable: {exc}'
    except Exception:
        return 'Currency provider is unavailable. Please try again shortly; no current rate was verified.'
    if player:
        try:
            player.show_content('CURRENCY CONVERSION', result)
        except Exception:
            pass
    return result


TOOL = {
    'name': 'currency_convert',
    'description': 'Convert an amount using dated daily currency reference rates. Not live trading quotes. Use ISO currency codes such as USD, INR, EUR.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'amount': {'type': 'NUMBER', 'description': 'Nonnegative amount to convert'},
        'base': {'type': 'STRING', 'description': 'Source currency ISO code, e.g. USD'},
        'quote': {'type': 'STRING', 'description': 'Target currency ISO code, e.g. INR'},
        'refresh': {'type': 'BOOLEAN', 'description': 'Bypass recent rate cache; provider still publishes daily reference rates'}},
        'required': ['amount', 'base', 'quote']},
    'handler': currency_action,
}
