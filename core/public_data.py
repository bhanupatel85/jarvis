"""Bounded, cached public data access. No credentials or model calls."""
import json
import math
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

_cache = OrderedDict()
_lock = threading.Lock()
_inflight = {}


def fetch(url, ttl=300, xml=False, refresh=False):
    """Reuse fresh results and coalesce concurrent requests for the same resource.

    Errors and expired responses are never presented as current data. Only fixed
    provider URLs constructed by the callers below should reach this function.
    """
    key = (url, xml)
    with _lock:
        hit = _cache.get(key)
        if not refresh and hit and time.monotonic() < hit[0]:
            _cache.move_to_end(key)
            return hit[1], hit[2], True
        pending = _inflight.get(key)
        owner = pending is None
        if owner:
            if len(_inflight) >= 32:
                raise RuntimeError('Public-data requests are busy; try again shortly')
            pending = _inflight[key] = Future()
    if not owner:
        # A socket timeout is not an overall wall-clock deadline. Bound followers
        # independently so another request cannot hold up their worker forever.
        value, stamp, _ = pending.result(timeout=6)
        return value, stamp, True
    try:
        request = Request(url, headers={'User-Agent': 'Jarvis-PublicData/1.1', 'Accept': 'application/xml' if xml else 'application/json'})
        with urlopen(request, timeout=5) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Provider response exceeds size limit')
        value = ElementTree.fromstring(raw) if xml else json.loads(raw)
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with _lock:
            _cache[key] = (time.monotonic() + ttl, value, stamp)
            _cache.move_to_end(key)
            while len(_cache) > 128:
                _cache.popitem(last=False)
        result = (value, stamp, False)
        pending.set_result(result)
        return result
    except Exception as exc:
        pending.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(key, None)


def currency(amount, base, quote, refresh=False):
    if isinstance(amount, bool):
        raise ValueError("Amount must be a number, not a boolean")
    amount = float(amount)
    base, quote = str(base).upper().strip(), str(quote).upper().strip()
    if not math.isfinite(amount) or amount < 0 or not all(re.fullmatch(r'[A-Z]{3}', c) for c in (base, quote)):
        raise ValueError('Use a finite nonnegative amount and three-letter currency codes, such as USD and INR')
    if base == quote:
        return f'{amount:g} {base} = {amount:g} {quote} (same currency; no exchange rate needed).'
    url = f'https://api.frankfurter.dev/v2/rate/{base}/{quote}'
    data, stamp, cached = fetch(url, ttl=3600, refresh=refresh)
    rate = float(data['rate'])
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError('Invalid provider rate')
    converted = amount * rate
    if not math.isfinite(converted):
        raise ValueError('Converted amount is too large')
    return (f'{amount:g} {base} = {converted:,.2f} {quote}. Rate: {rate:g}; rate date: {data["date"]}. '
            f'Source: Frankfurter ({url}). Retrieved {stamp}' + (' (cached).' if cached else '.') +
            ' Daily reference rate; bank fees and live trading prices may differ.')


def resolve_location(city, country_code=''):
    if not isinstance(city, str):
        raise ValueError('Provide a city name')
    city = city.strip()
    if not city or len(city) > 150:
        raise ValueError('Provide a city name')
    country_code = str(country_code or '').strip().upper()
    if country_code and not re.fullmatch(r'[A-Z]{2}', country_code):
        raise ValueError('Use a two-letter country code, such as IN')
    params = {'name': city, 'count': 1, 'language': 'en', 'format': 'json'}
    if country_code:
        params['countryCode'] = country_code
    geo, _, _ = fetch('https://geocoding-api.open-meteo.com/v1/search?' + urlencode(params), ttl=86400)
    if not geo.get('results'):
        raise ValueError('City not found; try city and region')
    place = geo['results'][0]
    lat, lon = float(place['latitude']), float(place['longitude'])
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Provider returned invalid coordinates')
    return place


def weather(city, when='today', country_code='', refresh=False):
    when = str(when or 'today').strip().lower()
    if when not in ('today', 'now', 'tomorrow'):
        raise ValueError('Weather currently supports today, now, or tomorrow')
    place = resolve_location(city, country_code)
    url = 'https://api.open-meteo.com/v1/forecast?' + urlencode({'latitude': place['latitude'], 'longitude': place['longitude'], 'current': 'temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m', 'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max', 'timezone': 'auto', 'forecast_days': 2})
    data, stamp, cached = fetch(url, refresh=refresh)
    label = ', '.join(str(place[k]) for k in ('name', 'admin1', 'country') if place.get(k))
    day = 1 if when == 'tomorrow' else 0
    daily = data['daily']
    result = f'{label}, {daily["time"][day]}: low {daily["temperature_2m_min"][day]} C, high {daily["temperature_2m_max"][day]} C; rain probability {daily["precipitation_probability_max"][day]}%.'
    if day == 0:
        c = data['current']
        result += f' Current model estimate at {c["time"]} ({data["timezone"]}): {c["temperature_2m"]} C, feels like {c["apparent_temperature"]} C, humidity {c["relative_humidity_2m"]}%, wind {c["wind_speed_10m"]} km/h.'
    return result + f' Source: Open-Meteo ({url}). Retrieved {stamp}' + (' (cached).' if cached else '.')


def air_quality(city, country_code='', refresh=False):
    """CAMS model estimates using the explicitly labelled US AQI scale."""
    place = resolve_location(city, country_code)
    url = 'https://air-quality-api.open-meteo.com/v1/air-quality?' + urlencode({
        'latitude': place['latitude'], 'longitude': place['longitude'],
        'current': 'us_aqi,pm2_5,pm10', 'timezone': 'auto', 'forecast_days': 1})
    data, stamp, cached = fetch(url, ttl=600, refresh=refresh)
    current = data.get('current') or {}
    label = ', '.join(str(place[k]) for k in ('name', 'admin1', 'country') if place.get(k))
    readings = []
    aqi = current.get('us_aqi')
    if isinstance(aqi, (int, float)) and not isinstance(aqi, bool) and math.isfinite(aqi) and aqi >= 0:
        category = next((text for maximum, text in (
            (50, 'good'), (100, 'moderate'), (150, 'unhealthy for sensitive groups'),
            (200, 'unhealthy'), (300, 'very unhealthy'), (float('inf'), 'hazardous'))
            if aqi <= maximum))
        readings.append(f'US AQI {aqi:g} ({category})')
    for field, name in (('pm2_5', 'PM2.5'), ('pm10', 'PM10')):
        value = current.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            readings.append(f'{name} {value:g} micrograms/m3')
    if not readings:
        raise ValueError('No valid air-quality readings returned for this location')
    return (f'{label}: ' + '; '.join(readings) +
            f'. Model time: {current.get("time") or "not supplied"} ({data.get("timezone") or "timezone not supplied"}). '
            'CAMS model estimate on the US AQI scale, not an Indian CPCB station measurement; local conditions may differ. '
            f'Source: Open-Meteo / CAMS ({url}). Retrieved {stamp}' + (' (cached).' if cached else '.'))


def headlines(query='', refresh=False):
    """Only broad topics use RSS; specific searches retain existing search routing."""
    q = re.sub(r'\s+', ' ', (query or '').strip().lower())
    feeds = {'': 'world', 'news': 'world', 'top world news today': 'world', 'world news today': 'world', 'world': 'world', 'technology': 'technology', 'tech news': 'technology', 'technology news': 'technology', 'business': 'business', 'business news': 'business', 'science': 'science_and_environment'}
    feeds.update({alias: 'world' for alias in ('world news', 'latest news', 'top headlines', 'headlines', 'latest world news')})
    feeds.update({'science news': 'science_and_environment', 'latest technology news': 'technology', 'latest business news': 'business'})
    section = feeds.get(q)
    if section is None:
        return None
    url = f'https://feeds.bbci.co.uk/news/{section}/rss.xml'
    root, stamp, cached = fetch(url, ttl=180, xml=True, refresh=refresh)
    lines = []
    for item in root.findall('./channel/item')[:5]:
        title, link = item.findtext('title'), item.findtext('link')
        if title and link and link.startswith('https://'):
            lines.append(f'{len(lines)+1}. {title}\nPublished: {item.findtext("pubDate") or "not provided"}\n{link}')
    if not lines:
        raise ValueError('No headlines in provider feed')
    return f'BBC News headlines; retrieved {stamp}' + (' (cached)' if cached else '') + '\n' + '\n'.join(lines)
