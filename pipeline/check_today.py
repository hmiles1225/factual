"""Stage 3 on the live site: check the claims in Today's top stories.

Runs after cluster.py in the hourly scan. For each of Today's top stories:
  1. Gemini lists up to 3 checkable claims that appear in the coverage (and any values question).
  2. A claim already in the library is reused. Only new claims are checked: Gemini checks,
     code verifies every quote, and a "Doesn't hold up" stands only if Claude Opus agrees.
  3. Each story gets "The verdict", assembled in code from its checked claims. No model writes it,
     so it cannot say anything its claims do not.

The library (data/library.json) is read back from the live site at the start of each scan, so a
claim is paid for once. Spend is capped per day in code; when a cap is reached, a Doesn't hold up
waits as Unproven and gets its second opinion when budget allows. A failure here never blocks the
scan: the site keeps last hour's verdicts.
"""
import hashlib
import json
import os
import re
import sys
import time
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
GEMINI_DAILY_USD = 0.50
GEMINI_DAILY_SEARCHES = 150      # Google gives 5,000 free a month across Gemini 3 models
UNDERCOUNT = 1.7                 # our cost log ran this far under the real bill (2026-10-17)
RECHECK_AFTER_DAYS = 7
OPUS_TYPICAL_USD = 0.51          # measured mean per Opus second opinion, 2026-10-17 eval
SAME_CLAIM = 0.93                # embedding similarity at which two wordings are one claim
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.010), "claude-haiku-5-5": (0.10, 0.50, 0), "claude-sonnet-5-5": (2.00, 10.00, 0),
          "gemini-3.8-flash": (0.75, 3.75, 0.0)}   # Gemini searches are tracked by count, not dollars

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "One checkable factual statement, worded as close to the coverage as possible."},
                    "articles": {"type": "array", "items": {"type": "integer"}, "description": "Numbers of the articles that make this claim."},
                },
                "required": ["claim", "articles"],
                "additionalProperties": False,
            },
        },
        "values_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "values_questions"],
    "additionalProperties": False,
}

EXTRACT_PROMPT = """You pick the claims a fact-checker should check in one news story. Below are the
headlines and summaries from several outlets covering the same event, numbered.

Rules:
- Return at most 3 claims. Each must be a factual statement that appears in this coverage and can be
  checked against a primary source (a number, an event, a finding, a quote of record).
- Word each claim as close to the coverage as you can. Do not add facts that are not in it.
- List the article numbers that make each claim. Use only numbers from the list.
- Prefer the claims the story turns on. If outlets on different sides make different factual claims,
  include claims from more than one side.
- A question about what should happen or what matters more is a values question, not a claim.
  List up to 2 of those separately, worded neutrally.
- If nothing in the coverage is checkable, return no claims.

Coverage:
{coverage}"""


SUPPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "established": {"type": "string", "enum": ["all", "part", "none"]},
        "missing": {"type": "string", "description": "The part of the claim the quotes do not establish, if any."},
    },
    "required": ["established", "missing"],
    "additionalProperties": False,
}
SUPPORT_PROMPT = """Below is a claim and some quotes, each copied word for word from its source page.
Using ONLY these quotes, not anything you know, decide whether they establish every part of the claim
exactly as it is stated. Pay attention to strong words: a quote saying someone left or was asked to
reconsider does not establish that they were fired; a total does not establish a record.

Answer "all" only if every part of the claim, as worded, is stated in the quotes. Answer "part" if some
of it is and some is not, and say what is missing. Answer "none" if the quotes do not support it.

Claim: {claim}

Quotes:
{quotes}"""


def support_check(claim, evidence):
    """Holds up must follow from the verified quotes alone. Returns (ok, missing, usage)."""
    quotes = "\n".join(f"- \"{e['quote']}\" ({e['publisher']})" for e in evidence if e.get("role") in ("supports", "context"))
    if not quotes:
        return False, "no verified quote supports it", {}
    out, usage = gemini_json(SUPPORT_PROMPT.replace("{claim}", claim).replace("{quotes}", quotes), SUPPORT_SCHEMA)
    return out["established"] == "all", out.get("missing", ""), usage


def cost_usd(model, usage, searches=0):
    p = next((v for k, v in PRICES.items() if model and model.startswith(k)), (4.0, 20.0, 0.01))
    u = usage or {}
    tin = u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0) + 0.1 * u.get("cache_read_input_tokens", 0)
    return (tin * p[0] + u.get("output_tokens", 0) * p[1]) / 1e6 + searches * p[2]


def load_library():
    """Last scan's library from the live site. Only a 404 means 'start empty'; any other failure
    means skip checking this scan, so a network blip can never trigger a full, paid re-check."""
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


def public_record(claim, first, second, verdict, note, story_ids):
    """What readers see. Only verified evidence is published."""
    finding, dropped = sourced_finding(first)
    ev = [{k: e[k] for k in ("url", "publisher", "published", "quote", "role")} for e in first["evidence_checked"] if e["verified"]]
    if second and second.get("evidence_checked"):
        ev += [{k: e[k] for k in ("url", "publisher", "published", "quote", "role")} for e in second["evidence_checked"] if e["verified"] and e["url"] not in {x["url"] for x in ev}]
    out = first["output"]
    return {
        "claim": claim["claim"], "verdict": verdict, "steelman": out.get("steelman", ""), "finding": finding,
        "sentences_dropped": dropped, "reasoning_flags": out.get("reasoning_flags", []), "newest_data": out.get("newest_data", ""),
        "evidence": ev, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked_by": first["model"], "second_opinion": (second or {}).get("model"),
        "second_verdict": (second or {}).get("verdict"), "note": note, "stories": story_ids,
        "model_verdict": first["verdict_raw"], "pending_second": note == "second opinion waiting for budget",
    }


def main():
    C.load_env()
    if not (os.environ.get("GEMINI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        print("check_today: API keys not set; skipping checks")
        return 0
    stories_path = ROOT / "data/stories.json"
    data = json.loads(stories_path.read_text())
    try:
        lib = load_library()
    except Exception as e:
        print(f"check_today: could not read the library ({e}); skipping checks this scan")
        return 0

    today = datetime.now(timezone.utc).date().isoformat()
    spend = lib.setdefault("spend", {}).setdefault(today, {"anthropic_usd": 0.0, "gemini_usd": 0.0, "gemini_searches": 0, "new_claims": 0})
    lib["spend"] = {d: v for d, v in lib["spend"].items() if d >= (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()}
    claims = lib.setdefault("claims", {})

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

    def anthropic_left():
        return ANTHROPIC_DAILY_USD - spend["anthropic_usd"]

    def charge_anthropic(model, usage, searches=0):
        spend["anthropic_usd"] = round(spend["anthropic_usd"] + UNDERCOUNT * cost_usd(model, usage, searches), 4)

    def charge_pipe():
        for u in C.PIPE_USAGE:
            charge_anthropic(u["model"], u)
        C.PIPE_USAGE.clear()

    def apply_support_check(record):
        if record["verdict"] != C.HU or "support" in record:
            return
        if spend["gemini_usd"] >= GEMINI_DAILY_USD + 0.10:  # small reserve: this guard is cheap and protects readers
            return
        try:
            ok, missing, usage = support_check(record["claim"], record["evidence"])
        except Exception as e:
            print(f"  support check failed: {e}")
            return
        spend["gemini_usd"] = round(spend["gemini_usd"] + UNDERCOUNT * cost_usd(C.GEMINI_MODEL, usage), 4)
        record["support"] = "all" if ok else "partial"
        if not ok:
            record["verdict"] = C.UN
            record["note"] = f"the sources confirm part of this claim, not all of it as stated: {missing}".rstrip(": ")
            print(f"  Holds up -> Unproven (support check): {record['claim'][:70]}")

    for rec in claims.values():  # claims checked before this guard existed
        apply_support_check(rec)

    top = [s for s in data["stories"] if s.get("related_to") is None][:TOP_STORIES]
    new_this_scan = 0
    for story in top:
        coverage = "\n".join(f"{i + 1}. {a['source']}: {a['title']}" for i, a in enumerate(story["articles"][:12]))
        cached = lib.setdefault("extractions", {}).get(story["sid"])
        if cached and cached["coverage"] == coverage:
            extracted = cached["result"]  # same coverage as last scan: no new extraction call
        else:
            if spend["gemini_usd"] >= GEMINI_DAILY_USD:
                continue
            try:
                extracted, usage = gemini_json(EXTRACT_PROMPT.replace("{coverage}", coverage), EXTRACT_SCHEMA)
            except Exception as e:
                print(f"  extract failed for {story['sid']}: {e}")
                continue
            spend["gemini_usd"] = round(spend["gemini_usd"] + UNDERCOUNT * cost_usd(C.GEMINI_MODEL, usage), 4)
            lib["extractions"][story["sid"]] = {"coverage": coverage, "result": extracted, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        story_keys = []
        for cl in extracted.get("claims", [])[:3]:
            idx = [i for i in cl.get("articles", []) if 1 <= i <= min(12, len(story["articles"]))]
            if not idx or not cl.get("claim", "").strip():
                continue  # a claim no listed article makes is dropped, never checked
            cl["said_by"] = sorted({story["articles"][i - 1]["source"] for i in idx})
            existing = find_existing(cl["claim"])
            rec = claims.get(existing) if existing else None
            fresh = rec and datetime.fromisoformat(rec["checked_at"]) > datetime.now(timezone.utc) - timedelta(days=RECHECK_AFTER_DAYS)
            if rec and fresh and not rec.get("pending_second"):
                rec["stories"] = sorted(set(rec.get("stories", [])) | {story["sid"]})
                story_keys.append(existing)
                continue
            if new_this_scan >= MAX_NEW_PER_SCAN or spend["new_claims"] >= MAX_NEW_PER_DAY \
                    or spend["gemini_usd"] >= GEMINI_DAILY_USD or spend["gemini_searches"] >= GEMINI_DAILY_SEARCHES:
                if rec:
                    story_keys.append(existing)
                continue

            try:
                first = C.check(cl["claim"], "gemini")
            except Exception as e:
                print(f"  check failed: {cl['claim'][:60]}: {e}")
                continue
            charge_pipe()
            spend["gemini_usd"] = round(spend["gemini_usd"] + UNDERCOUNT * cost_usd(C.GEMINI_MODEL, first["usage"]), 4)
            spend["gemini_searches"] += first.get("web_searches", 0)
            spend["new_claims"] += 1
            new_this_scan += 1
            first.pop("trace", None)

            second, note, verdict = None, None, first["verdict"]
            if verdict == C.DHU:
                if anthropic_left() >= OPUS_TYPICAL_USD:   # room for one Opus check at its measured typical cost
                    try:
                        second = C.check(cl["claim"], "claude")
                        second.pop("trace", None)
                        charge_anthropic(second["model"], second["usage"], second.get("web_searches", 0))
                        charge_pipe()
                        verdict, why = C.combine(first, second)
                        note = why
                    except Exception as e:
                        verdict, note = C.UN, f"second opinion failed: {str(e)[:120]}"
                else:
                    verdict, note = C.UN, "second opinion waiting for budget"
            k = existing or key_of(cl["claim"])
            record = public_record(cl, first, second, verdict, note, sorted(set((rec or {}).get("stories", [])) | {story["sid"]}))
            record["said_by"] = cl["said_by"]
            apply_support_check(record)
            claims[k] = record
            story_keys.append(k)
            print(f"  {verdict:<16} {cl['claim'][:80]}")
        story["checks"] = story_keys
        story["values_questions"] = extracted.get("values_questions", [])[:2]
        story["verdict"] = assemble(story_keys, claims, story["values_questions"])

    live = {s["sid"] for s in data["stories"]}
    lib["extractions"] = {k: v for k, v in lib.get("extractions", {}).items() if k in live}
    lib["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lib["caps"] = {"anthropic_daily_usd": ANTHROPIC_DAILY_USD, "gemini_daily_usd": GEMINI_DAILY_USD,
                   "gemini_daily_searches": GEMINI_DAILY_SEARCHES, "new_claims_per_day": MAX_NEW_PER_DAY}
    (ROOT / "data/library.json").write_text(json.dumps(lib, indent=1))
    stories_path.write_text(json.dumps(data, indent=1))
    print(f"check_today: {new_this_scan} new claims · today anthropic ${spend['anthropic_usd']:.2f}/{ANTHROPIC_DAILY_USD:.2f} · "
          f"gemini ${spend['gemini_usd']:.2f}/{GEMINI_DAILY_USD:.2f}, searches {spend['gemini_searches']}/{GEMINI_DAILY_SEARCHES}")
    return 0


def assemble(keys, claims, values_questions):
    """The verdict, built only from checked claims. Three lines, always."""
    recs = [claims[k] | {"key": k} for k in keys if k in claims]
    true = [r for r in recs if r["verdict"] in (C.HU, C.MC)]
    not_true = [r for r in recs if r["verdict"] == C.DHU]
    open_ = [r for r in recs if r["verdict"] == C.UN]
    return {
        "true": [{"key": r["key"], "verdict": r["verdict"]} for r in true],
        "not_true": [{"key": r["key"], "verdict": r["verdict"]} for r in not_true],
        "open": [{"key": r["key"], "verdict": r["verdict"]} for r in open_] + [{"values": q} for q in values_questions],
        "checked": len(recs),
    }


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never block the scan; the site keeps last hour's verdicts
        print(f"check_today failed: {type(e).__name__}: {e}")
        sys.exit(0)
