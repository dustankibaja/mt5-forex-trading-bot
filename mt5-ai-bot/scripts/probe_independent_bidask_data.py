#!/usr/bin/env python3
"""Discover independently hosted public H1 EURUSD bid/ask data links.

Discovery prints ONLY URLs and metadata. It never downloads bulk data,
touches a broker, accesses accounts, or claims strategy results.
"""
import html
import json
import re
import urllib.request
from urllib.parse import urljoin, urlparse

URL = "https://evtradelabs.com/data"
PATTERN = re.compile(
    r"""(?:href|src|data-url|url)=["']([^"']+)["']|(?:"|')([^"']*(?:\.json\.gz|\.csv\.gz|/api/[^"']*download)[^"']*)(?:"|')""",
    re.I
)


def http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Emtifize research source-verification/1.0",
        "Accept": "text/html,application/json",
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        content = response.read(2_500_000)
        return response.status, response.headers.get("Content-Type", ""), content


def main():
    try:
        status, content_type, raw = http_get(URL)
    except Exception as error:
        print(f"PROBE_ERROR: {type(error).__name__} {error}")
        return 0
    page = raw.decode("utf-8", errors="replace")
    print(f"PROBE_SOURCE status={status} type={content_type} bytes={len(raw)}")
    matches = set()
    for a, b in PATTERN.findall(page):
        link = html.unescape(a or b).replace("\\/", "/")
        if any(q in link.lower() for q in
               ("eurusd", "data", "download", ".json.gz", ".csv.gz", "api/")):
            if len(link) <= 500:
                matches.add(urljoin(URL, link))
    for link in sorted(matches)[:75]:
        print(f"FOUND_LINK {link}")
    for clue in ("EURUSD", "api/", ".json.gz", "download", "__NEXT_DATA__"):
        print(f"HTML_OCCURRENCES {clue} {page.lower().count(clue.lower())}")
    scripts = sorted(set(
        urljoin(URL, link) for link in re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']', page, flags=re.I
        )
        if urlparse(urljoin(URL, link)).hostname == urlparse(URL).hostname
    ))
    print(f"LOCAL_JS_BUNDLES {len(scripts)}")
    for js in scripts[:5]:
        try:
            status, typ, raw = http_get(js)
            code = raw.decode("utf-8", errors="replace")
            for match in re.findall(r'.{0,70}(?:\.json\.gz|/api/[^" ]{0,60}|EURUSD.{0,80}).{0,30}', code, flags=re.I):
                if len(match) < 250:
                    print(f"JS_CLUE {match[:225]}")
            print(f"JS_SCANNED status={status} bytes={len(raw)}")
        except Exception as error:
            print(f"JS_UNAVAILABLE {type(error).__name__}")
    try:
        status, typ, raw = http_get("https://evtradelabs.com/api/data/catalog")
        catalog = json.loads(raw)
        print(f"CATALOG_RESPONSE type={type(catalog).__name__} bytes={len(raw)}")
        print(f"CATALOG_KEYS {list(catalog)[:20] if isinstance(catalog,dict) else 'array'}")
        entries = catalog.get("files", []) if isinstance(catalog, dict) else catalog
        print(f"CATALOG_ENTRIES {len(entries) if isinstance(entries,list) else type(entries).__name__}")
        if isinstance(entries, list):
            for row in entries:
                if not isinstance(row, dict):
                    continue
                encoded = json.dumps(row, ensure_ascii=False)
                if ("EURUSD" in encoded and "H1" in encoded and
                        any(y in encoded for y in ("2022","2023","2024","2025"))):
                    print(f"CATALOG_EURUSD {encoded[:700]}")
    except Exception as error:
        print(f"CATALOG_ERROR {type(error).__name__}: {str(error)[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
