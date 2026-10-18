"""Stage 3 on the live site: what the coverage agrees on, and where it differs.

Runs after cluster.py in the hourly scan. For each of Today's top political stories:
  1. Gemini reads the outlets' headlines and summaries and writes a brief: facts the coverage agrees
     on, points where it differs (each side's position, with the outlets that take it), and any
     values question. Every item must cite the numbered articles it comes from, or it is dropped.
  2. Agreed facts are confirmed against the cited outlets' own text: a fact stays only if at least
     two different outlets state it. These are consensus reports, labeled as such, not verdicts.
  3. A difference that turns on a fact is checked against primary sources (Gemini checks, code
     verifies every quote, Holds up must follow from the verified quotes alone, and Doesn't hold up
     needs Claude Opus to agree). Checked claims live in the library and are reused.

The library (data/library.json) is read back from the live site at the start of each scan, so work
is paid for once. Spend is capped per day in code. A failure here never blocks the scan: the site
keeps last hour's results.
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_URL = "https://hestonmiles.com/factual/data/library.json"
TOP_STORIES = 5
MAX_NEW_PER_SCAN = 4
MAX_NEW_PER_DAY = 25
ANTHROPIC_DAILY_USD = 1.00
GEMINI_DAILY_USD = 1.50
GEMINI_DAILY_SEARCHES = 150      # Google gives 5,000 free a month across Gemini 3 models
UNDERCOUNT = 1.7                 # our cost log ran this far under the real bill (2026-10-17)
RECHECK_AFTER_DAYS = 7
OPUS_TYPICAL_USD = 0.51          # measured mean per Opus second opinion, 2026-10-17 eval
SAME_CLAIM = 0.93                # embedding similarity at which two wordings are one claim
MIN_OUTLETS_AGREED = 2           # an agreed fact needs at least this many outlets to state it
BRIEF_VERSION = "2"              # bump when the brief instructions change, so cached briefs regenerate
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.010), "claude-haiku-5-5": (0.10, 0.50, 0), "claude-sonnet-5-5": (2.00, 10.00, 0),
          "gemini-3.8-flash": (0.75, 3.75, 0.0)}   # Gemini searches are tracked by count, not dollars

_item = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_ints = {"type": "array", "items": {"type": "integer"}}
BRIEF_SCHEMA = _item({
    "agreed": {"type": "array", "items": _item({"fact": {"type": "string"}, "articles": _ints}, ["fact", "articles"])},
    "differences": {"type": "array", "items": _item({
        "point": {"type": "string", "description": "What the coverage differs on, in neutral words."},
        "positions": {"type": "array", "items": _item({"says": {"type": "string"}, "articles": _ints}, ["says", "articles"])},
        "checkable_claim": {"type": "string", "description": "If the difference turns on a checkable fact, that fact as one statement. Else empty."},
    }, ["point", "positions", "checkable_claim"])},
    "values_questions": {"type": "array", "items": {"type": "string"}},
}, ["agreed", "differences", "values_questions"])

BRIEF_PROMPT = """You are writing the neutral brief for one news story, from the numbered coverage
below (each line: outlet, its audience lean, headline, and summary when there is one).

Write:
- agreed: up to 4 facts that several outlets report. Plain, neutral sentences. Prefer facts reported
  by outlets of different leans. List every article number that states the fact.
- differences: up to 2 points where the coverage differs: in what happened, in a disputed fact, or in
  what it emphasizes. Name the point neutrally, then give each position in neutral words with the
  article numbers that take it. If the difference turns on a checkable fact, also write that fact as
  one statement in checkable_claim; otherwise leave it empty.
- values_questions: up to 2 questions about what should happen or what matters more, worded neutrally.

Rules:
- Attribute every claim to whoever made it. If a person, party, agency or lawyer says something, write
  who says it ("The Justice Department says about 200,000...", "Omar's attorneys say the search was
  unlawful"). Never state a claim someone made as a fact, and never present what an outlet reports
  someone saying as the outlet's own view.
- Agreed facts are things that happened or were said on the record, stated with attribution where
  someone made a claim. A disputed or one-sided assertion is a difference, not an agreed fact.
- Use only what is in the coverage below. Add nothing from your own knowledge. Do not judge which side
  is right. Do not use loaded words. Use only article numbers from the list.

Coverage:
{coverage}"""

CONFIRM_SCHEMA = _item({"facts": {"type": "array", "items": _item({"fact": {"type": "integer"}, "stated_by": _ints}, ["fact", "stated_by"])}}, ["facts"])
CONFIRM_PROMPT = """For each numbered fact, list which numbered articles state it, using ONLY the text of
those articles below. An article states a fact only if its headline or summary says it; implying it or
being about the same topic is not enough.

Facts:
{facts}

Articles:
{articles}"""

SUPPORT_SCHEMA = _item({"established": {"type": "string", "enum": ["all", "part", "none"]}, "missing": {"type": "string"}},
                       ["established", "missing"])
SUPPORT_PROMPT = """Below is a claim and some quotes, each copied word for word from its source page.
Using ONLY these quotes, not anything you know, decide whether they establish every part of the claim
exactly as it is stated. Pay attention to strong words: a quote saying someone left or was asked to
reconsider does not establish that they were fired; a total does not establish a record.

Answer "all" only if every part of the claim, as worded, is stated in the quotes. Answer "part" if some
of it is and some is not, and say what is missing. Answer "none" if the quotes do not support it.

Claim: {claim}

Quotes:
{quotes}"""


def cost_usd(model, usage, searches=0):
    p = next((v for k, v in PRICES.items() if model and model.startswith(k)), (4.0, 20.0, 0.01))
    u = usage or {}
    tin = u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0) + 0.1 * u.get("cache_read_input_tokens", 0)
    return (tin * p[0] + u.get("output_tokens", 0) * p[1]) / 1e6 + searches * p[2]


def load_library():
    """Last scan's library from the live site. Only a 404 means 'start empty'; any other failure
    means skip this scan, so a network blip can never trigger a full, paid re-check."""
    try:
        with urllib.request.urlopen(urllib.request.Request(LIBRARY_URL, headers={"User-Agent": C.UA}), timeout=20, context=C.SSL_CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"claims": {}, "spend": {}}
        raise


def key_of(text):
    return hashlib.sha1(re.sub(r"[^a-z0-9%$.]+", " ", text.lower()).strip().encode()).hexdigest()[:12]


def gemini_json(prompt, schema):
    key = os.environ["GEMINI_API_KEY"]
    body = json.dumps({"model": C.GEMINI_MODEL, "input": prompt,
                       "response_format": {"type": "text", "mime_type": "application/json", "schema": schema}}).encode()
    req = urllib.request.Request(C.GEMINI_URL, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120, context=C.SSL_CTX) as r:
        raw = json.loads(r.read())
    texts = []
    C._walk(raw.get("steps", raw), lambda n: texts.append(n["text"]) if isinstance(n, dict) and n.get("type") == "text" and isinstance(n.get("text"), str) else None)
    u = raw.get("usage") or {}
    usage = {"input_tokens": u.get("input_tokens") or u.get("total_input_tokens") or 0,
             "output_tokens": (u.get("output_tokens") or u.get("total_output_tokens") or 0) + (u.get("thought_tokens") or u.get("total_thought_tokens") or 0)}
    return json.loads(raw.get("output_text") or texts[-1]), usage


def sourced_finding(r):
    """Drop any sentence whose numbers are not in a verified quote."""
    bad = set(r.get("numbers_unsourced") or [])
    if not bad:
        return r["output"].get("finding", ""), 0
    sentences = re.split(r"(?<=[.!?])\s+", r["output"].get("finding", ""))
    keep = [s for s in sentences if not (set(C.numbers_in(s)) & bad)]
    return " ".join(keep), len(sentences) - len(keep)


def public_record(claim, first, second, verdict, note, story_ids, said_by):
    """What readers see about one checked claim. Only verified evidence is published."""
    finding, dropped = sourced_finding(first)
    fields = ("url", "publisher", "published", "quote", "role")
    ev = [{k: e[k] for k in fields} for e in first["evidence_checked"] if e["verified"]]
    if second and second.get("evidence_checked"):
        seen = {x["url"] for x in ev}
        ev += [{k: e[k] for k in fields} for e in second["evidence_checked"] if e["verified"] and e["url"] not in seen]
    out = first["output"]
    return {
        "claim": claim, "verdict": verdict, "steelman": out.get("steelman", ""), "finding": finding,
        "sentences_dropped": dropped, "reasoning_flags": out.get("reasoning_flags", []), "newest_data": out.get("newest_data", ""),
        "evidence": ev, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked_by": first["model"], "second_opinion": (second or {}).get("model"), "second_verdict": (second or {}).get("verdict"),
        "note": note, "stories": story_ids, "said_by": said_by,
        "model_verdict": first["verdict_raw"], "pending_second": note == "second opinion waiting for budget",
    }


def main():
    C.load_env()
    if not (os.environ.get("GEMINI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        print("check_today: API keys not set; skipping")
        return 0
    stories_path = ROOT / "data/stories.json"
    data = json.loads(stories_path.read_text())
    summaries = {}
    if (ROOT / "data/articles.json").exists():
        summaries = {a["url"]: a.get("summary", "") for a in json.loads((ROOT / "data/articles.json").read_text())["articles"]}
    side_of = {f["source"]: f.get("side", "unplaced") for f in data.get("feeds", [])}
    try:
        lib = load_library()
    except Exception as e:
        print(f"check_today: could not read the library ({e}); skipping this scan")
        return 0

    today = datetime.now(timezone.utc).date().isoformat()
    spend = lib.setdefault("spend", {}).setdefault(today, {"anthropic_usd": 0.0, "gemini_usd": 0.0, "gemini_searches": 0, "new_claims": 0})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    lib["spend"] = {d: v for d, v in lib["spend"].items() if d >= cutoff}
    claims = lib.setdefault("claims", {})
    briefs = lib.setdefault("briefs", {})
    lib.pop("extractions", None)  # replaced by briefs

    def gemini_ok():
        return spend["gemini_usd"] < GEMINI_DAILY_USD

    def charge_gemini(usage, searches=0):
        spend["gemini_usd"] = round(spend["gemini_usd"] + UNDERCOUNT * cost_usd(C.GEMINI_MODEL, usage), 4)
        spend["gemini_searches"] += searches

    def charge_anthropic(model, usage, searches=0):
        spend["anthropic_usd"] = round(spend["anthropic_usd"] + UNDERCOUNT * cost_usd(model, usage, searches), 4)

    def charge_pipe():
        for u in C.PIPE_USAGE:
            charge_anthropic(u["model"], u)
        C.PIPE_USAGE.clear()

    from fastembed import TextEmbedding
    embed = TextEmbedding("BAAI/bge-small-en-v1.5")
    vec = lambda texts: (lambda a: a / np.linalg.norm(a, axis=1, keepdims=True))(np.array(list(embed.embed(texts)), dtype=np.float32))
    lib_keys = list(claims)
    lib_vecs = vec([claims[k]["claim"] for k in lib_keys]) if lib_keys else None

    def find_existing(text):
        k = key_of(text)
        if k in claims:
            return k
        if lib_vecs is not None:
            s = lib_vecs @ vec([text])[0]
            i = int(np.argmax(s))
            if s[i] >= SAME_CLAIM:
                return lib_keys[i]
        return None

    def support_ok(record):
        """Holds up must follow from the verified quotes alone."""
        if record["verdict"] != C.HU or "support" in record or spend["gemini_usd"] >= GEMINI_DAILY_USD + 0.10:
            return
        quotes = "\n".join(f"- \"{e['quote']}\" ({e['publisher']})" for e in record["evidence"] if e.get("role") in ("supports", "context"))
        if quotes:
            try:
                out, usage = gemini_json(SUPPORT_PROMPT.replace("{claim}", record["claim"]).replace("{quotes}", quotes), SUPPORT_SCHEMA)
            except Exception as e:
                print(f"  support check failed: {e}")
                return
            charge_gemini(usage)
            ok, missing = out["established"] == "all", out.get("missing", "")
        else:
            ok, missing = False, "no verified quote supports it"
        record["support"] = "all" if ok else "partial"
        if not ok:
            record["verdict"] = C.UN
            record["note"] = f"the sources confirm part of this claim, not all of it as stated: {missing}".rstrip(": ")

    for rec in claims.values():  # claims checked before the support check existed
        support_ok(rec)

    state = {"new_this_scan": 0}

    def check_claim(text, story_sid, said_by):
        """Library first; a new claim is checked under the caps. Returns the library key or None."""
        existing = find_existing(text)
        rec = claims.get(existing) if existing else None
        fresh = rec and datetime.fromisoformat(rec["checked_at"]) > datetime.now(timezone.utc) - timedelta(days=RECHECK_AFTER_DAYS)
        if rec and fresh and not rec.get("pending_second"):
            rec["stories"] = sorted(set(rec.get("stories", [])) | {story_sid})
            return existing
        if state["new_this_scan"] >= MAX_NEW_PER_SCAN or spend["new_claims"] >= MAX_NEW_PER_DAY \
                or not gemini_ok() or spend["gemini_searches"] >= GEMINI_DAILY_SEARCHES:
            return existing
        try:
            first = C.check(text, "gemini")
        except Exception as e:
            print(f"  check failed: {text[:60]}: {e}")
            return existing
        charge_pipe()
        charge_gemini(first["usage"], first.get("web_searches", 0))
        spend["new_claims"] += 1
        state["new_this_scan"] += 1
        first.pop("trace", None)
        second, note, verdict = None, None, first["verdict"]
        if verdict == C.DHU:
            if ANTHROPIC_DAILY_USD - spend["anthropic_usd"] >= OPUS_TYPICAL_USD:
                try:
                    second = C.check(text, "claude")
                    second.pop("trace", None)
                    charge_anthropic(second["model"], second["usage"], second.get("web_searches", 0))
                    charge_pipe()
                    verdict, note = C.combine(first, second)
                except Exception as e:
                    verdict, note = C.UN, f"second opinion failed: {str(e)[:120]}"
            else:
                verdict, note = C.UN, "second opinion waiting for budget"
        k = existing or key_of(text)
        record = public_record(text, first, second, verdict, note, sorted(set((rec or {}).get("stories", [])) | {story_sid}), said_by)
        support_ok(record)
        claims[k] = record
        print(f"  {record['verdict']:<16} {text[:80]}")
        return k

    top = [s for s in data["stories"] if s.get("related_to") is None and s.get("topic") == "politics"][:TOP_STORIES]
    for story in top:
        arts = story["articles"][:14]
        lines = []
        for i, a in enumerate(arts):
            summ = (summaries.get(a["url"]) or "")[:300]
            lines.append(f"{i + 1}. {a['source']} ({side_of.get(a['source'], 'unplaced')}): {a['title']}" + (f" | {summ}" if summ else ""))
        coverage = "\n".join(lines)
        digest = hashlib.sha1((BRIEF_VERSION + coverage).encode()).hexdigest()[:16]
        cached = briefs.get(story["sid"])
        if cached and cached["digest"] == digest:
            brief = cached["brief"]
        else:
            if not gemini_ok():
                brief = cached["brief"] if cached else None
            else:
                try:
                    raw, usage = gemini_json(BRIEF_PROMPT.replace("{coverage}", coverage), BRIEF_SCHEMA)
                    charge_gemini(usage)
                    brief = build_brief(raw, arts, lines, side_of, gemini_json, charge_gemini)
                    briefs[story["sid"]] = {"digest": digest, "brief": brief, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                except Exception as e:
                    print(f"  brief failed for {story['sid']}: {e}")
                    brief = cached["brief"] if cached else None
        if not brief:
            continue
        # Factual differences are checked against primary sources (cached in the library).
        for d in brief["differences"]:
            if d.get("checkable_claim") and not d.get("check"):
                said_by = sorted({o for p in d["positions"] for o in p["outlets"]})
                d["check"] = check_claim(d["checkable_claim"], story["sid"], said_by)
        story["brief"] = brief
        story["checks"] = [d["check"] for d in brief["differences"] if d.get("check")]
        print(f"  {story['sid']}: {len(brief['agreed'])} agreed, {len(brief['differences'])} differences")

    live = {s["sid"] for s in data["stories"]}
    lib["briefs"] = {k: v for k, v in briefs.items() if k in live}
    lib["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lib["caps"] = {"anthropic_daily_usd": ANTHROPIC_DAILY_USD, "gemini_daily_usd": GEMINI_DAILY_USD,
                   "gemini_daily_searches": GEMINI_DAILY_SEARCHES, "new_claims_per_day": MAX_NEW_PER_DAY}
    (ROOT / "data/library.json").write_text(json.dumps(lib, indent=1))
    stories_path.write_text(json.dumps(data, indent=1))
    print(f"check_today: {state['new_this_scan']} new claims · today anthropic ${spend['anthropic_usd']:.2f}/{ANTHROPIC_DAILY_USD:.2f} · "
          f"gemini ${spend['gemini_usd']:.2f}/{GEMINI_DAILY_USD:.2f}, searches {spend['gemini_searches']}/{GEMINI_DAILY_SEARCHES}")
    return 0


def build_brief(raw, arts, lines, side_of, ask, charge):
    """Keep only what the coverage supports: valid article numbers, and agreed facts that at least two
    different outlets state in their own headline or summary."""
    n = len(arts)
    valid = lambda idx: sorted({i for i in idx if isinstance(i, int) and 1 <= i <= n})
    outlets = lambda idx: sorted({arts[i - 1]["source"] for i in idx})

    agreed = [(a["fact"].strip(), valid(a["articles"])) for a in raw.get("agreed", [])[:4] if a.get("fact", "").strip()]
    agreed = [(f, idx) for f, idx in agreed if len(outlets(idx)) >= MIN_OUTLETS_AGREED]
    confirmed = []
    if agreed:
        facts = "\n".join(f"{j + 1}. {f}" for j, (f, _) in enumerate(agreed))
        cited = sorted({i for _, idx in agreed for i in idx})
        out, usage = ask(CONFIRM_PROMPT.replace("{facts}", facts).replace("{articles}", "\n".join(lines[i - 1] for i in cited)), CONFIRM_SCHEMA)
        charge(usage)
        stated = {f["fact"]: valid(f["stated_by"]) for f in out.get("facts", [])}
        for j, (fact, idx) in enumerate(agreed):
            by = [i for i in stated.get(j + 1, []) if i in idx]  # an outlet counts only if it was cited and states it
            if len(outlets(by)) >= MIN_OUTLETS_AGREED:
                confirmed.append({"fact": fact, "reported_by": outlets(by),
                                  "sides": sorted({side_of.get(o, "unplaced") for o in outlets(by)})})

    differences = []
    for d in raw.get("differences", [])[:2]:
        positions = [{"says": p["says"].strip(), "outlets": outlets(valid(p["articles"]))} for p in d.get("positions", [])[:3]]
        positions = [p for p in positions if p["says"] and p["outlets"]]
        if d.get("point", "").strip() and positions:
            differences.append({"point": d["point"].strip(), "positions": positions,
                                "checkable_claim": (d.get("checkable_claim") or "").strip(), "check": None})
    values = [q.strip() for q in raw.get("values_questions", [])[:2] if q.strip()]
    return {"agreed": confirmed, "differences": differences, "values_questions": values}


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never block the scan; the site keeps last hour's results
        print(f"check_today failed: {type(e).__name__}: {e}")
        sys.exit(0)
