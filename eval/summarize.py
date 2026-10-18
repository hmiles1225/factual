"""Summarize eval runs: per-model scores, left/right fairness, the two-model system, and cost.

  python eval/summarize.py baseline v1

Recomputes every number from the per-case rows in results.jsonl; nothing is read from an
aggregate. Cost comes from each row's recorded model and token usage at the prices below.
"""
import json
import os
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOW = Path(os.environ.get("FACTUAL_EVAL_FLOW", ROOT / ".claude/hillclimb/claim-check"))
DHU, UN = "Doesn't hold up", "Unproven"

# USD per million tokens, and per search. Checked 2026-10-17:
# Claude: platform pricing table; web search $10 per 1,000.
# Gemini 3.8 Flash: ai.google.dev pricing, rate through 2026-12-31 (doubles 2027-01-01);
# Google Search grounding 5,000 free a month, then $14 per 1,000 (priced here at $14, worst case).
PRICES = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "search": 0.010},
    "gemini-3.8-flash": {"in": 0.75, "out": 3.75, "search": 0.014},
}


def cost(row):
    p = next((v for k, v in PRICES.items() if row["model"].startswith(k)), None)
    if p is None:
        return float("nan")
    u = row["usage"]
    tokens_in = u["input_tokens"] + 1.25 * u.get("cache_creation_input_tokens", 0) + 0.1 * u.get("cache_read_input_tokens", 0)
    return (tokens_in * p["in"] + u["output_tokens"] * p["out"]) / 1e6 + row.get("web_searches", 0) * p["search"]


GOLD = {c["prompt_id"]: c["expected"]["verdict"] for c in map(json.loads, (ROOT / "eval/claims.jsonl").read_text().splitlines())}


def regrade(row):
    """Score against the current answer key, so a corrected answer applies to past runs too."""
    gold, v = GOLD[row["prompt_id"]], row["meta"]["verdict"]
    row["meta"]["gold"] = gold
    row["grade"]["correct"] = float(v == gold)
    row["grade"]["raw_correct"] = float(row["meta"]["verdict_raw"] == gold)
    row["grade"]["false_conviction"] = float(v == DHU and gold in ("Holds up", "Missing context", "Values"))
    return row


def load(variant):
    path = FLOW / variant / "results.jsonl"
    rows = [regrade(json.loads(line)) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    errs = FLOW / variant / "errors.jsonl"
    nerr = len(errs.read_text().splitlines()) if errs.exists() else 0
    return rows, nerr


def wilson(k, n, z=1.96):
    """95% range for a rate. Stays honest at small n and at 0 or 100%, where the simple formula says ±0."""
    if not n:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def report(variant, rows, nerr):
    ok = [r for r in rows if r["status"] == "ok"]
    n = len(ok)
    if not n:
        return f"### {variant}\nNo scored rows ({nerr} errors).\n"
    mean = lambda k, rs=ok: sum(r["grade"][k] for r in rs) / len(rs) if rs else float("nan")
    acc = mean("correct")
    by_lean = {lean: [r for r in ok if r["meta"]["lean"] == lean] for lean in ("left", "right", "neutral")}
    pairs = defaultdict(dict)
    for r in ok:
        if r["meta"]["pair"]:
            pairs[r["meta"]["pair"]][r["meta"]["lean"]] = r
    full = {p: d for p, d in pairs.items() if "left" in d and "right" in d}
    uneven = [p for p, d in full.items() if d["left"]["grade"]["correct"] != d["right"]["grade"]["correct"]]
    costs = [cost(r) for r in rows]
    lines = [
        f"### {variant} · {ok[0]['model']}",
        f"- Right verdict: **{acc:.0%}** ({sum(r['grade']['correct'] for r in ok):.0f} of {n}; 95% range {wilson(round(acc * n), n)[0]:.0%} to {wilson(round(acc * n), n)[1]:.0%})",
        f"- Before the evidence check: {mean('raw_correct'):.0%}",
        f"- False \"Doesn't hold up\": {sum(r['grade']['false_conviction'] for r in ok):.0f}",
        f"- Quotes verified: {mean('quotes_verified'):.0%} · numbers all sourced: {mean('numbers_ok'):.0%}",
        "- By side: " + " · ".join(f"{k} {mean('correct', v):.0%} of {len(v)}" for k, v in by_lean.items() if v),
        f"- Mirror pairs judged unevenly: {len(uneven)} of {len(full)}" + (f" ({', '.join(sorted(uneven))})" if uneven else ""),
        f"- Cost: ${sum(costs):.2f} total, ${sum(costs) / len(rows):.3f} a claim (range ${min(costs):.3f}-${max(costs):.3f})",
        f"- Time: median {sorted(r['latency_s'] for r in rows)[len(rows) // 2]:.0f}s a claim · searches {sum(r.get('web_searches', 0) for r in rows)}",
        f"- Errors (not scored): {nerr}",
        "",
        "| case | correct | got | before check | quotes | unsourced numbers |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(ok, key=lambda r: r["prompt_id"]):
        m = r["meta"]
        lines.append(f"| {r['prompt_id']} | {m['gold']} | {'✓ ' if r['grade']['correct'] else '✗ '}{m['verdict']} | {m['verdict_raw']} | {m['quotes']} | {', '.join(m['numbers_unsourced'])} |")
    return "\n".join(lines) + "\n"


def system(primary, second, name):
    a = {r["prompt_id"]: r for r in primary if r["status"] == "ok"}
    b = {r["prompt_id"]: r for r in second if r["status"] == "ok"}
    both = sorted(a.keys() & b.keys())
    if not both:
        return ""
    right = convictions = 0
    for cid in both:
        v = a[cid]["meta"]["verdict"]
        if v == DHU and b[cid]["meta"]["verdict"] != DHU:
            v = UN
        gold = a[cid]["meta"]["gold"]
        right += v == gold
        convictions += v == DHU and gold in ("Holds up", "Missing context", "Values")
    return (f"### Two-model system: {name}\n- Right verdict: **{right / len(both):.0%}** of {len(both)} · "
            f"false \"Doesn't hold up\": {convictions}\n")


if __name__ == "__main__":
    variants = sys.argv[1:] or ["baseline", "v1"]
    data = {v: load(v) for v in variants}
    out = ["# Claim-check eval summary", ""]
    for v, (rows, nerr) in data.items():
        out.append(report(v, rows, nerr))
    if len(variants) == 2:
        (a, _), (b, _) = data[variants[0]], data[variants[1]]
        out.append(system(a, b, f"{variants[0]} decides, {variants[1]} second opinion"))
        out.append(system(b, a, f"{variants[1]} decides, {variants[0]} second opinion"))
    text = "\n".join(out)
    (FLOW / "summary.md").write_text(text)
    print(text)
