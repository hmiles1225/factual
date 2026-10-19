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
UA = "fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)"
ATOM = "{http://www.w3.org/2005/Atom}"
SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"
# python.org builds on macOS ship without CA certs; fall back to the system bundle.
_CA = "/etc/ssl/cert.pem"
SSL_CTX = ssl.create_default_context(cafile=_CA) if os.path.exists(_CA) else ssl.create_default_context()
# Below this share of working feeds, the scan fails so the site keeps its last good data.
MIN_FEED_SHARE = 2 / 3
# A feed whose newest item is older than this has stopped updating. It counts as failed,
# so a dead feed can never pass old stories off as today's news.
MAX_FEED_AGE_HOURS = 72
# Every outlet is read over the same window, so a long feed can't make one outlet look
# like it covers more stories than another.
MAX_ITEM_AGE_HOURS = 48
# Articles are kept for this long across scans, so slower topics (environment, science, health) can be
# grouped over a week: one outlet covers a story on Monday, another on Wednesday. Same window for all.
POOL_DAYS = 7
LIVE_ARTICLES = "https://hestonmiles.com/factual/data/articles.json"


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
    for it in root.iter(f"{SITEMAP}url"):  # Google News sitemap (outlets with no RSS)
        news = it.find(f"{NEWS}news")
        if news is None:
            continue
        items.append({
            "source": source,
            "title": clean(news.findtext(f"{NEWS}title")),
            "url": (it.findtext(f"{SITEMAP}loc") or "").strip(),
            "published": when(news.findtext(f"{NEWS}publication_date")),
            "summary": "",
        })
    return [i for i in items if i["title"] and i["url"]]


def fetch(feed):
    req = urllib.request.Request(feed["url"], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
            items = parse(r.read(), feed["source"])
        dated = [i["published"] for i in items if i["published"]]
        if not dated:
            return feed["source"], [], "no dated items"
        newest = max(dated)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(newest)).total_seconds() / 3600
        if age > MAX_FEED_AGE_HOURS:
            return feed["source"], [], f"stale: newest item {newest[:10]}"
        cutoff = datetime.now(timezone.utc).timestamp() - MAX_ITEM_AGE_HOURS * 3600
        items = [i for i in items if i["published"] and datetime.fromisoformat(i["published"]).timestamp() >= cutoff]
        return feed["source"], items, None
    except Exception as e:  # report every failure; never hide a dead feed
        return feed["source"], [], f"{type(e).__name__}: {e}"[:120]


def fetch_outlet(feed):
    """The outlet's main feed decides whether it worked; its section feeds (health, science, climate)
    add articles when they work, and a failing section is reported without failing the outlet."""
    source, items, err = fetch(feed)
    for url in feed.get("sections", []):
        _, more, serr = fetch({"source": source, "url": url})
        if serr:
            print(f"  section {source}: {url} {serr}")
        items += more
    return source, items, err


def main():
    cfg = json.loads((ROOT / "pipeline/feeds.json").read_text())
    # A region edition (the Texas demo) reads its own outlets only until its cutoff.
    now = datetime.now(timezone.utc)
    live = {k for k, r in cfg.get("regions", {}).items() if now < datetime.fromisoformat(r["until"])}
    feeds = [f for f in cfg["feeds"] if not f.get("region") or f["region"] in live]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_outlet, feeds))
    articles, failed, status = [], 0, []
    for source, items, err in results:
        if err:
            failed += 1
            print(f"  FAIL  {source:<22} {err}")
        else:
            print(f"  ok    {source:<22} {len(items)} articles")
            articles.extend(items)
        status.append({"source": source, "ok": not err, "articles": len(items), "error": err})
    seen, unique = set(), []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    fresh = len(unique)
    # Carry forward last scan's articles that are still inside the pool window. Never fatal.
    pool_cut = datetime.now(timezone.utc).timestamp() - POOL_DAYS * 86400
    try:
        with urllib.request.urlopen(urllib.request.Request(LIVE_ARTICLES, headers={"User-Agent": UA}), timeout=30, context=SSL_CTX) as r:
            for a in json.loads(r.read()).get("articles", []):
                if a.get("url") and a["url"] not in seen and a.get("published") \
                        and datetime.fromisoformat(a["published"]).timestamp() >= pool_cut:
                    seen.add(a["url"])
                    unique.append(a)
    except Exception as e:
        print(f"  pool: last scan's articles not readable ({e}); this scan starts the pool fresh")
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(), "count": len(unique), "fresh": fresh,
           "pool_days": POOL_DAYS, "feeds": status, "articles": unique}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/articles.json").write_text(json.dumps(out, indent=1))
    print(f"\n{fresh} new articles from {len(feeds) - failed} of {len(feeds)} feeds, {len(unique)} in the {POOL_DAYS}-day pool -> data/articles.json")
    if len(feeds) - failed < MIN_FEED_SHARE * len(feeds):
        print(f"Too few feeds worked ({len(feeds) - failed} of {len(feeds)}). Not publishing this scan.")
        return 1
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
