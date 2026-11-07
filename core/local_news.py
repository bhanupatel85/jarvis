"""Dated, source-linked local startup headlines; no credentials required."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

AREAS = (
    ("Old Bowenpally and surroundings", '"Old Bowenpally" OR Bowenpally OR B Bowenpally', ("bowenpally", "బోయిన్‌పల్లి", "బోయినపల్లి")),
    ("Munigadapa and Jagadevpur surroundings", 'Munigadapa OR Jagadevpur OR Jagdevpur OR "మునిగడప" OR "జగదేవపూర్"', ("munigadapa", "jagadevpur", "jagdevpur", "మునిగడప", "జగదేవపూర్")),
    ("Medchal and surroundings", 'Medchal OR Kompally OR "మేడ్చల్"', ("medchal", "kompally", "మేడ్చల్")),
)

def parse_feed(data, aliases, now=None):
    now = now or datetime.now(timezone.utc)
    found = []
    for item in ET.fromstring(data).findall("./channel/item"):
        title = re.sub(r"\s+", " ", item.findtext("title", "")).strip()
        link = item.findtext("link", "").strip()
        if not title or not link.startswith("https://") or not any(a in title.casefold() for a in aliases):
            continue
        try:
            date = parsedate_to_datetime(item.findtext("pubDate", ""))
            if date.tzinfo is None:
                continue
            if not now - timedelta(days=7) <= date <= now + timedelta(minutes=10):
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        source = item.findtext("source", "News report").strip()
        found.append((date, title[:350], source[:100], link))
    return sorted(found, key=lambda row: row[0], reverse=True)

def _area_news(area):
    label, query, aliases = area
    url = "https://news.google.com/rss/search?" + urlencode({"q": "(" + query + ") when:7d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    try:
        with urlopen(Request(url, headers={"User-Agent": "JarvisLocalNews/1.0"}), timeout=5) as response:
            rows = parse_feed(response.read(1500000), aliases)
        return label, rows, False
    except Exception:
        return label, [], True

def local_briefing():
    lines = ["LOCAL NEWS — reports published in the last 7 days (not necessarily events from today).", "Headlines are publisher reports, not independently verified facts."]
    seen = set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for label, rows, failed in pool.map(_area_news, AREAS):
            lines.append("\n" + label + ":")
            if failed:
                lines.append("News could not be fetched for this area right now.")
                continue
            count = 0
            for date, title, source, link in rows:
                key = title.casefold()
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"- {title} | {source} | Published {date:%d %b %Y}\n  {link}")
                count += 1
                if count == 2:
                    break
            if not count:
                lines.append("No additional recent local headlines found for this area; this does not mean nothing happened.")
    return "\n".join(lines)
