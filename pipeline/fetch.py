"""Stage 1: pull the latest headlines from every feed in feeds.json.

Standard library only. Writes data/articles.json and prints a status line per
feed, so a dead or blocked feed is visible instead of silently missing.
"""
import html
import json
import os
import re
import ssl
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "fACTUAL-scan/0.1 (+https://factual.hestonmiles.com)"
ATOM = "{http://www.w3.org/2005/Atom}"
# python.org builds on macOS ship without CA certs; fall back to the system bundle.
_CA = "/etc/ssl/cert.pem"
SSL_CTX = ssl.create_default_context(cafile=_CA) if os.path.exists(_CA) else ssl.create_default_context()
# Below this share of working feeds, the scan fails so the site keeps its last good data.
MIN_FEED_SHARE = 2 / 3


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def when(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def parse(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):  # RSS 2.0
        items.append({
            "source": source,
            "title": clean(it.findtext("title")),
            "url": (it.findtext("link") or "").strip(),
            "published": when(it.findtext("pubDate")),
            "summary": clean(it.findtext("description"))[:500],
        })
    for it in root.iter(f"{ATOM}entry"):  # Atom
        link = it.find(f"{ATOM}link")
        items.append({
            "source": source,
            "title": clean(it.findtext(f"{ATOM}title")),
            "url": link.get("href") if link is not None else "",
            "published": when(it.findtext(f"{ATOM}updated") or it.findtext(f"{ATOM}published")),
            "summary": clean(it.findtext(f"{ATOM}summary"))[:500],
        })
    return [i for i in items if i["title"] and i["url"]]


def fetch(feed):
    req = urllib.request.Request(feed["url"], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
            items = parse(r.read(), feed["source"])
        return feed["source"], items, None
    except Exception as e:  # report every failure; never hide a dead feed
        return feed["source"], [], f"{type(e).__name__}: {e}"[:120]


def main():
    feeds = json.loads((ROOT / "pipeline/feeds.json").read_text())["feeds"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, feeds))
    articles, failed = [], 0
    for source, items, err in results:
        if err:
            failed += 1
            print(f"  FAIL  {source:<22} {err}")
        else:
            print(f"  ok    {source:<22} {len(items)} articles")
            articles.extend(items)
    seen, unique = set(), []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(), "count": len(unique), "articles": unique}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/articles.json").write_text(json.dumps(out, indent=1))
    print(f"\n{len(unique)} articles from {len(feeds) - failed} of {len(feeds)} feeds -> data/articles.json")
    if len(feeds) - failed < MIN_FEED_SHARE * len(feeds):
        print(f"Too few feeds worked ({len(feeds) - failed} of {len(feeds)}). Not publishing this scan.")
        return 1
    return 0 if unique else 1


if __name__ == "__main__":
    sys.exit(main())
