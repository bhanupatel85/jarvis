"""Search within the existing Google Maps page instead of opening web search."""
from urllib.parse import urlsplit, quote_plus
from core import outcome


def is_maps_url(url):
    parsed=urlsplit(url)
    host=(parsed.hostname or '').lower()
    google_hosts={'google.com','www.google.com','google.co.in','www.google.co.in',
                  'google.co.uk','www.google.co.uk'}
    return (host=='maps.google.com' or (host in google_hosts and
            (parsed.path=='/maps' or parsed.path.startswith('/maps/'))))


async def search_maps(page, query):
    query=str(query).strip()
    if not query:
        return outcome.failed('browser_control','Say the place to search for on Maps')
    if not is_maps_url(page.url):
        await page.goto('https://www.google.com/maps',wait_until='domcontentloaded',timeout=30000)
    fields=page.locator('input#searchboxinput')
    if await fields.count()!=1:
        fields=page.get_by_role('searchbox')
    if await fields.count()!=1 or not await fields.is_visible():
        return outcome.failed('browser_control','The Maps search field is unavailable. Inspect the current page for consent or sign-in; no web search was opened.')
    await fields.fill(query,timeout=5000)
    await fields.press('Enter',timeout=5000)
    return outcome.unverified('browser_control','Search submitted inside the existing Maps tab. Inspect the resulting place before claiming it was found.',query=query,url=page.url)
