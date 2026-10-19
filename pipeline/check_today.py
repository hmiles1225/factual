"""Stage 3 on the live site: what the coverage agrees on, and where it differs.

Runs after cluster.py in the hourly scan. For each topic's top stories covered by both left- and
right-leaning outlets (politics 5, environment, science and health 3 each):
  1. Gemini reads the outlets' headlines, summaries and the opening of each article and writes a brief:
     common ground (facts outlets on both sides state), other agreed facts, points where the coverage
     differs (each side's position, with the outlets that take it), and any values question. Every item
     must cite the numbered articles it comes from, or it is dropped.
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check as C  # noqa: E402
from images import image_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_URL = "https://hestonmiles.com/factual/data/library.json"
ARCHIVE_URL = "https://hestonmiles.com/factual/data/archive/"
TOPIC_QUOTAS = {"politics": 5, "environment": 3, "science": 3, "health": 3}   # Heston's call, 2026-10-18
EXTRA_CANDIDATES = 3             # stories tried past the quota, in rank order, when one won't summarize
ARTICLES_PER_BRIEF = 14          # picked round-robin by side, so one side can't fill the brief
EXCERPT_CHARS = 900              # opening of each article read for the brief; never published
REBRIEF_HOURS = 6                # a story is re-summarized when a new side joins, else at most this often
MAX_NEW_PER_SCAN = 5
MAX_NEW_PER_DAY = 30
# "Decent" fact-check coverage for the proof of concept (Heston's call, 2026-10-19): about 16 to 20 checks a
# day, nearly every politics account. At most $3.10/day, ~$93/month.
ANTHROPIC_DAILY_USD = 1.10       # two Opus second opinions (~$0.51 each) a day
GEMINI_DAILY_USD = 2.00          # summaries, checks, and searches past Google's free allowance
# One-off raises, approved by Heston for a specific date only. Expires by itself.
GEMINI_EXTRA_USD = {"2026-10-19": 0.50}   # one-off, approved by Heston: today's total stays at the $2.50 he approved
# Bump when the outlet list changes: a story whose outlets changed since its summary is re-summarized once.
ROSTER_VERSION = "2026-10-19"
GEMINI_FREE_SEARCHES = 150      # Google gives 5,000 free a month across Gemini 3 models; ~150 a day
SEARCH_USD = 0.014               # then $14 per 1,000 searches (ai.google.dev pricing, 2026-10-18), charged to the Gemini cap
CHECK_RESERVE_USD = 0.35         # most one fact-check has cost (tokens plus paid searches), with margin
UNDERCOUNT = 1.7                 # our cost log ran this far under the real bill (2026-10-17)
RECHECK_AFTER_DAYS = 7
DECIDED = ("Holds up", "Missing context", "Doesn't hold up")
# One-off fresh checks, by library key, when a verdict is known to rest on thin evidence. Runs once each.
FORCE_RECHECK = {"ff5e92501774": "court order cited never names the course; look for a filing that does (2026-10-19)"}
OPUS_TYPICAL_USD = 0.51          # measured mean per Opus second opinion, 2026-10-17 eval
CARRY_OVER = 0.80               # same story, same side: an earlier decided claim this close is the same claim, reworded
SAME_CLAIM = 0.93                # embedding similarity at which two wordings are one claim
MIN_OUTLETS_AGREED = 2           # an agreed fact needs at least this many outlets to state it
BRIEF_VERSION = "8"              # bump when the brief instructions change, so cached briefs regenerate
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.010), "claude-haiku-5-5": (0.10, 0.50, 0), "claude-sonnet-5-5": (2.00, 10.00, 0),
          "gemini-3.8-flash": (0.75, 3.75, 0.0)}   # Gemini searches are tracked by count, not dollars

_item = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_ints = {"type": "array", "items": {"type": "integer"}}
BRIEF_SCHEMA = _item({
    "common_ground": {"type": "array", "items": _item({"fact": {"type": "string"}, "articles": _ints}, ["fact", "articles"])},
    "agreed": {"type": "array", "items": _item({"fact": {"type": "string"}, "articles": _ints}, ["fact", "articles"])},
    "differences": {"type": "array", "items": _item({
        "point": {"type": "string", "description": "What the coverage differs on, in neutral words."},
        "positions": {"type": "array", "items": _item({
            "says": {"type": "string"}, "articles": _ints,
            "crux": {"type": "string", "description": "Copied word for word from says: the short phrase that is what this side says differently."},
            "checkable_claim": {"type": "string", "description": "A checkable factual claim this side makes, as one statement, attributed. Else empty."},
        }, ["says", "crux", "articles", "checkable_claim"])},
        "checkable_claim": {"type": "string", "description": "Deprecated; leave empty."},
    }, ["point", "positions", "checkable_claim"])},
    "values_questions": {"type": "array", "items": {"type": "string"}},
    "main_subject": _item({"name": {"type": "string", "description": "Full name as commonly written, e.g. 'Ilhan Omar'."},
                           "kind": {"type": "string", "enum": ["person", "organization", "place", "none"]}}, ["name", "kind"]),
}, ["common_ground", "agreed", "differences", "values_questions", "main_subject"])

BRIEF_PROMPT = """You are writing the neutral brief for one news story, from the numbered coverage
below (each line: outlet, its audience lean, headline, its summary when there is one, and the opening
of the article when we could read it).

Write:
- common_ground: 3 to 6 sentences that, read in order, report the story the way a wire service would:
  what happened, who is involved, when and where, what each named party says, and the key numbers.
  Use only facts that at least one left-leaning AND at least one right-leaning outlet both state in
  their own text (headline, summary or opening). Write each sentence at the level of detail both sides
  give, leaving out any number, quote or framing only one side uses. Even when the sides disagree on
  why or how, they usually agree on what happened: that is common ground. Each sentence is one fact
  with every article number that states it. Fewer sentences only if the coverage truly shares less.
- agreed: up to 3 more facts, not already in common_ground, that several outlets report. Plain, neutral sentences. Prefer facts reported
  by outlets of different leans. When left- and right-leaning outlets both report the same core event,
  write that fact at the level of detail they share: leave out a number, quote or detail only some of
  them give, or make that detail its own fact. List every article number that states the fact.
- differences: up to 3 points where the coverage differs, especially where left-leaning and
  right-leaning outlets tell it differently (the lean of each outlet is shown in the coverage list): in
  what happened, in a disputed fact, in context left out, or in emphasis. Name the point neutrally, then
  give each position in neutral words with the article numbers that take it, and copy into crux the
  few words of that position that are the actual difference (they will be shown in bold). For each position,
  left and right alike, if it states any fact about the world (what happened, what someone did or said, a
  number), write that claim as one statement in its
  checkable_claim, attributed to whoever made it but never to the outlet (write "A federal judge
  approved the warrant", not "The Daily Wire reports a federal judge approved the warrant"), so each
  side's facts can be checked the same way; otherwise leave it empty.
- values_questions: up to 2 questions about what should happen or what matters more, worded neutrally.
- main_subject: the one person (or organization, or place) the story is mainly about, by full name.
  Use kind "none" if there is no single clear subject.

Rules:
- Attribute every claim to whoever made it. If a person, party, agency or lawyer says something, write
  who says it ("The Justice Department says about 200,000...", "Omar's attorneys say the search was
  unlawful"). Never state a claim someone made as a fact, and never present what an outlet reports
  someone saying as the outlet's own view.
- Agreed facts are what happened: the event itself (who did what, when, where) is almost always
  agreed when several outlets report it, and should be listed. Attribute only claims someone makes
  ("Her attorneys say the search was unlawful"). A disputed or one-sided assertion is a difference.
  Most stories have at least two agreed facts.
- Use only what is in the coverage below. Add nothing from your own knowledge. Do not judge which side
  is right. Do not use loaded words. Use only article numbers from the list.

Claims already checked for this story. If a side's position still rests on one of these, copy it word
for word as that position's checkable_claim, so its check carries over:
{prior}

Coverage:
{coverage}"""

CONFIRM_SCHEMA = _item({"facts": {"type": "array", "items": _item({"fact": {"type": "integer"}, "stated_by": _ints}, ["fact", "stated_by"])}}, ["facts"])
CONFIRM_PROMPT = """For each numbered fact, list which numbered articles state it, using ONLY the text of
those articles below. An article states a fact only if its headline, summary or opening says it; implying
it or being about the same topic is not enough.

Facts:
{facts}

Articles:
{articles}"""

SUPPORT_SCHEMA = _item({"established": {"type": "string", "enum": ["all", "part", "none"]},
                        "missing": {"type": "string", "description": "Only the part of the claim the evidence does not establish, as a short phrase starting with 'that' (e.g. 'that other work was paused'). Empty if all is established."}},
                       ["established", "missing"])
LOADED_VERSION = "1"
LOADED_SCHEMA = _item({"terms": {"type": "array", "items": _item({
    "term": {"type": "string", "description": "Copied exactly as the outlet wrote it."},
    "articles": _ints,
    "why": {"type": "string", "description": "Why it is loaded, in at most 12 words."},
    "neutral": {"type": "string", "description": "A plainer, neutral way to say it."}},
    ["term", "articles", "why", "neutral"])}}, ["terms"])
LOADED_PROMPT = """Below is the coverage of one news story: each numbered line is an outlet, its audience lean, its
headline, its summary, and the opening of the article when we could read it.

List words or short phrases the OUTLETS THEMSELVES use that are inflammatory or clearly slanted: emotionally
charged labels, insults, scare words, loaded characterizations, partisan labels (for example "regime",
"radical", "slammed", "meltdown", "far-right", "leftist", "illegal aliens", "extremist"). Rules:
- Only the outlet's own words. Skip anything inside quotation marks or attributed to a speaker: quoting
  someone is not the outlet's language.
- Copy each term exactly as written, at most six words.
- Hold left-leaning and right-leaning outlets to the same standard. Up to 4 terms per side; none is fine.
- Ordinary, accurate words are not loaded ("arrested", "said", "Republican").
For each term give every article number that uses it, why it is loaded, and a neutral alternative.

Coverage:
{coverage}"""

CLAIM_SCHEMA = _item({"claim": {"type": "string", "description": "One checkable factual claim, or empty."}}, ["claim"])
CLAIM_PROMPT = """One side of a news story's coverage is summarized below. Write the single most important factual
claim this account makes, as one plain statement that can be checked against primary sources (court
records, official statements, government data, documents). Attribute it to whoever made it ("Police said
Oliver was charged with ...", "Trump said ..."), but never to a news outlet. Use only what the account
says; add nothing. If the account makes no factual claim, only emphasis, framing or opinion, return an
empty claim.

The point the coverage differs on: {point}
This side's account: {says}"""

SUPPORT_VERSION = "4"   # 2: quotes judged in their page passage; 3: plus the page's sentences naming the claim's terms, editor's standard
SUPPORT_PROMPT = """Below is a claim and the evidence for it. Each item is a quote copied word for word from its
source page, shown with the page's address and the passage around the quote on that page, which our
code read itself, and other sentences from the same page that mention names or numbers in the claim.
Using ONLY this evidence, not anything you know, decide whether it establishes every part of the claim.
The address, passage and other sentences can establish what a quote is about (which court, case, place,
person or date). Judge as a careful editor would: ordinary paraphrase and plain implication count (2,700
events are thousands of events; events that took place were planned; the same place, person or body under
a slightly different name is the same). Words that change the meaning do
not: a quote saying someone left or was asked to reconsider does not establish that they were fired; a
total does not establish a record; an endorsement does not establish when it was withheld.

Answer "all" only if every part of the claim, as worded, is established. Answer "part" if some of it is
and some is not, and in "missing" name only the part that is not established, briefly. Answer "none" if the evidence does not support it.

Claim: {claim}

Evidence:
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


THOUGHTS = {"tokens": 0, "calls": 0}   # thinking tokens this scan, logged so effort can be tuned on data


def gemini_json(prompt, schema, thinking=None):
    """thinking: None keeps the model default (medium on gemini-3.8-flash); "low" for pure matching tasks."""
    key = os.environ["GEMINI_API_KEY"]
    req_body = {"model": C.GEMINI_MODEL, "input": prompt,
                "response_format": {"type": "text", "mime_type": "application/json", "schema": schema}}
    if thinking:
        req_body["generation_config"] = {"thinking_level": thinking}
    body = json.dumps(req_body).encode()
    req = urllib.request.Request(C.GEMINI_URL, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120, context=C.SSL_CTX) as r:
        raw = json.loads(r.read())
    texts = []
    C._walk(raw.get("steps", raw), lambda n: texts.append(n["text"]) if isinstance(n, dict) and n.get("type") == "text" and isinstance(n.get("text"), str) else None)
    u = raw.get("usage") or {}
    THOUGHTS["tokens"] += u.get("thought_tokens") or u.get("total_thought_tokens") or 0
    THOUGHTS["calls"] += 1
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
        "evidence": ev, "figures": first.get("figures", []), "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
    images = lib.setdefault("images", {})
    lib.pop("extractions", None)  # replaced by briefs

    gemini_cap = GEMINI_DAILY_USD + GEMINI_EXTRA_USD.get(today, 0.0)

    def gemini_ok():
        return spend["gemini_usd"] < gemini_cap

    def charge_gemini(usage, searches=0):
        paid = max(0, spend["gemini_searches"] + searches - GEMINI_FREE_SEARCHES) - max(0, spend["gemini_searches"] - GEMINI_FREE_SEARCHES)
        spend["gemini_usd"] = round(spend["gemini_usd"] + UNDERCOUNT * cost_usd(C.GEMINI_MODEL, usage) + paid * SEARCH_USD, 4)
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
        """Holds up must follow from the verified quotes, read in their passage on the source page."""
        # Version 1 judged quotes alone and cut true claims whose quotes didn't repeat the names (a court
        # order's excerpt doesn't name the judge). Re-judge those, starting again from the checker's verdict.
        if record.get("support") == "partial" and record.get("support_v") != SUPPORT_VERSION and record.get("model_verdict") == C.HU \
                and not record.get("second_opinion"):
            record["verdict"] = C.HU
            record.pop("support", None)
            if (record.get("note") or "").startswith("the sources confirm part"):
                record["note"] = None
        if record["verdict"] != C.HU or "support" in record or spend["gemini_usd"] >= gemini_cap + 0.10:
            return
        items = []
        for e in record["evidence"]:
            if e.get("role") not in ("supports", "context"):
                continue
            ctx = passage(e["url"], e["quote"])
            more = mentions(e["url"], record["claim"], ctx or e["quote"])
            items.append(f"- Quote: \"{e['quote']}\"\n  Source: {e['publisher']}, {e['url']}"
                         + (f"\n  Passage on the page: \"{ctx}\"" if ctx else "")
                         + "".join(f"\n  Elsewhere on the page: \"{m}\"" for m in more))
        charge_pipe()
        quotes = "\n".join(items)
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
        record["support_v"] = SUPPORT_VERSION
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
        forced = existing in FORCE_RECHECK and not (rec or {}).get("rechecked")
        if rec and fresh and not rec.get("pending_second") and not forced:
            rec["stories"] = sorted(set(rec.get("stories", [])) | {story_sid})
            return existing
        # Searches past Google's free allowance are paid, and charged to the Gemini cap (charge_gemini).
        # Start a check only with room for a worst-case one: the cap is checked before a check, but its
        # paid searches are charged after, and one overran the cap by $0.45 on 2026-10-19.
        if state["new_this_scan"] >= MAX_NEW_PER_SCAN or spend["new_claims"] >= MAX_NEW_PER_DAY \
                or spend["gemini_usd"] + CHECK_RESERVE_USD > gemini_cap:
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
        if forced:
            record["rechecked"] = FORCE_RECHECK[existing]
        support_ok(record)
        claims[k] = record
        print(f"  {record['verdict']:<16} {text[:80]}")
        return k

    # One-off fresh checks run on their own: a claim already attached to a story is never asked for again.
    for k, why in FORCE_RECHECK.items():
        rec = claims.get(k)
        if rec and not rec.get("rechecked"):
            print(f"  recheck {k}: {why}")
            check_claim(rec["claim"], (rec.get("stories") or ["recheck"])[0], rec.get("said_by", []))

    def process(story):
        """Summarize one story (cached unless stale), check its claims, find its image. True if summarized."""
        arts = pick_articles(story["articles"], side_of, ARTICLES_PER_BRIEF)
        outlets_now = sorted({a["source"] for a in story["articles"]})
        sides_now = sorted({side_of.get(o, "unplaced") for o in outlets_now})
        cached = briefs.get(story["sid"])
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["at"])).total_seconds() / 3600 if cached else 0
        # Re-summarize on a new brief version, or when the outlets changed and either a new side joined or
        # REBRIEF_HOURS have passed. A new article from an outlet already in the story never triggers it.
        stale = not cached or cached.get("version") != BRIEF_VERSION or (
            cached.get("outlets") != outlets_now and (cached.get("sides") != sides_now or age_h >= REBRIEF_HOURS
                                                      or cached.get("roster") != ROSTER_VERSION))
        brief = cached["brief"] if cached else None
        if stale and gemini_ok():
            lines, excerpts = coverage_lines(arts, side_of, summaries)
            try:
                prior = [c["claim"] for c in claims.values() if story["sid"] in c.get("stories", []) and c.get("verdict") in DECIDED]
                raw, usage = gemini_json(BRIEF_PROMPT.replace("{prior}", "\n".join(f"- {t}" for t in prior[:12]) or "(none)")
                                         .replace("{coverage}", "\n".join(lines)), BRIEF_SCHEMA)
                charge_gemini(usage)
                brief = build_brief(raw, arts, lines, side_of, gemini_json, charge_gemini)
                briefs[story["sid"]] = {"version": BRIEF_VERSION, "roster": ROSTER_VERSION, "outlets": outlets_now, "sides": sides_now, "brief": brief,
                                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                        "openings_read": sum(1 for x in excerpts if x)}
            except Exception as e:
                print(f"  brief failed for {story['sid']}: {e}")
        if not brief:
            return False
        # Loaded language: once per summary, a separate small pass over the same coverage, verified in code.
        if brief.get("loaded_v") != LOADED_VERSION and gemini_ok():
            try:
                llines, _ = coverage_lines(arts, side_of, summaries)
                out, usage = gemini_json(LOADED_PROMPT.replace("{coverage}", "\n".join(llines)), LOADED_SCHEMA)
                charge_gemini(usage)
                brief["loaded"] = verify_loaded(out, arts, llines, side_of)
                brief["loaded_v"] = LOADED_VERSION
            except Exception as e:
                print(f"  loaded-language pass failed: {e}")
        # Every side's account gets the same chance of a check: if the brief left an account without a
        # claim, ask for the one factual claim it makes (or confirm it makes none). Once per account.
        for d in brief["differences"]:
            for pos in d["positions"]:
                if not pos.get("checkable_claim") and not pos.get("claim_tried") and gemini_ok():
                    try:
                        out, usage = gemini_json(CLAIM_PROMPT.replace("{point}", d["point"]).replace("{says}", pos["says"]), CLAIM_SCHEMA, "low")
                        charge_gemini(usage)
                        pos["checkable_claim"] = (out.get("claim") or "").strip()
                        pos["no_claim"] = not pos["checkable_claim"]
                        pos["claim_tried"] = True
                    except Exception as e:
                        print(f"  claim extraction failed: {e}")
            # an account with no check yet goes first, so the per-scan cap never starves one side
            d["positions"].sort(key=lambda q: bool(q.get("check")))
        # A re-summary rewords claims. Where a side's new claim is undecided and an earlier decided claim from
        # the same side of this story says the same thing, keep the earlier one, so a Confirmed doesn't
        # silently turn into a fresh Unproven. Same side means the claim's outlets share a side and none oppose.
        earlier = [(k, c) for k, c in claims.items() if story["sid"] in c.get("stories", []) and c.get("verdict") in DECIDED]
        used = {p.get("check") for d in brief["differences"] for p in d["positions"]}
        for d in brief["differences"]:
            for pos in d["positions"]:
                cur = claims.get(pos.get("check")) if pos.get("check") else None
                if not pos.get("checkable_claim") or (cur and cur.get("verdict") in DECIDED) or not earlier:
                    continue
                mine = {side_of.get(o) for o in pos["outlets"]} - {"unplaced", None}
                best, best_k = 0.0, None
                for k, c in earlier:
                    theirs = {side_of.get(o) for o in c.get("said_by", [])} - {"unplaced", None}
                    if k in used or not (mine & theirs) or ({"left", "right"} <= (mine | theirs)):
                        continue
                    sim = float(vec([pos["checkable_claim"]])[0] @ vec([c["claim"]])[0])
                    if sim > best:
                        best, best_k = sim, k
                if best_k and best >= CARRY_OVER:
                    print(f"  carry over ({best:.2f}): {claims[best_k]['claim'][:70]}")
                    pos["checkable_claim"], pos["check"] = claims[best_k]["claim"], best_k
                    used.add(best_k)
        # Factual differences are checked against primary sources (cached in the library).
        for d in brief["differences"]:
            if d.get("checkable_claim") and not d.get("check"):  # briefs written before per-side claims
                said_by = sorted({o for p in d["positions"] for o in p["outlets"]})
                d["check"] = check_claim(d["checkable_claim"], story["sid"], said_by)
            for pos in d["positions"]:  # each side's factual claim, checked the same way
                if pos.get("checkable_claim"):
                    pos["checkable_claim"] = deattribute(pos["checkable_claim"], pos["outlets"])
                if pos.get("checkable_claim") and not pos.get("check"):
                    pos["check"] = check_claim(pos["checkable_claim"], story["sid"], pos["outlets"])
        story["brief"] = brief
        story["checks"] = [k for d in brief["differences"] for k in [d.get("check")] + [p.get("check") for p in d["positions"]] if k]
        subj = brief.get("main_subject") or {}
        if subj.get("name") and subj.get("kind") in ("person", "organization", "place"):
            ikey = f"{subj['kind']}:{subj['name'].casefold()}"
            if ikey not in images:
                try:
                    images[ikey] = image_for(subj["name"], subj["kind"])  # None is cached too: no safe image
                except Exception as e:
                    print(f"  image lookup failed for {subj['name']}: {e}")
            if images.get(ikey):
                story["image"] = images[ikey]
        shared = [f for f in brief["agreed"] if "left" in f["sides"] and "right" in f["sides"]]
        print(f"  {story['sid']} [{story['topic']}]: {len(shared)} common ground of {len(brief['agreed'])} agreed, {len(brief['differences'])} differences")
        return bool(shared)  # Today shows only what both sides report; no common ground, no slot


    # Each topic: walk its ranking (stories covered by both left- and right-leaning outlets only) until
    # its quota has a real summary, trying at most EXTRA_CANDIDATES more. Only these appear on Today.
    both = lambda s: bool(s["coverage"].get("left")) and bool(s["coverage"].get("right"))
    for topic, quota in TOPIC_QUOTAS.items():
        cands = [s for s in data["stories"] if s.get("related_to") is None and s.get("topic") == topic and both(s)]
        done = 0
        for story in cands[:quota + EXTRA_CANDIDATES]:
            if done >= quota:
                break
            if process(story):
                done += 1
                story["on_today"] = True
        print(f"  {topic}: {done} of {quota} on Today ({len(cands)} stories covered by both sides)")

    write_archive([s for s in data["stories"] if s.get("on_today")], data.get("feeds", []))

    live = {s["sid"] for s in data["stories"]}
    lib["briefs"] = {k: v for k, v in briefs.items() if k in live}
    lib["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lib["caps"] = {"anthropic_daily_usd": ANTHROPIC_DAILY_USD, "gemini_daily_usd": GEMINI_DAILY_USD,
                   "gemini_free_searches": GEMINI_FREE_SEARCHES, "search_usd": SEARCH_USD, "new_claims_per_day": MAX_NEW_PER_DAY}
    (ROOT / "data/library.json").write_text(json.dumps(lib, indent=1))
    stories_path.write_text(json.dumps(data, indent=1))
    (ROOT / "data/.summarized").write_text(datetime.now(timezone.utc).isoformat())  # deploy publishes stories.json only with this
    print(f"check_today: {state['new_this_scan']} new claims · today anthropic ${spend['anthropic_usd']:.2f}/{ANTHROPIC_DAILY_USD:.2f} · "
          f"gemini ${spend['gemini_usd']:.2f}/{gemini_cap:.2f}, searches {spend['gemini_searches']} ({GEMINI_FREE_SEARCHES} free), "
          f"thinking tokens {THOUGHTS['tokens']} over {THOUGHTS['calls']} calls")
    return 0


def passage(url, quote, width=400):
    """The text around a verified quote on its own page, read by our code (never published)."""
    text, _ = C.fetch_page(url)
    if not text:
        text, _ = C.fetch_via_anthropic(url)
    if not text:
        return None
    q = C.norm(quote)
    i = text.find(q[:80])
    if i < 0:
        return None
    return text[max(0, i - width): i + len(q) + width]


_STOP = {"the", "a", "an", "and", "of", "in", "on", "at", "to", "for", "is", "was", "were", "by", "with", "that", "this", "as", "from"}


def mentions(url, claim, already, limit=4):
    """Sentences on the evidence page that name the claim's proper nouns or numbers and are not already
    shown, so a quote can be tied to the place, case or person the claim names. Our own read of the page."""
    text, _ = C.fetch_page(url)
    if not text:
        text, _ = C.fetch_via_anthropic(url)
    if not text:
        return []
    names = re.findall(r"(?:[A-Z][\w'.-]+(?:\s+(?:[A-Z][\w'.-]+|of|the))*)", claim)
    terms = {C.norm(t).strip(".,;:'\"") for t in names}
    terms = {t for t in terms if t not in _STOP and len(t) > 3} | set(C.numbers_in(claim))
    seen, out = C.norm(already), []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(sent) > 400 or sent in seen:
            continue
        if any(t in sent for t in terms):
            out.append(sent.strip())
            if len(out) >= limit:
                break
    return out


_QUOTED = re.compile(r"[\u201c\"][^\u201d\"]{1,300}[\u201d\"]|\u2018[^\u2019]{1,300}\u2019")


def verify_loaded(raw, arts, lines, side_of):
    """Keep a term only where it appears, outside quotation marks, in the cited outlet's own line (headline,
    summary or opening). Outlets and sides come from those verified lines, never from the model."""
    n, out, seen = len(arts), [], set()
    for t in raw.get("terms", [])[:10]:
        term = (t.get("term") or "").strip().strip('"\u201c\u201d')
        if not term or len(term) > 60 or term.casefold() in seen:
            continue
        found = []
        for i in t.get("articles", []):
            if isinstance(i, int) and 1 <= i <= n:
                own = _QUOTED.sub(" ", lines[i - 1].split(": ", 1)[-1])
                if term.casefold() in own.casefold():
                    found.append(arts[i - 1]["source"])
        if found:
            seen.add(term.casefold())
            outlets = sorted(set(found))
            out.append({"term": term, "outlets": outlets, "sides": sorted({side_of.get(o, "unplaced") for o in outlets}),
                        "why": (t.get("why") or "").strip(), "neutral": (t.get("neutral") or "").strip()})
    return out


def coverage_lines(arts, side_of, summaries):
    """The numbered coverage lines the models read: outlet, lean, headline, summary, and the article's opening."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        excerpts = list(pool.map(excerpt, [a["url"] for a in arts]))
    lines = []
    for i, (a, ex) in enumerate(zip(arts, excerpts)):
        summ = (summaries.get(a["url"]) or "")[:300]
        lines.append(f"{i + 1}. {a['source']} ({side_of.get(a['source'], 'unplaced')}): {a['title']}"
                     + (f" | {summ}" if summ else "") + (f" | Opening: {ex}" if ex else ""))
    return lines, excerpts


def pick_articles(arts, side_of, n):
    """Up to n articles, one per outlet first (newest), dealt round-robin left, right, center, unplaced,
    so the brief hears both sides equally whatever the article counts."""
    ordered = sorted(arts, key=lambda a: a.get("published") or "", reverse=True)
    seen, firsts, rest = set(), [], []
    for a in ordered:
        (rest if a["source"] in seen else firsts).append(a)
        seen.add(a["source"])
    by_side = {k: [] for k in ("left", "right", "center", "unplaced")}
    for a in firsts + rest:
        by_side[side_of.get(a["source"], "unplaced")].append(a)
    out = []
    while len(out) < n and any(by_side.values()):
        for k in by_side:
            if by_side[k] and len(out) < n:
                out.append(by_side[k].pop(0))
    return out


_P = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)
_JUNK = re.compile(r"subscribe|sign up|newsletter|cookie|all rights reserved|advertisement|click here", re.I)


def excerpt(url):
    """The opening paragraphs of an article, read for the brief only (never stored or published).
    A page that refuses us, or has no readable paragraphs, gives an empty string."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": C.UA})
        with urllib.request.urlopen(req, timeout=12, context=C.SSL_CTX) as r:
            page = r.read(2_000_000).decode("utf-8", "replace")
    except Exception:
        return ""
    page = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", page, flags=re.S | re.I)
    out = ""
    for m in _P.finditer(page):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        t = __import__("html").unescape(t)
        if len(t) >= 80 and not _JUNK.search(t):
            out += t + " "
            if len(out) >= EXCERPT_CHARS:
                break
    return out[:EXCERPT_CHARS].strip()


def _live_json(url):
    """A JSON file from the live site; None if it doesn't exist yet. Other failures raise."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": C.UA}), timeout=20, context=C.SSL_CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def write_archive(stories, feeds):
    """Keep every story that was on Today, by day (U.S. Eastern), so the site builds an archive. A story
    keeps its latest summary for the day. If the live archive can't be read, skip: never overwrite it."""
    day = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    try:
        arch = _live_json(f"{ARCHIVE_URL}{day}.json") or {"date": day, "stories": {}}
        index = _live_json(f"{ARCHIVE_URL}index.json") or {"days": []}
    except Exception as e:
        print(f"  archive not readable ({e}); not writing it this scan")
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    keep = ("sid", "working_title", "topic", "span", "outlets", "sources", "coverage", "articles", "checks", "image")
    for st in stories:
        rec = {k: st[k] for k in keep if k in st}
        rec["brief"] = {k: v for k, v in st["brief"].items() if k != "dropped_agreed"}
        rec["archived_at"] = now
        arch["stories"][st["sid"]] = rec
    arch["feeds"] = feeds
    arch["updated_at"] = now
    out = ROOT / "data/archive"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{day}.json").write_text(json.dumps(arch, indent=1))
    counts = {}
    for rec in arch["stories"].values():
        counts[rec.get("topic", "other")] = counts.get(rec.get("topic", "other"), 0) + 1
    days = [d for d in index["days"] if d["date"] != day] + [{"date": day, "count": len(arch["stories"]), "topics": counts}]
    index["days"] = sorted(days, key=lambda d: d["date"], reverse=True)
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"  archive {day}: {len(arch['stories'])} stories")


def deattribute(claim, outlets):
    """'Breitbart reported that X' checks only what an outlet said. Check X itself."""
    names = "|".join(re.escape(o) for o in sorted(outlets, key=len, reverse=True))
    out = re.sub(rf"^(?:the\s+)?(?:{names})\s+(?:reported|reports|says|said|states|stated|writes|wrote)\s+(?:that\s+)?",
                 "", claim.strip(), flags=re.I) if names else claim.strip()
    return out[:1].upper() + out[1:]


def build_brief(raw, arts, lines, side_of, ask, charge):
    """Keep only what the coverage supports: valid article numbers, and agreed facts that at least two
    different outlets state in their own headline or summary."""
    n = len(arts)
    valid = lambda idx: sorted({i for i in idx if isinstance(i, int) and 1 <= i <= n})
    outlets = lambda idx: sorted({arts[i - 1]["source"] for i in idx})

    # Common ground first, then other agreed facts; both pass the same confirmation, and the sides each
    # fact is confirmed on (not the writer's say-so) decide whether the page calls it common ground.
    seen, cands = set(), []
    for a in raw.get("common_ground", [])[:6] + raw.get("agreed", [])[:3]:
        key = a.get("fact", "").strip().casefold()
        if key and key not in seen:
            seen.add(key); cands.append(a)
    agreed = [(a["fact"].strip(), valid(a["articles"])) for a in cands]
    agreed = [(f, idx) for f, idx in agreed if len(outlets(idx)) >= MIN_OUTLETS_AGREED]
    confirmed, dropped = [], []
    for a in cands:
        f, idx = a.get("fact", "").strip(), valid(a.get("articles", []))
        if f and len(outlets(idx)) < MIN_OUTLETS_AGREED:
            dropped.append({"fact": f, "why": f"cited by {len(outlets(idx))} outlet(s)"})
    if agreed:
        facts = "\n".join(f"{j + 1}. {f}" for j, (f, _) in enumerate(agreed))
        # Confirm against every article, not only the ones the brief cited: an outlet that states the
        # fact counts whether or not the brief writer listed it. Missing one would hide common ground.
        # Pure matching, so low thinking: same answer, fewer billed thinking tokens.
        out, usage = ask(CONFIRM_PROMPT.replace("{facts}", facts).replace("{articles}", "\n".join(lines)), CONFIRM_SCHEMA, "low")
        charge(usage)
        stated = {f["fact"]: valid(f["stated_by"]) for f in out.get("facts", [])}
        for j, (fact, idx) in enumerate(agreed):
            by = stated.get(j + 1, [])  # an outlet counts if its own headline or summary states it
            if len(outlets(by)) >= MIN_OUTLETS_AGREED:
                confirmed.append({"fact": fact, "reported_by": outlets(by),
                                  "sides": sorted({side_of.get(o, "unplaced") for o in outlets(by)})})
            else:
                dropped.append({"fact": fact, "why": f"confirmed in {len(outlets(by))} outlet(s): {', '.join(outlets(by))}"})

    differences = []
    for d in raw.get("differences", [])[:3]:
        positions = [{"says": p["says"].strip(), "outlets": outlets(valid(p["articles"])),
                      "crux": c if (c := (p.get("crux") or "").strip()) and c in p["says"] and len(c) < len(p["says"].strip()) else "",
                      "checkable_claim": (p.get("checkable_claim") or "").strip(), "check": None} for p in d.get("positions", [])[:3]]
        positions = [p for p in positions if p["says"] and p["outlets"]]
        if d.get("point", "").strip() and positions:
            differences.append({"point": d["point"].strip(), "positions": positions,
                                "checkable_claim": (d.get("checkable_claim") or "").strip(), "check": None})
    values = [q.strip() for q in raw.get("values_questions", [])[:2] if q.strip()]
    subj = raw.get("main_subject") or {}
    return {"agreed": confirmed, "dropped_agreed": dropped, "differences": differences, "values_questions": values,
            "main_subject": {"name": (subj.get("name") or "").strip(), "kind": subj.get("kind", "none")}}


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never block the scan; the site keeps last hour's results
        print(f"check_today failed: {type(e).__name__}: {e}")
        sys.exit(0)
