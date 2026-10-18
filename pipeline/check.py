"""Stage 3: check one claim against sources fetched in this run.

The model may state only what it found in documents it retrieved this run. Code then
re-reads every cited page and keeps a quote only if it appears there word for word.
A verdict with no verified evidence is downgraded to Unproven. Numbers in the
explanation must appear in a verified quote. The verdict rules the model follows are
method/verdicts.md, sent verbatim, so the public method and the prompt cannot drift.

Two checkers, one output shape:
  check_claude(claim)  Claude Opus 5.5 with web search and web fetch
  check_gemini(claim)  Gemini 3.8 Flash with Google Search and URL context
combine(primary, second) applies the two-model rule for "Doesn't hold up".
"""
import html
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HU, MC, DHU, UN, VAL = "Holds up", "Missing context", "Doesn't hold up", "Unproven", "Values"
VERDICTS = [HU, MC, DHU, UN, VAL]
FLAGS = ["Correlation, not cause", "Totals, not rates", "Picked dates", "Too small to tell", "Forecast, not a finding"]
CLAUDE_MODEL = "claude-opus-5-5"
GEMINI_MODEL = "gemini-3.8-flash"
UA = "fACTUAL-check/0.1 (+https://hestonmiles.com/factual/)"
_CA = "/etc/ssl/cert.pem"
SSL_CTX = ssl.create_default_context(cafile=_CA) if os.path.exists(_CA) else ssl.create_default_context()

SCHEMA = {
    "type": "object",
    "properties": {
        "fact_or_values": {"type": "string", "enum": ["fact", "values"]},
        "verdict": {"type": "string", "enum": VERDICTS},
        "steelman": {"type": "string", "description": "Why this sounds right: the strongest honest reason someone believes it."},
        "finding": {"type": "string", "description": "What the evidence shows, in plain sentences. Never opens with a verdict-like word."},
        "reasoning_flags": {"type": "array", "items": {"type": "string", "enum": FLAGS}},
        "newest_data": {"type": "string", "description": "Which dataset release or study you relied on, its date, and how you confirmed no newer release exists."},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "publisher": {"type": "string"},
                    "published": {"type": "string"},
                    "quote": {"type": "string", "description": "Copied word for word from the page. No paraphrase."},
                    "role": {"type": "string", "enum": ["supports", "contradicts", "context"]},
                },
                "required": ["url", "publisher", "published", "quote", "role"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["fact_or_values", "verdict", "steelman", "finding", "reasoning_flags", "newest_data", "evidence"],
    "additionalProperties": False,
}

SYSTEM = """You are the claim checker for fACTUAL, a news app with no human editor. Nobody reviews your
answer before readers see it, so accuracy matters more than completeness.

How to work:
1. Decide first whether the claim is about facts or about values. A values claim (what should
   happen, what matters more) gets the verdict "Values" and needs no evidence.
2. For a factual claim, search for primary sources: the agency dataset, the official count, the
   study itself, the court filing. News outlets are not evidence; use them only to find the primary
   source.
3. Find the NEWEST release of every dataset you use. Search explicitly for a newer release before
   relying on a figure, and say in newest_data what you checked. Today's date is {today}.
4. Use only what you read in pages you retrieved during this task. Do not use facts from memory,
   even ones you are sure of. If you could not retrieve support for a point, leave it out.
5. Every evidence quote must be copied word for word from the page at that exact URL. Code will
   re-read the page and drop any quote it cannot find. Quote the sentence that carries the number.
6. Every number you write in "finding" must appear in one of your quotes.
7. Write "steelman" first: the strongest honest reason a reasonable person believes the claim.
   Never mock. Rate the claim, never the person or group who says it.

The verdict rules below are fACTUAL's published method. Follow them exactly.

{method}"""


def system_prompt():
    method = (ROOT / "method/verdicts.md").read_text()
    return SYSTEM.replace("{today}", time.strftime("%Y-%m-%d")).replace("{method}", method)


def user_prompt(claim):
    return f"Check this claim:\n\n\"{claim}\"\n\nReturn the JSON object described by the schema."


# ---------------------------------------------------------------- page text for verification

def norm(text):
    text = html.unescape(text or "")
    text = text.replace("­", "")
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("−", "-"), (" ", " ")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip().casefold()


def page_text(raw, content_type):
    if "pdf" in content_type or raw[:5] == b"%PDF-":
        import pypdf
        return " ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(raw)).pages)
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    return re.sub(r"<[^>]+>", " ", text)


_PAGE_CACHE = {}


def fetch_page(url):
    """Our own read of a cited page. Returns (normalized text, final url) or (None, error)."""
    if url in _PAGE_CACHE:
        return _PAGE_CACHE[url]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"})
        with urllib.request.urlopen(req, timeout=25, context=SSL_CTX) as r:
            raw = r.read(15_000_000)
            out = (norm(page_text(raw, r.headers.get("Content-Type", ""))), r.geturl())
    except Exception as e:
        out = (None, f"{type(e).__name__}: {e}"[:160])
    _PAGE_CACHE[url] = out
    return out


def quote_found(quote, text):
    q = norm(quote)
    if len(q) < 12:
        return False
    parts = [p.strip() for p in re.split(r"\.\.\.|…", q) if len(p.strip()) >= 12]
    pos = 0
    for p in parts or [q]:
        i = text.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return True


NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def numbers_in(text):
    """Numbers that must be sourced. Bare years are excluded: they date a fact, they are not one."""
    out = []
    for m in NUM.findall(text or ""):
        bare = m.rstrip("%").replace(",", "")
        if re.fullmatch(r"(19|20)\d\d", bare) and not m.endswith("%"):
            continue
        out.append(bare + ("%" if m.endswith("%") else ""))
    return out


def verify(result, fetched_docs=None):
    """Keep only evidence whose quote is on the page. Downgrade a verdict that loses its support."""
    out = result["output"]
    fetched_docs = fetched_docs or {}
    checked, notes = [], []
    for ev in out.get("evidence", []):
        url = ev.get("url", "")
        text = fetched_docs.get(url) or None
        how, info = "model fetch", ""
        if text is None:
            text, info = fetch_page(url)
            how = "our fetch"
        ok = bool(text) and quote_found(ev.get("quote", ""), text)
        checked.append({**ev, "verified": ok, "checked_by": how if text else f"unreachable ({info})"})
    verified = [e for e in checked if e["verified"]]
    sourced = " ".join(norm(e["quote"]) for e in verified).replace(",", "")
    unsourced = [n for n in numbers_in(out.get("finding", "")) if n.casefold() not in sourced and n.rstrip("%") not in sourced]

    verdict = out.get("verdict")
    if verdict in (HU, MC, DHU) and not [e for e in verified if e["role"] in ("supports", "contradicts")]:
        notes.append(f"downgraded from {verdict}: no verified supporting or contradicting evidence")
        verdict = UN
    result.update({
        "verdict_raw": out.get("verdict"),
        "verdict": verdict,
        "evidence_checked": checked,
        "quotes_total": len(checked),
        "quotes_verified": len(verified),
        "numbers_unsourced": unsourced,
        "guard_notes": notes,
    })
    return result


def combine(primary, second):
    """Two-model rule: Doesn't hold up stands only if a different model family agrees."""
    if primary["verdict"] == DHU and second["verdict"] != DHU:
        return UN, f"{primary['model']} said Doesn't hold up; {second['model']} said {second['verdict']}"
    return primary["verdict"], None


# ---------------------------------------------------------------- Claude

def check_claude(claim, model=CLAUDE_MODEL):
    import anthropic
    client = anthropic.Anthropic(max_retries=4)
    system = system_prompt()
    messages = [{"role": "user", "content": user_prompt(claim)}]
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    searches = fetches = 0
    trace = [{"role": "system", "content": system}, {"role": "user", "content": messages[0]["content"]}]
    fetched, served, t0 = {}, None, time.time()
    for _ in range(5):  # pause_turn continuations
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
                   {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}],
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        served = resp.model
        u = resp.usage
        for k in usage:
            usage[k] += getattr(u, k, 0) or 0
        stu = getattr(u, "server_tool_use", None)
        if stu is not None:
            searches += getattr(stu, "web_search_requests", 0) or 0
            fetches += getattr(stu, "web_fetch_requests", 0) or 0
        for block in resp.to_dict()["content"]:
            t = block.get("type")
            if t == "server_tool_use":
                trace.append({"role": "tool_call", "name": block.get("name"), "content": json.dumps(block.get("input"), indent=2)})
            elif t == "web_fetch_tool_result":
                c = block.get("content") or {}
                doc = (c.get("content") or {}).get("source") or {}
                if c.get("url") and doc.get("data"):
                    fetched[c["url"]] = norm(doc["data"] if doc.get("type") == "text" else "")
                trace.append({"role": "tool_result", "content": f"fetched {c.get('url')} ({len(doc.get('data') or '')} chars)"})
            elif t == "web_search_tool_result":
                res = block.get("content")
                urls = [r.get("url") for r in res] if isinstance(res, list) else [str(res)]
                trace.append({"role": "tool_result", "content": "search results:\n" + "\n".join(urls)})
            elif t == "text":
                trace.append({"role": "assistant", "content": block.get("text", "")})
        if resp.stop_reason == "pause_turn":
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
            continue
        break
    text = next((b.text for b in reversed(resp.content) if b.type == "text"), "")
    result = {"checker": "claude", "model": model, "served_model": served, "stop_reason": resp.stop_reason,
              "usage": usage, "web_searches": searches, "web_fetches": fetches, "latency_s": round(time.time() - t0, 1),
              "trace": trace}
    if resp.stop_reason in ("refusal", "max_tokens"):
        result["output"] = {"verdict": None, "evidence": [], "finding": ""}
        return result, fetched
    result["output"] = json.loads(text)
    return result, fetched


# ---------------------------------------------------------------- Gemini

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


def _walk(node, fn):
    fn(node)
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk(v, fn)


def check_gemini(claim, model=GEMINI_MODEL):
    key = os.environ["GEMINI_API_KEY"]
    system = system_prompt()
    body = {
        "model": model,
        "input": system + "\n\n" + user_prompt(claim),
        "tools": [{"type": "google_search"}, {"type": "url_context"}],
        "response_format": {"type": "text", "mime_type": "application/json", "schema": SCHEMA},
    }
    data = json.dumps(body).encode()
    t0 = time.time()
    raw = None
    # The docs send the key in a header. Gemini 3.x generateContent once rejected that with an
    # empty 404 and accepted ?key=, so fall back to the query form on a 404 only.
    for url, headers in ((GEMINI_URL, {"x-goog-api-key": key}), (f"{GEMINI_URL}?key={key}", {})):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=300, context=SSL_CTX) as r:
                raw = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code == 404 and not detail.strip():
                continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from None
    if raw is None:
        raise RuntimeError("Gemini: empty 404 on both auth forms")

    texts, queries, cited = [], [], []

    def grab(n):
        if not isinstance(n, dict):
            return
        if n.get("type") == "text" and isinstance(n.get("text"), str):
            texts.append(n["text"])
        if isinstance(n.get("queries"), list):
            queries.extend(q for q in n["queries"] if isinstance(q, str))
        if n.get("type") == "url_citation" and n.get("url"):
            cited.append(n["url"])
    _walk(raw.get("steps", raw), grab)
    text = raw.get("output_text") or (texts[-1] if texts else "")
    u = raw.get("usage") or {}
    usage = {"input_tokens": u.get("input_tokens") or u.get("total_input_tokens") or 0,
             "output_tokens": (u.get("output_tokens") or u.get("total_output_tokens") or 0) + (u.get("thought_tokens") or u.get("total_thought_tokens") or 0),
             "cache_read_input_tokens": u.get("cached_tokens") or u.get("total_cached_tokens") or 0,
             "cache_creation_input_tokens": 0}
    trace = [{"role": "system", "content": system}, {"role": "user", "content": user_prompt(claim)}]
    if queries:
        trace.append({"role": "tool_call", "name": "google_search", "content": json.dumps(queries, indent=2)})
    if cited:
        trace.append({"role": "tool_result", "content": "cited:\n" + "\n".join(dict.fromkeys(cited))})
    trace.append({"role": "assistant", "content": text})
    result = {"checker": "gemini", "model": model, "served_model": raw.get("model", model), "stop_reason": raw.get("status", "completed"),
              "usage": usage, "usage_raw": u, "web_searches": len(queries), "web_fetches": 0,
              "latency_s": round(time.time() - t0, 1), "trace": trace}
    try:
        result["output"] = json.loads(text)
    except json.JSONDecodeError:
        result["raw_response"] = raw
        raise RuntimeError(f"Gemini returned non-JSON output: {text[:200]!r}")
    return result, {}


def check(claim, checker="claude"):
    result, fetched = (check_claude if checker == "claude" else check_gemini)(claim)
    if result["output"].get("verdict") is None:
        result.update({"verdict": None, "verdict_raw": None, "evidence_checked": [], "quotes_total": 0,
                       "quotes_verified": 0, "numbers_unsourced": [], "guard_notes": [f"no verdict: {result['stop_reason']}"]})
        return result
    return verify(result, fetched)


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)", line)
            if m:
                os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))


if __name__ == "__main__":
    load_env()
    which = sys.argv[2] if len(sys.argv) > 2 else "claude"
    r = check(sys.argv[1], which)
    r.pop("trace", None)
    print(json.dumps(r, indent=1)[:6000])
