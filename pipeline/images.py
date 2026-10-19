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
# A place's or organization's Wikidata picture is often a map, flag, seal or logo: not a news photo.
NOT_A_PHOTO = re.compile(r"\b(flag|flags|coat[ _]of[ _]arms|seal|emblem|logo|logotype|wordmark|insignia|diagram|chart)\b", re.I)
# A map is not a photo, but for a country or region with no photo it is the right picture (Heston, 2026-10-19).
MAP = re.compile(r"\b(map|maps|locator|location|orthographic|globe|satellite)\b", re.I)
# Nothing graphic: judged on the file name and on the file's own Commons description and categories.
GRAPHIC = re.compile(r"\b(patients?|victims?|corpses?|cadavers?|dead bod(y|ies)|bodies|wounded|injur(y|ies|ed)|blood(y|ied)?|bleeding|"
                     r"autops(y|ies)|lesions?|rash|gore|graphic|casualt(y|ies)|funerals?|burials?|massacre|executions?|killed|"
                     r"died|dying|deceased|sick|case #?\d)\b", re.I)  # not "wound": "tightly wound" describes a virus filament
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
        if kind == "place" and not val(e, "P625"):
            continue  # a place must have coordinates: "china" the tableware is not China the country
        if val(e, "P171") or val(e, "P105"):
            continue  # a species is never the subject: "turkey" the bird, "apple" the fruit
        if kind == "organization" and not any(val(e, p) for p in ("P571", "P159", "P112", "P856")):
            continue  # an organization has a founding date, headquarters, founder or website
        cands.append((len(e.get("sitelinks", {})), q, e))
    cands.sort(key=lambda c: -c[0])
    if not cands:
        return None
    if kind != "person" and len(cands) > 1 and cands[0][0] < 3 * max(cands[1][0], 1):
        return None  # two real places or bodies share the name (Georgia the country, Georgia the state): no guess
    if kind == "person" and len(cands) > 1:
        # Several living people share the name: take the most widely documented one only when it is
        # clearly the famous one (at least 20 linked Wikipedias and 5 times the next), else no image.
        top, nxt = cands[0][0], cands[1][0]
        if top < 20 or top < 5 * max(nxt, 1):
            return None
    _, qid, ent = cands[0]
    rec = _record(qid, ent, name, "Photo" if kind == "person" else "Image")
    if not rec and kind == "place":
        rec = _record(qid, ent, name, "Map", maps=True)  # no photo of the place: its map
    return rec


def image_for_title(title):
    """The main picture of an exact English Wikipedia article (resolved to its Wikidata entity), for a story
    with no person to show: "Ebola virus", "Africa CDC". A person's article still has to be a living person."""
    title = (title or "").strip()
    if not title:
        return None
    ents = _get("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbgetentities", "sites": "enwiki", "titles": title, "props": "claims|sitelinks", "normalize": 1,
         "format": "json"})).get("entities", {})
    qid, ent = next(((q, e) for q, e in ents.items() if q.startswith("Q") and "missing" not in e), (None, None))
    if not qid:
        return None
    val = lambda p: [c["mainsnak"].get("datavalue", {}).get("value") for c in ent.get("claims", {}).get(p, [])]
    if any(isinstance(v, dict) and v.get("id") == "Q5" for v in val("P31")) and val("P570"):
        return None  # a historical person is never today's picture
    label = (ent.get("sitelinks", {}).get("enwiki") or {}).get("title", title)
    return _record(qid, ent, label, "Image")


def _record(qid, ent, label, word, maps=False):
    """The first P18 file that is a real picture (not a map, flag, seal or logo), not graphic, freely
    licensed, and a JPEG, PNG or WebP. Downloaded to data/images so readers only contact our domain."""
    files = [c["mainsnak"]["datavalue"]["value"] for c in ent.get("claims", {}).get("P18", []) if "datavalue" in c["mainsnak"]]
    for f in files:
        fn = f.replace("_", " ")
        if NOT_A_PHOTO.search(fn) or GRAPHIC.search(fn) or (bool(MAP.search(fn)) != maps):
            continue  # photos pass first; maps only when asked for (a place with no photo)
        page = next(iter(_get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "titles": "File:" + f, "prop": "imageinfo", "iiprop": "url|extmetadata|mime",
             "iiurlwidth": 1200, "format": "json"}))["query"]["pages"].values()))
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        mime = info.get("mime")
        if mime == "image/svg+xml" and maps and (info.get("thumburl") or "").endswith(".png"):
            mime = "image/png"  # Commons renders vector maps to PNG; use that copy
        elif mime not in ("image/jpeg", "image/png", "image/webp"):
            continue
        md = info.get("extmetadata", {})
        about = _plain(md.get("ImageDescription", {}).get("value")) + " " + _plain(md.get("Categories", {}).get("value"))
        if GRAPHIC.search(about) or NOT_A_PHOTO.search(_plain(md.get("Categories", {}).get("value"))) or \
                (not maps and MAP.search(_plain(md.get("Categories", {}).get("value")))):
            continue  # the file's own description or categories say it is graphic, or a map or logo
        license_ = _plain(md.get("LicenseShortName", {}).get("value"))
        if not ALLOWED.match(license_):
            continue
        artist = _plain(md.get("Artist", {}).get("value")) or "Unknown author"
        artist = re.sub(r"^(.+?)(?:\s+\1)+$", r"\1", artist)  # "Unknown author Unknown author" -> once
        url = info.get("thumburl") or info.get("url")
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
        fname = hashlib.sha1(url.encode()).hexdigest()[:12] + "." + ext
        out = ROOT / "data/images" / fname
        out.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30, context=C.SSL_CTX) as r:
            data = r.read(8_000_000)
        out.write_bytes(data)
        return {
            "src": f"data/images/{fname}", "alt": label, "subject": label, "wikidata": qid,
            "about": about.strip()[:500],  # the file's own description and categories, for the relevance check
            "artist": artist[:120], "license": license_, "source": info.get("descriptionurl"),
            "caption": f"{label}. {word}: {artist[:80]} · {license_} · Wikimedia Commons",
        }
    return None


if __name__ == "__main__":
    import sys
    print(json.dumps(image_for(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "person"), indent=1))
