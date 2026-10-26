"""Texas Election numbers: polls, the published poll averages, which polls each side reported, how far Texas
polls have missed before, and the money. No AI anywhere: every figure is parsed and checked in code.

Runs after cluster.py in the hourly scan and writes data/tx-numbers.json, which the race pages read
(story.html?s=tx-senate, s=tx-governor). Heston's calls, 2026-10-20: Senate and governor; show the averages
others publish rather than making our own; four stories (polls against their margin of error, which polls each
side's outlets reported, past polling misses, money inside and outside the campaigns).

Polls and averages come from Wikipedia's tables, which cite each pollster. A poll is shown only when its
pollster's own release, read by us, has both candidates' numbers near their names. The rest are counted and
named, never drawn. What was confirmed is read back from the live file, so each release is fetched once.
A failure here never blocks the scan: the site keeps the last file.
"""
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIVE_URL = "https://hestonmiles.com/factual/data/tx-numbers.json"
OUT = ROOT / "data/tx-numbers.json"
VERSION = "1"
SQUASH_V = "2"           # 2: quotes compared on letters, digits and % only
MONEY_V = "3"            # 2: governor accounts by TEC filer id, cash on hand only. 3: outside spending counted once, checked
RECENT_DAYS = 30          # the polls drawn: fielded (end date) within this many days of the scan
WIKI_API = "https://en.wikipedia.org/w/api.php"
FEC_API = "https://api.open.fec.gov/v1"
GENERAL_FROM = "2026-05-27"   # the day after Texas's primary runoff (May 26 2026)

# Candidates in Texas ballot order (the governor's party is listed first). FEC ids from the FEC's own search.
RACES = {
    "tx-senate": {"name": "U.S. Senate", "wiki": "2026_United_States_Senate_election_in_Texas",
                  "candidates": [{"name": "Ken Paxton", "party": "R", "fec": "S6TX00388"},
                                 {"name": "James Talarico", "party": "D", "fec": "S6TX00479"}]},
    "tx-governor": {"name": "Governor", "wiki": "2026_Texas_gubernatorial_election",
                    # Texas Ethics Commission filer ids (read from the TEC's cover sheets, 2026-10-20). Abbott's money is
                    # mostly in Texans for Greg Abbott (00051153), a committee beside his own account (00019652): their
                    # Sept 24 cash, $17,317,177 + $870,089, is the $18.2M the Texas Tribune reported. Hinojosa files as Regina.
                    "candidates": [{"name": "Greg Abbott", "party": "R", "tec": ["00019652", "00051153"]},
                                   {"name": "Gina Hinojosa", "party": "D", "tec": ["00080440"]}]},
}


# ---------- Wikipedia tables ----------

def wikitext(page):
    q = urllib.parse.urlencode({"action": "parse", "page": page, "prop": "wikitext|revid", "format": "json", "formatversion": 2})
    req = urllib.request.Request(f"{WIKI_API}?{q}", headers={"User-Agent": C.UA})
    with urllib.request.urlopen(req, timeout=30, context=C.SSL_CTX) as r:
        p = json.loads(r.read())["parse"]
    return p["wikitext"], p.get("revid")


def split_top(s, sep="|"):
    """Split on sep outside {{templates}} and [[links]]."""
    out, depth, cur, i = [], 0, "", 0
    while i < len(s):
        two = s[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; cur += two; i += 2; continue
        if two in ("}}", "]]"):
            depth = max(0, depth - 1); cur += two; i += 2; continue
        if s[i] == sep and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += s[i]
        i += 1
    out.append(cur)
    return out


def plain(s):
    """Wikitext to plain text: no refs, notes, templates, links or bold."""
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"\{\{\s*(efn|refn|efn-ua|sfn)[^{}]*\}\}", "", s, flags=re.I)
    s = re.sub(r"\{\{\s*nbsp\s*\}\}", " ", s, flags=re.I)
    s = re.sub(r"\{\{\s*(sdash|ndash|mdash|n/a|TBA|TBD)\s*\}\}", "", s, flags=re.I)
    s = re.sub(r"\{\{\s*nowrap\s*\|([^{}]*)\}\}", r"\1", s, flags=re.I)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"<[^>]+>", " ", s).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", s).strip()


def ref_url(cell, page):
    """The first cited URL in a cell: an inline cite, or a named ref defined elsewhere on the page."""
    for ref in re.finditer(r"<ref([^>]*)(/>|>(.*?)</ref>)", cell, flags=re.S):
        body = ref.group(3)
        if body is None:
            name = re.search(r"name\s*=\s*\"?([^\"/>]+?)\"?\s*$", ref.group(1).strip())
            if not name:
                continue
            d = re.search(r"<ref\s+name\s*=\s*\"?" + re.escape(name.group(1).strip()) + r"\"?\s*>(.*?)</ref>", page, flags=re.S)
            body = d.group(1) if d else ""
        m = re.search(r"\|\s*url\s*=\s*([^\s|}]+)", body) or re.search(r"\[(https?://[^\s\]]+)", body)
        if m:
            return m.group(1).strip()
    return None


def table_after(page, start, must):
    """The first wikitable at or after start whose header names every word in must: (header cells, rows)."""
    for m in re.finditer(r"\{\|", page[start:]):
        a = start + m.start()
        b = page.find("\n|}", a)
        t = page[a:b]
        head = t.split("\n|-")[0] + ("\n" + t.split("\n|-")[1] if t.split("\n|-")[0].count("\n!") == 0 else "")
        if all(w in head for w in must):
            return t
    return None


def cells_of(table):
    """Rows of cell texts (raw), with rowspans filled in. Header lines (!) are returned separately."""
    chunks = table.split("\n|-")
    header = [split_top(l[1:])[-1] for c in chunks[:2] for l in c.split("\n") if l.startswith("!")]
    rows, spans = [], {}
    for chunk in chunks[1:]:
        raw = [l for l in chunk.split("\n") if l.startswith("|") and not l.startswith("|}") and not l.startswith("|+")]
        if not raw or chunk.lstrip().startswith("!"):
            continue
        row, it = [], iter(raw)
        col = 0
        cells = list(it)
        k = 0
        while k < len(cells) or col in spans:
            if col in spans:
                val, left = spans[col]
                row.append(val)
                spans[col] = (val, left - 1)
                if left - 1 == 0:
                    del spans[col]
                col += 1
                continue
            line = cells[k][1:]
            k += 1
            parts = split_top(line)
            attrs, val = (parts[0], parts[-1]) if len(parts) > 1 else ("", parts[0])
            rs = re.search(r"rowspan\s*=\s*\"?(\d+)", attrs)
            if rs and int(rs.group(1)) > 1:
                spans[col] = (val, int(rs.group(1)) - 1)
            row.append(val)
            col += 1
        rows.append(row)
    return header, rows


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def end_date(text):
    """The last day of a field period: "October 8–16, 2026", "September 30 – October 14, 2026", "Oct 2, 2026"."""
    t = plain(text).replace("–", "-").replace("—", "-")
    year = re.findall(r"(\d{4})", t)
    if not year:
        return None
    last = t.split("-")[-1].strip()
    mon = [w for w in re.findall(r"[A-Za-z]+", t) if w.lower()[:3] in {k[:3] for k in MONTHS}]
    day = re.findall(r"\b(\d{1,2})\b", last) or re.findall(r"\b(\d{1,2})\b", t)
    if not mon or not day:
        return None
    m = next(v for k, v in MONTHS.items() if k[:3] == mon[-1].lower()[:3])
    try:
        return datetime(int(year[-1]), m, int(day[0])).date().isoformat()
    except ValueError:
        return None


def pct(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", plain(text))
    return float(m.group(1)) if m else None


ONE_SIDE = re.compile(r"campaign|\bPAC\b|supports|Party\b|Majority|Leadership Fund|Victory|Committee", re.I)


def notes_of(page):
    """Wikipedia's per-row client notes: {{efn-ua|name=Fox|Poll conducted for [[Fox News]]}} -> {"Fox": "..."}."""
    return {n.strip(): plain(t) for n, t in re.findall(r"\{\{[Ee]fn-ua\s*\|\s*name\s*=\s*\"?([^|\"}]+)\"?\s*\|(.*?)\}\}(?=[^}])", page)}


def sponsor_note(cell, notes):
    m = re.search(r"\{\{[Ee]fn-ua\s*\|\s*name\s*=\s*\"?([^|\"}]+)\"?\s*\}\}", cell)
    return notes.get(m.group(1).strip()) if m else None


def parse_polls(page, cands):
    """Head-to-head polls of the general election from the race page."""
    surnames = [c["name"].split()[-1] for c in cands]
    notes = notes_of(page)
    gen = page.find("General election")
    t = table_after(page, max(0, gen), ["Poll source"] + surnames)
    if not t:
        return []
    header, rows = cells_of(t)
    hp = [plain(h) for h in header]
    col = {s: next((i for i, h in enumerate(hp) if s in h), None) for s in surnames}
    src_i = next(i for i, h in enumerate(hp) if "Poll source" in h)
    date_i = next(i for i, h in enumerate(hp) if "administered" in h or "Date" in h)
    n_i = next((i for i, h in enumerate(hp) if "Sample" in h), None)
    moe_i = next((i for i, h in enumerate(hp) if "error" in h), None)
    polls = []
    for r in rows:
        if len(r) < len(hp) - 1 or None in col.values() or max(col.values()) >= len(r):
            continue
        name = plain(r[src_i])
        shares = [pct(r[col[s]]) for s in surnames]
        if not name or None in shares:
            continue
        samp = plain(r[n_i]) if n_i is not None else ""
        pop = re.search(r"\((LV|RV|A)\)", samp)
        n = re.search(r"([\d,]{2,})", samp)
        moe = re.search(r"(\d+(?:\.\d+)?)", plain(r[moe_i])) if moe_i is not None else None
        tags = re.findall(r"\(([RD])\)", name)
        client = sponsor_note(r[src_i], notes)
        polls.append({
            "pollster": re.sub(r"\s*\([RD]\)\s*", " ", name).replace(" /", "/").strip(),
            # The pollster's own lean as Wikipedia labels it (from the Texas Tribune): R, D, or both (a
            # bipartisan team, like Fox News's Beacon (D) and Shaw (R)).
            "affiliation": tags[0] if len(set(tags)) == 1 else "both" if tags else None,
            # Who paid, from Wikipedia's note on the row; one_side when a campaign, party or a group backing one does.
            "client": client, "one_side": bool(client and ONE_SIDE.search(client)),
            "dates": plain(r[date_i]), "end": end_date(r[date_i]),
            "n": int(n.group(1).replace(",", "")) if n else None, "pop": pop.group(1) if pop else None,
            "moe": float(moe.group(1)) if moe else None,
            "shares": shares, "url": ref_url(r[src_i], page),
        })
    return polls


def parse_averages(page, cands):
    """The 'Aggregate polls' table: each published average, as Wikipedia lists it."""
    surnames = [c["name"].split()[-1] for c in cands]
    gen = page.find("General election")
    t = table_after(page, max(0, gen), ["aggregation"] + surnames)
    if not t:
        return []
    header, rows = cells_of(t)
    hp = [plain(h) for h in header]
    col = {s: next((i for i, h in enumerate(hp) if s in h), None) for s in surnames}
    out = []
    for r in rows:
        name = plain(r[0]) if r else ""
        if not name or name.lower().startswith("average") or len(r) < len(hp) - 1:
            continue
        shares = [pct(r[col[s]]) for s in surnames]
        if None in shares:
            continue
        out.append({"source": name, "dates": plain(r[1]), "updated": plain(r[2]), "shares": shares, "url": ref_url(r[0], page)})
    return out


# ---------- two sources must agree ----------
# A poll is shown only when two independent reads agree: Wikipedia's table and our own read of the pollster's
# release. Gemini finds the head-to-head topline in the release and copies the passage; code confirms the passage
# is in the release, that it holds both numbers, and that they match Wikipedia's (to rounding: ActiVote's 51.9 is
# Wikipedia's 52). Pattern-matching alone was tried first and failed a swapped-numbers test (2026-10-20): crosstabs
# put dozens of plausible numbers beside every name.

POLL_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["found", "a_pct", "b_pct", "n", "moe", "quote"],
               "properties": {"found": {"type": "boolean"}, "a_pct": {"type": "number"}, "b_pct": {"type": "number"},
                              "n": {"type": "integer", "description": "Sample size for this result; 0 if not stated."},
                              "moe": {"type": "number", "description": "Margin of error in points for this sample; 0 if not stated."},
                              "quote": {"type": "string", "description": "The passage showing both numbers, copied exactly, at most 300 characters."}}}
POLL_PROMPT = """Below is the text of a poll release. Find this poll's head-to-head result in the Texas {office} race between
{a} and {b}{pop}. Use the result for the whole sample, never a subgroup (not by age, party, region and so on).
Give a_pct and b_pct exactly as the release prints them, and copy the passage that shows them, word for word.
Give the sample size and margin of error for that sample if the release states them, else 0.
If the release does not report this result, found is false.

Release:
{text}"""
AVG_PROMPT = """Below is the text of a page that publishes a polling average. Find its current average for the Texas {office}
race between {a} and {b}. Give a_pct and b_pct exactly as printed, and copy the passage that shows them, word for word.
n and moe are 0. If the page does not show this average, found is false.

Page:
{text}"""
NUMBER = re.compile(r"(?<![\d.])\d{1,2}(?:\.\d)?(?![\d])")


def squash(t):
    """Text and quotes compared the same way: casefolded, letters, digits, decimal points and % only, single
    spaces. PDF tables put dot leaders, column gaps and stray symbols between the words a quote keeps."""
    return " ".join(re.findall(r"[a-z0-9%]+(?:\.\d+)?", C.norm(t)))


def close(x, v):
    """A release number matches Wikipedia's when it rounds to it."""
    return abs(float(x) - v) < 0.5 if float(v).is_integer() else abs(float(x) - v) < 0.051


def read(url, pipes_left):
    """Our read of a page: directly, else through the fetch tool (a few per scan; it costs a little)."""
    text, info = C.fetch_page(url)
    if not text and pipes_left[0] > 0 and os.environ.get("ANTHROPIC_API_KEY"):
        pipes_left[0] -= 1
        text, info = C.fetch_via_anthropic(url)
    return text, info


def agree(text, prompt, want, ask, charge):
    """Ask for the numbers, then hold the answer to the page and to Wikipedia. Returns (ok, why, answer)."""
    out, usage = ask(prompt, POLL_SCHEMA)
    charge(usage)
    if not out.get("found"):
        return False, "the release does not report this result", out
    q, page = squash(out.get("quote", "")), squash(text)
    if len(q) < 12 or q not in page:
        return False, "the passage given is not in the release", out
    nums = [float(x) for x in NUMBER.findall(q)]
    got = [out.get("a_pct"), out.get("b_pct")]
    if not all(any(abs(x - g) < 0.051 for x in nums) for g in got):
        return False, "the passage does not show both numbers", out
    if not all(close(g, w) for g, w in zip(got, want)):
        return False, f"the release says {got[0]:g} to {got[1]:g}, Wikipedia {want[0]:g} to {want[1]:g}", out
    return True, "", out


def lead_moe(moe, shares):
    """Margin of error on the gap between two candidates: about twice the stated one. With shares p1, p2
    (fractions) the gap's standard error is sqrt((p1 + p2 - (p1 - p2)^2) / n); the stated margin is z*sqrt(0.25 / n)."""
    if not moe:
        return None
    p1, p2 = shares[0] / 100, shares[1] / 100
    return round(2 * moe * math.sqrt(p1 + p2 - (p1 - p2) ** 2), 1)


# ---------- money (FEC) ----------

def fec(path, **params):
    params["api_key"] = os.environ.get("FEC_API_KEY") or "DEMO_KEY"
    req = urllib.request.Request(f"{FEC_API}{path}?{urllib.parse.urlencode(params)}", headers={"User-Agent": C.UA})
    with urllib.request.urlopen(req, timeout=30, context=C.SSL_CTX) as r:
        return json.loads(r.read())


def fec_money(cands):
    """Campaign totals, and outside spending counted once. Groups file 24/48-hour notices first and repeat the same
    spending in their next regular report, so the raw list double-counts (2026-10-20: it showed $155M against
    Talarico). Counted: regular-report lines up to the last date that group's reports cover, then notices after
    it; superseded amendments and memo lines dropped. Shown only if the regular-report lines add up to the FEC's
    own processed total for the candidate (within 2%), so the counting is checked against the FEC itself."""
    out, all_ok = [], True
    for c in cands:
        if not c.get("fec"):
            continue
        tot = (fec(f"/candidate/{c['fec']}/totals/", cycle=2026).get("results") or [{}])[0]
        rows, last = [], None
        for _ in range(40):
            params = dict(candidate_id=c["fec"], cycle=2026, per_page=100, sort="-expenditure_date", **(last or {}))
            page = fec("/schedules/schedule_e/", **params)
            rows += page.get("results") or []
            last = (page.get("pagination") or {}).get("last_indexes")
            if not page.get("results") or not last:
                break
        day = lambda r: (r.get("expenditure_date") or r.get("dissemination_date") or "")[:10]
        cid = lambda r: r.get("committee_id") or (r.get("committee") or {}).get("committee_id") or ""
        name = lambda r: (r.get("committee") or {}).get("name") or r.get("committee_name") or "Unnamed group"
        keep = [r for r in rows if r.get("most_recent") is not False and r.get("memo_code") != "X" and r.get("memoed_subtotal") is not True]
        cutoff = {}
        for r in keep:
            if not r.get("is_notice"):
                cutoff[cid(r)] = max(cutoff.get(cid(r), ""), day(r))
        counted = [r for r in keep if not r.get("is_notice") or day(r) > cutoff.get(cid(r), "")]
        # The check: regular-report lines (every election) against the FEC's processed totals for the candidate.
        proc = fec("/schedules/schedule_e/by_candidate/", candidate_id=c["fec"], cycle=2026, per_page=100).get("results") or []
        check = {}
        for k in ("S", "O"):
            mine = sum(r.get("expenditure_amount") or 0 for r in keep if not r.get("is_notice") and r.get("support_oppose_indicator") == k)
            theirs = sum(r.get("total") or 0 for r in proc if r.get("support_oppose_indicator") == k)
            check[k] = {"regular_reports": round(mine), "fec_processed": round(theirs),
                        "ok": abs(mine - theirs) <= max(10000, 0.02 * max(mine, theirs))}
        ok = all(v["ok"] for v in check.values())
        all_ok = all_ok and ok
        # General election only: the primary's spending (a pro-Cornyn group spent $25M against Paxton) is another contest.
        general = lambda r: (r.get("election_type") or "").startswith("G") or (not r.get("election_type") and day(r) >= GENERAL_FROM)
        by = {}
        for r in counted:
            if general(r):
                k = (r.get("support_oppose_indicator"), name(r))
                by[k] = by.get(k, 0) + (r.get("expenditure_amount") or 0)
        top = lambda k: [{"group": g.title(), "usd": round(v)} for (s_, g), v in sorted(by.items(), key=lambda kv: -kv[1]) if s_ == k][:3]
        out.append({"name": c["name"], "party": c["party"], "fec": c["fec"],
                    "raised": tot.get("receipts"), "spent": tot.get("disbursements"),
                    "cash": tot.get("last_cash_on_hand_end_period"), "through": (tot.get("coverage_end_date") or "")[:10],
                    "outside_support": round(sum(v for (k, _), v in by.items() if k == "S")),
                    "outside_oppose": round(sum(v for (k, _), v in by.items() if k == "O")),
                    "top_support": top("S"), "top_oppose": top("O"),
                    "outside_check": {"rows": len(rows), "kept": len(keep), "counted": len(counted),
                                      "notices_dropped_usd": round(sum(r.get("expenditure_amount") or 0 for r in keep if r not in counted)), **check},
                    "url": f"https://www.fec.gov/data/candidate/{c['fec']}/?cycle=2026"})
    note = "Campaign: the candidate's own committee, the whole 2026 cycle (primary included)."
    if all_ok:
        note += (" Outside: spending by any group for or against the candidate in the general election, as reported to the FEC, "
                 "each expense counted once (a 24- or 48-hour notice and the regular report that repeats it are one expense).")
    return {"source": "FEC", "candidates": out, "outside_ok": all_ok, "note": note}


# ---------- money (Texas Ethics Commission, state races) ----------
# The TEC publishes every report as one zip (about 1 GB, rebuilt daily). Only cover.csv is read: each report's
# totals. A zip can be read in pieces, so this is four requests and about 28 MB, once a day.
TEC_ZIP = "https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip"


def _get(url, start=None, end=None, method="GET"):
    h = {"User-Agent": C.UA}
    if start is not None:
        h["Range"] = f"bytes={start}-{end}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h, method=method), timeout=300, context=C.SSL_CTX) as r:
        return r.read(), r.headers, r.geturl()


def zip_member(url, name):
    import struct, zlib
    _, head, url = _get(url, method="HEAD")
    size = int(head["Content-Length"])
    tail, _, _ = _get(url, size - 65536, size - 1)
    e = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[e + 12:e + 20])
    cd, _, _ = _get(url, cd_off, cd_off + cd_size - 1)
    i = 0
    while i < len(cd):
        f = struct.unpack("<IHHHHHHIIIHHHHHII", cd[i:i + 46])
        method, csize, nlen, xlen, clen, off = f[4], f[7], f[10], f[11], f[12], f[16]
        if cd[i + 46:i + 46 + nlen].decode() == name:
            hdr, _, _ = _get(url, off, off + 29)
            n2, x2 = struct.unpack("<HH", hdr[26:30])
            data, _, _ = _get(url, off + 30 + n2 + x2, off + 30 + n2 + x2 + csize - 1)
            return (zlib.decompress(data, -15) if method == 8 else data), head.get("Last-Modified")
        i += 46 + nlen + xlen + clen
    raise KeyError(name)


def tec_money(cands):
    """Cash on hand only. Raised and spent are left out: Abbott's campaign moves money between its two accounts
    (his own account's July to September 'raised' is exactly $4,750,000, a transfer), so adding their totals would
    count it twice. Cash at one date can't double-count."""
    import csv, io
    raw, modified = zip_member(TEC_ZIP, "cover.csv")
    ids = {i for c in cands for i in c.get("tec", [])}
    rows = [r for r in csv.DictReader(io.StringIO(raw.decode("latin-1"))) if r["filerIdent"] in ids and r["periodEndDt"] >= "20250101"]
    out = []
    for c in cands:
        latest = {}
        for r in rows:
            if r["filerIdent"] in c["tec"]:
                cur = latest.get(r["filerIdent"])
                if not cur or (r["periodEndDt"], r["filedDt"]) > (cur["periodEndDt"], cur["filedDt"]):
                    latest[r["filerIdent"]] = r
        if len(latest) != len(c["tec"]) or len({r["periodEndDt"] for r in latest.values()}) != 1:
            continue  # an account missing, or reports ending on different days: no total we can stand behind
        end = next(iter(latest.values()))["periodEndDt"]
        out.append({"name": c["name"], "party": c["party"], "cash": round(sum(float(r["contribsMaintainedAmount"] or 0) for r in latest.values())),
                    "accounts": [r["filerName"] for r in latest.values()], "through": end,
                    "url": "https://www.ethics.state.tx.us/search/cf/"})
    return {"source": "Texas Ethics Commission", "file_date": modified, "candidates": out,
            "note": "Cash on hand in every account the campaign reports to the Texas Ethics Commission. Raised and spent are "
                    "left out: one campaign moves money between its accounts, so adding their totals would count it twice."}


# ---------- which polls each side's outlets reported ----------
# Matched in code from our own article pool: an article from a placed outlet, in a Texas race story, that names a
# pollster in its headline or summary. The poll it means is that pollster's latest one for the race released by the
# article's date. Kept across scans (read back from the live file), so the record grows through Election Day.
ALIASES = {"University of Houston": ["university of houston", "hobby school", "uh poll", "uh statewide poll", "uh hobby"],
           "University of Texas/Texas Politics Project": ["texas politics project", "university of texas/texas politics", "ut/texas politics", "ut-tyler"],
           "Beacon Research/Shaw & Co. Research": ["fox news poll", "fox news survey"],
           "CBS News/YouGov": ["cbs news poll", "cbs news/yougov", "cbs/yougov"],
           "New York Times/Siena University": ["new york times/siena", "times/siena", "nyt/siena"],
           "ReconMR/Siena University": ["reconmr"]}


def pollster_keys(name):
    if name in ALIASES:
        return ALIASES[name]
    parts = [p.strip().lower() for p in re.split(r"/| and ", name) if len(p.strip()) >= 4]
    generic = {"university", "research", "polling", "group", "poll", "news", "the", "college", "insights", "strategies"}
    keys = []
    for p in parts:
        core = " ".join(w for w in p.split() if w not in generic)
        if len(core) >= 5 and core not in ("yougov", "siena"):  # shared by several polls: needs the partner's name
            keys.append(core)
    return keys or [name.lower()]


def race_articles(rid):
    """This race's articles from the scan: Texas election coverage (cluster.tx_admit) whose first matching race
    (cluster.TX_RACES) is this one. Stories are grouped by event, so the race is read from the articles."""
    import cluster as CL
    path = ROOT / "data/articles.json"
    if not path.exists():
        return []
    feeds = json.loads((ROOT / "pipeline/feeds.json").read_text())
    region = {f["source"] for f in feeds["feeds"] if f.get("region")}
    key = rid.split("-", 1)[1]
    out = []
    for a in json.loads(path.read_text())["articles"]:
        if CL.tx_admit(a, a["source"] in region):
            if next((k for k, _, rx in CL.TX_RACES if rx.search(CL.text_for(a))), None) == key:
                out.append(a)
    return out


def cited_polls(rid, all_polls, prior):
    stories = json.loads((ROOT / "data/stories.json").read_text()) if (ROOT / "data/stories.json").exists() else {}
    side = {f["source"]: f.get("side", "unplaced") for f in stories.get("feeds", [])}
    keep = {c["url"]: c for c in prior}
    for a in race_articles(rid):
        text = f"{a.get('title', '')}. {a.get('summary') or ''}".lower()
        if " poll" not in text and "survey" not in text:
            continue
        day = (a.get("published") or "")[:10]
        for name in sorted({p["pollster"] for p in all_polls}):
            if not any(k in text for k in pollster_keys(name)):
                continue
            theirs = [p for p in all_polls if p["pollster"] == name and p["end"] and (not day or p["end"] <= day)]
            if not theirs:
                continue
            p = max(theirs, key=lambda p: p["end"])
            keep[a["url"]] = {"url": a["url"], "outlet": a["source"], "side": side.get(a["source"], "unplaced"),
                              "title": a.get("title", ""), "day": day, "pollster": name, "poll_end": p["end"], "shares": p["shares"]}
            break
    return sorted(keep.values(), key=lambda c: c["day"], reverse=True)


# ---------- history and the forecast ----------

def history():
    h = json.loads((Path(__file__).resolve().parent / "tx_history.json").read_text())
    for r in h["races"]:
        res = r["result"]
        if "r_votes" in res:
            res["r_pct"], res["d_pct"] = round(100 * res["r_votes"] / res["total"], 2), round(100 * res["d_votes"] / res["total"], 2)
        r["result_margin"] = round(res["r_pct"] - res["d_pct"], 1)
        r["miss"] = round(r["result_margin"] - r["poll"]["margin"], 1)   # positive: the Republican did better than the polls
    misses = [r["miss"] for r in h["races"]]
    h["typical_miss"] = round(math.sqrt(sum(m * m for m in misses) / len(misses)), 1)  # root mean square: both directions alike
    return h


def t_cdf(t, df):
    """Student's t distribution function, closed form (df a whole number)."""
    th = math.atan(t / math.sqrt(df))
    s, c = math.sin(th), math.cos(th)
    if df % 2:  # odd
        term, acc = c, c if df > 1 else 0.0
        for k in range(1, (df - 1) // 2):
            term *= c * c * (2 * k) / (2 * k + 1)
            acc += term
        a = (2 / math.pi) * (th + s * acc) if df > 1 else (2 / math.pi) * th
    else:
        term, acc = 1.0, 1.0
        for k in range(1, df // 2):
            term *= c * c * (2 * k - 1) / (2 * k)
            acc += term
        a = s * acc
    return 0.5 + a / 2


def forecast(averages, cands, hist):
    """Chance each candidate wins: centered on the middle of the published averages, spread as wide as Texas's past
    polling misses (both directions alike), with a t distribution's wider tails because eight races is a small sample.
    Heston's call, 2026-10-20: percentage only."""
    margins = sorted(a["shares"][0] - a["shares"][1] for a in averages)  # first candidate minus second
    if len(margins) < 3:
        return None
    k = len(margins)
    center = margins[k // 2] if k % 2 else (margins[k // 2 - 1] + margins[k // 2]) / 2
    df = len(hist["races"]) - 1
    p_first = t_cdf(center / hist["typical_miss"], df)
    return {"center": round(center, 2), "spread": hist["typical_miss"], "df": df, "averages": k,
            "chance": [round(100 * p_first), 100 - round(100 * p_first)],
            "method": f"the middle of {k} published averages, and how far Texas polls have missed: in {len(hist['races'])} races "
                      f"since 2016, RealClearPolitics' final average missed the result by {hist['typical_miss']} points on average, "
                      f"in both directions. Wider tails than a bell curve, because {len(hist['races'])} races is a small sample."}


# ---------- polls by group (crosstabs) ----------
# Heston, 2026-10-26: demographic numbers for both races, as their own story. Crosstab tables are where reading a
# number goes wrong (a flattened PDF table puts every column's number in one line), so a group's numbers are kept
# only when two models reading the release on their own agree (Gemini and Claude Haiku), the quoted passage is in
# the release with both numbers, the two shares add up like a vote (60 to 101), and the headline result sits
# between a category's groups (men and women bracket the total). Every poll's number is shown, never a blend.
GROUPS_LIVE = True       # 2026-10-26: first batch (5 releases, 18 numbers) checked by hand against the releases: all correct
CROSS_V = "1"
CROSS_PER_SCAN = 6
HAIKU = "claude-haiku-5-5"
CANON = [  # (category, label, pattern on the group's name as printed); first match wins
    ("gender", "Men", r"^(men|male|males|m)$|^(men|male|males)\b"), ("gender", "Women", r"^(women|female|females|f)$|^(women|female|females)\b"),
    ("race", "White", r"^(white|anglo)"), ("race", "Black", r"^(black|african)"), ("race", "Hispanic", r"^(hispanic|latin)"),
    ("party", "Republicans", r"^republican"), ("party", "Democrats", r"^democrat"), ("party", "Independents", r"^independent"),
    ("education", "No college degree", r"(no college|non-college|without a (college|4-year)|high school|less than (a )?college|no degree)"),
    ("education", "College degree", r"(college (grad|degree|educated)|bachelor|4-year degree|postgrad|graduate degree)"),
    ("area", "Urban", r"^urban"), ("area", "Suburban", r"^suburban"), ("area", "Rural", r"^rural"),
]
AGE = re.compile(r"(\d{2})\s*(?:-|to|\u2013)\s*(\d{2})|(\d{2})\s*\+|(\d{2})\s+and\s+(?:older|over|up)|under\s+(\d{2})", re.I)
CROSS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["groups"], "properties": {"groups": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["group", "a_pct", "b_pct", "quote"],
    "properties": {"group": {"type": "string"}, "a_pct": {"type": "number"}, "b_pct": {"type": "number"}, "quote": {"type": "string"}}}}}}
CROSS_PROMPT = """Below is the text of a poll release. Find this poll's head-to-head result in the Texas {office} race between
{a} and {b}{pop}, broken down by group: gender, age, race or ethnicity, party, education, urban/suburban/rural.
For each group give {a}'s and {b}'s percentages exactly as printed (a_pct, b_pct) and copy the passage that shows them,
word for word. Only the vote-choice question for this race: never the share of the sample a group makes up, never
another question or race. If the release has no breakdown for this race, return an empty list.{json}

Release:
{text}"""


WORD_SETS = [{"men", "women", "male", "female", "males", "females"}, {"white", "black", "hispanic", "latino", "latina", "latinos", "asian", "anglo"},
             {"republican", "republicans", "democrat", "democrats", "democratic", "independent", "independents"},
             {"college", "degree", "degrees", "graduate", "graduates", "bachelor", "postgrad"}, {"urban", "suburban", "rural"}]
SUBSET_WORDS = {"evangelical", "evangelicals", "catholic", "catholics", "christian", "christians", "protestant", "veterans",
                "parents", "married", "single", "union", "suburban women", "trump", "biden", "harris", "voters who"}


def canon(name):
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    words = set(re.findall(r"[a-z]+", n))
    # A compound group ("white men without a college degree", "white evangelical Christians") is a different
    # group from "White": never filed under one of its parts.
    if sum(bool(words & ws) for ws in WORD_SETS) > 1 or any(w in n for w in SUBSET_WORDS) or (AGE.search(n) and words & set().union(*WORD_SETS)):
        return None
    m = AGE.search(n)
    if m:
        lo, hi, plus, older, under = m.groups()
        return "age", (f"{lo}\u2013{hi}" if lo else f"{plus or older}+" if (plus or older) else f"Under {under}")
    for cat, label, pat in CANON:
        if re.search(pat, n):
            return cat, label
    return None


def haiku_json(prompt):
    import anthropic
    resp = anthropic.Anthropic(max_retries=3).messages.create(model=HAIKU, max_tokens=3000, messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text[text.find("{"): text.rfind("}") + 1]), {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}


def crosstabs(text, race, cands, poll, ask, charge, ask2):
    """Groups both readers agree on, held to the release and to sense. Returns (rows, notes)."""
    pop = {"LV": " among likely voters", "RV": " among registered voters"}.get(poll["pop"], "")
    base = (CROSS_PROMPT.replace("{office}", race["name"]).replace("{a}", cands[0]["name"]).replace("{b}", cands[1]["name"])
            .replace("{pop}", pop).replace("{text}", text[:150000]))
    g, usage = ask(base.replace("{json}", ""), CROSS_SCHEMA)
    charge(usage)
    h = ask2(base.replace("{json}", '\nReply with JSON only: {"groups": [{"group": "...", "a_pct": 0, "b_pct": 0, "quote": "..."}]}'))
    theirs = {}
    for r in h.get("groups", []):
        k = canon(r.get("group"))
        if k and isinstance(r.get("a_pct"), (int, float)) and isinstance(r.get("b_pct"), (int, float)):
            theirs[k] = (float(r["a_pct"]), float(r["b_pct"]))
    page, rows, notes = squash(text), [], []
    for r in g.get("groups", []):
        k = canon(r.get("group"))
        a, b = r.get("a_pct"), r.get("b_pct")
        if not k or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        why = None
        if k not in theirs or abs(theirs[k][0] - a) > 0.51 or abs(theirs[k][1] - b) > 0.51:
            why = "the two readings disagree"
        elif not (60 <= a + b <= 101):
            why = "the shares don't add up like a vote"
        else:
            q = squash(r.get("quote", ""))
            nums = [float(x) for x in NUMBER.findall(q)]
            if len(q) < 8 or q not in page:
                why = "the passage is not in the release"
            elif not all(any(abs(x - v) < 0.051 for x in nums) for v in (a, b)):
                why = "the passage does not show both numbers"
        if why:
            notes.append(f"{r.get('group')}: {why}")
        else:
            rows.append({"category": k[0], "group": k[1], "shares": [round(a, 1), round(b, 1)]})
    # The headline result sits between a category's groups (men and women bracket the total). Party is exempt.
    for cat in {r["category"] for r in rows} - {"party", "age"}:
        these = [r for r in rows if r["category"] == cat]
        if len(these) >= 2 and not all(min(r["shares"][i] for r in these) - 1.5 <= poll["shares"][i] <= max(r["shares"][i] for r in these) + 1.5 for i in (0, 1)):
            notes.append(f"{cat}: the groups don't bracket the headline result; all dropped")
            rows = [r for r in rows if r["category"] != cat]
    return rows, notes


# ---------- the run ----------

def load_live():
    try:
        req = urllib.request.Request(LIVE_URL, headers={"User-Agent": C.UA})
        with urllib.request.urlopen(req, timeout=20, context=C.SSL_CTX) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"tx_numbers: no live file ({e}); starting fresh")
        return {}


def main():
    now = datetime.now(timezone.utc)
    tx = json.loads((ROOT / "pipeline/feeds.json").read_text()).get("regions", {}).get("tx")
    if not tx or now >= datetime.fromisoformat(tx["until"]):
        print("tx_numbers: the Texas edition is over; the last file stays up")
        return 0
    live = load_live()
    cache = live.get("confirmed", {}) if live.get("version") == VERSION else {}
    # Quotes from PDF tables failed an over-strict comparison until 2026-10-20 (squash): check those again.
    cache = {k: v for k, v in cache.items() if v.get("why") != "the passage given is not in the release" or v.get("squash") == SQUASH_V}
    lib_path = ROOT / "data/library.json"
    lib = json.loads(lib_path.read_text()) if lib_path.exists() else None
    ask = charge = None
    if lib is not None and os.environ.get("GEMINI_API_KEY"):
        import check_today as CT
        spend = lib.setdefault("spend", {}).setdefault(now.date().isoformat(), {"anthropic_usd": 0.0, "gemini_usd": 0.0, "gemini_searches": 0, "new_claims": 0})
        cap = (lib.get("caps") or {}).get("today_gemini_cap", CT.GEMINI_DAILY_USD)

        def ask(prompt, schema):
            if spend["gemini_usd"] + 0.05 > cap:
                raise RuntimeError("today's Gemini cap is spent")
            return CT.gemini_json(prompt, schema, "low")

        def charge(usage):
            spend["gemini_usd"] = round(spend["gemini_usd"] + CT.UNDERCOUNT * CT.cost_usd(C.GEMINI_MODEL, usage), 4)
    ask2 = None
    if lib is not None and os.environ.get("ANTHROPIC_API_KEY") and ask:
        acap = (lib.get("caps") or {}).get("today_anthropic_cap", 1.10)

        def ask2(prompt):
            if spend["anthropic_usd"] + 0.02 > acap:
                raise RuntimeError("today's Claude cap is spent")
            out, usage = haiku_json(prompt)
            spend["anthropic_usd"] = round(spend["anthropic_usd"] + CT.UNDERCOUNT * CT.cost_usd(HAIKU, usage), 4)
            return out
    cross = live.get("crosstabs", {}) if live.get("crosstabs_v") == CROSS_V else {}
    cross_left = [CROSS_PER_SCAN]
    pipes_left = [2]
    hist = history()
    pages = {}
    for rid, race in RACES.items():
        try:
            pages[rid] = wikitext(race["wiki"])
        except Exception as e:
            print(f"tx_numbers: could not read Wikipedia for {rid}: {e}")
    # A pollster's lean as Wikipedia labels it on any race page, applied on every race page (the labels differ).
    lean = {}
    for rid, (page, rev) in pages.items():
        for p in parse_polls(page, RACES[rid]["candidates"]):
            if p["affiliation"]:
                lean[p["pollster"]] = p["affiliation"] if lean.get(p["pollster"]) in (None, p["affiliation"]) else "both"
    out = {"version": VERSION, "updated_at": now.isoformat(timespec="seconds"), "races": {}, "confirmed": cache,
           "history": hist, "recent_days": RECENT_DAYS}
    since = (now - timedelta(days=RECENT_DAYS)).date().isoformat()
    for rid, race in RACES.items():
        prev = (live.get("races") or {}).get(rid, {})
        if rid not in pages:
            if prev:
                out["races"][rid] = prev
            continue
        page, rev = pages[rid]
        cands = race["candidates"]
        surn = [c["name"].split()[-1] for c in cands]
        all_polls = parse_polls(page, cands)
        for p in all_polls:
            p["affiliation"] = lean.get(p["pollster"], p["affiliation"])
        shown, unconfirmed, seen = [], [], set()
        for p in [p for p in all_polls if p["end"] and p["end"] >= since]:
            key = f"{rid}|{p['url']}|{p['shares'][0]:g}|{p['shares'][1]:g}|{p['pop']}"
            ident = (p["pollster"], p["dates"])
            if key not in cache and p["url"] and ask:
                text, info = read(p["url"], pipes_left)
                if not text:
                    cache[key] = {"ok": False, "why": f"we could not read the release ({info})"[:140], "at": now.isoformat(timespec="seconds")}
                else:
                    pop = {"LV": " among likely voters", "RV": " among registered voters"}.get(p["pop"], "")
                    prompt = (POLL_PROMPT.replace("{office}", race["name"]).replace("{a}", cands[0]["name"]).replace("{b}", cands[1]["name"])
                              .replace("{pop}", pop).replace("{text}", text[:60000]))
                    try:
                        ok, why, ans = agree(text, prompt, p["shares"], ask, charge)
                    except Exception as e:
                        print(f"  {rid} {p['pollster']}: not checked ({e})")
                        ok = None
                    if ok is not None:
                        moe_ok = bool(p["moe"]) and abs((ans.get("moe") or 0) - p["moe"]) < 0.051 and f"{p['moe']:g}" in squash(text)
                        n_ok = bool(p["n"]) and ans.get("n") == p["n"]
                        cache[key] = {"ok": ok, "why": why, "moe_ok": moe_ok, "n_ok": n_ok, "at": now.isoformat(timespec="seconds"), "squash": SQUASH_V}
                        print(f"  {rid} {p['pollster']} {p['pop']} {p['shares']}: {'confirmed' if ok else why}")
            got = cache.get(key)
            if got and got["ok"]:
                if ident in seen:   # one row per poll: its first confirmed version (Wikipedia lists likely voters first)
                    continue
                seen.add(ident)
                moe = p["moe"] if got.get("moe_ok") else None
                shown.append({**p, "moe": moe, "n": p["n"] if got.get("n_ok") else None, "lead_moe": lead_moe(moe, p["shares"])})
            elif ident not in seen and not any(u["pollster"] == p["pollster"] and u["dates"] == p["dates"] for u in unconfirmed):
                unconfirmed.append({"pollster": p["pollster"], "dates": p["dates"], "url": p["url"],
                                    "why": (got or {}).get("why") or ("no link to the release" if not p["url"] else "not checked yet")})
        unconfirmed = [u for u in unconfirmed if (u["pollster"], u["dates"]) not in seen]
        averages = parse_averages(page, cands)
        try:
            cited = cited_polls(rid, all_polls, prev.get("cited", []))
        except Exception as e:
            print(f"  {rid}: cited polls failed ({e})")
            cited = prev.get("cited", [])
        money = prev.get("money")
        if not money or money.get("v") != MONEY_V or (money.get("at") or "")[:10] != now.date().isoformat():  # once a day
            try:
                if any(c.get("fec") for c in cands):
                    money = fec_money(cands)
                else:
                    money = tec_money(cands)
                money["at"], money["v"] = now.isoformat(timespec="seconds"), MONEY_V
            except Exception as e:
                print(f"  {rid}: money not updated ({e})")
                # Written to the file so a failure can be read without the Actions log (never the key itself).
                money = dict(money or {}, error=f"{type(e).__name__}: {e}"[:200], error_at=now.isoformat(timespec="seconds"),
                             fec_key_set=bool(os.environ.get("FEC_API_KEY")))
        # Polls by group: each shown poll's release read once (both models), CROSS_PER_SCAN at most per scan.
        for p in shown:
            ck = f"{rid}|{p['url']}|{p['pop']}"
            if ck in cross or not (ask and ask2) or cross_left[0] <= 0:
                continue
            cross_left[0] -= 1
            text, info = read(p["url"], pipes_left)
            if not text:
                cross[ck] = {"rows": [], "notes": [f"could not read the release ({info})"[:120]], "at": now.isoformat(timespec="seconds")}
                continue
            try:
                rows, notes = crosstabs(text, race, cands, p, ask, charge, ask2)
                cross[ck] = {"rows": rows, "notes": notes[:12], "at": now.isoformat(timespec="seconds")}
                print(f"  {rid} {p['pollster']}: {len(rows)} groups kept, {len(notes)} dropped")
            except Exception as e:
                print(f"  {rid} {p['pollster']}: crosstabs not read ({e})")
        groups = {}
        for p in shown:
            for r in (cross.get(f"{rid}|{p['url']}|{p['pop']}") or {}).get("rows", []):
                groups.setdefault(r["category"], {}).setdefault(r["group"], []).append(
                    {"pollster": p["pollster"], "end": p["end"], "url": p["url"], "shares": r["shares"], "one_side": p.get("one_side")})
        out["races"][rid] = {
            "name": race["name"], "candidates": [{"name": c["name"], "party": c["party"]} for c in cands],
            "wiki": f"https://en.wikipedia.org/wiki/{race['wiki']}", "wiki_rev": rev,
            "polls": shown, "unconfirmed": unconfirmed, "averages": averages, "cited": cited, "money": money,
            "forecast": forecast(averages, cands, hist), "groups": groups,
        }
        print(f"tx_numbers {rid}: {len(shown)} polls shown, {len(unconfirmed)} not confirmed, {len(averages)} averages, {len(cited)} cited")
    out["confirmed"] = {k: v for k, v in cache.items() if v.get("ok") or (v.get("at") or "") >= (now - timedelta(days=2)).isoformat()}
    out["crosstabs"], out["crosstabs_v"], out["groups_live"] = cross, CROSS_V, GROUPS_LIVE
    OUT.write_text(json.dumps(out, indent=1))
    # The investors' time capsule freezes these with the rest of the edition (see check_today.write_capsule).
    key = os.environ.get("CAPSULE_KEY", "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        (ROOT / "data/capsule" / key).mkdir(parents=True, exist_ok=True)
        (ROOT / "data/capsule" / key / "tx-numbers.json").write_text(json.dumps({k: v for k, v in out.items() if k != "confirmed"}))
    if lib is not None and ask:
        lib_path.write_text(json.dumps(lib, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never blocks the scan: the site keeps the last file
        print(f"tx_numbers failed: {e}")
        sys.exit(0)
