"""Imagery: one license-verified photo of a story's main subject, or none.

Rules (from the fACTUAL design, Figma card 20:2):
- Only images whose license code can verify: Wikimedia Commons files under public domain, CC0,
  CC BY or CC BY-SA, read from the Commons API. Never outlet or wire photos, never AI images.
- A person gets the image attached to their own Wikidata entity (usually an official portrait),
  found by exact name match and, for people, only if the entity is a human. Never a keyword search.
- Every image carries what it shows, who made it, its license and its source page.
- No safe image means no image.
The image is copied to the site during the scan, so a reader's browser contacts only our domain.
"""
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import check as C

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)"}
ALLOWED = re.compile(r"^(public domain|pd\b|cc0|cc by(-sa)? \d(\.\d)?)", re.I)


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20, context=C.SSL_CTX) as r:
        return json.loads(r.read())


def _plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def image_for(name, kind):
    """Return a public record for the subject's image, or None. Downloads the file to data/images/."""
    name = (name or "").strip()
    if not name or kind not in ("person", "organization", "place"):
        return None
    api = "https://www.wikidata.org/w/api.php?"
    hits = _get(api + urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 10})).get("search", [])
    # The name must be the entity's own label or one of its listed aliases ("Volodymyr Zelensky" is an alias
    # of "Volodymyr Zelenskyy"), read from the entity itself. Never a partial or keyword match.
    ids = [h["id"] for h in hits][:10]
    if not ids:
        return None
    ents = _get(api + urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|aliases|sitelinks|claims",
                                               "languages": "en", "format": "json"})).get("entities", {})
    # Compare whole names, case-folded, with doubled letters collapsed so a transliteration variant still
    # matches ("Zelensky" = "Zelenskyy"). Still a full-name match, never partial.
    fold = lambda t: re.sub(r"(.)\1+", r"\1", (t or "").casefold())
    names = lambda e: {fold((e.get("labels", {}).get("en") or {}).get("value"))} | {fold(a["value"]) for a in e.get("aliases", {}).get("en", [])}
    ids = [q for q in ids if fold(name) in names(ents.get(q, {}))]
    if not ids:
        return None
    val = lambda e, p: [c["mainsnak"].get("datavalue", {}).get("value") for c in e.get("claims", {}).get(p, [])]
    cands = []
    for q in ids:
        e = ents.get(q, {})
        is_human = any(isinstance(v, dict) and v.get("id") == "Q5" for v in val(e, "P31"))
        if kind == "person" and (not is_human or val(e, "P570")):
            continue  # people must be living humans: a historical namesake is never today's subject
        cands.append((len(e.get("sitelinks", {})), q, e))
    cands.sort(key=lambda c: -c[0])
    if not cands:
        return None
    if kind == "person" and len(cands) > 1:
        # Several living people share the name: take the most widely documented one only when it is
        # clearly the famous one (at least 20 linked Wikipedias and 5 times the next), else no image.
        top, nxt = cands[0][0], cands[1][0]
        if top < 20 or top < 5 * max(nxt, 1):
            return None
    _, qid, ent = cands[0]
    claims = ent.get("claims", {})
    files = [c["mainsnak"]["datavalue"]["value"] for c in claims.get("P18", []) if "datavalue" in c["mainsnak"]]
    if not files:
        return None
    page = next(iter(_get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "titles": "File:" + files[0], "prop": "imageinfo", "iiprop": "url|extmetadata|mime",
         "iiurlwidth": 1200, "format": "json"}))["query"]["pages"].values()))
    info = (page.get("imageinfo") or [None])[0]
    if not info or info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
        return None
    md = info.get("extmetadata", {})
    license_ = _plain(md.get("LicenseShortName", {}).get("value"))
    if not ALLOWED.match(license_):
        return None
    artist = _plain(md.get("Artist", {}).get("value")) or "Unknown author"
    artist = re.sub(r"^(.+?)(?:\s+\1)+$", r"\1", artist)  # "Unknown author Unknown author" -> once
    url = info.get("thumburl") or info.get("url")
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[info["mime"]]
    fname = hashlib.sha1(url.encode()).hexdigest()[:12] + "." + ext
    out = ROOT / "data/images" / fname
    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30, context=C.SSL_CTX) as r:
        data = r.read(8_000_000)
    out.write_bytes(data)
    label = name
    return {
        "src": f"data/images/{fname}", "alt": label, "subject": label, "wikidata": qid,
        "artist": artist[:120], "license": license_, "source": info.get("descriptionurl"),
        "caption": f"{label}. Photo: {artist[:80]} · {license_} · Wikimedia Commons",
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(image_for(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "person"), indent=1))
