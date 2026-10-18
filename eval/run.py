"""Run the claim checker over the test set and grade every answer in code.

  python eval/run.py --checker claude --variant baseline [--only p01L,p07R] [--reps 1]
  python eval/run.py --checker gemini --variant v1

Writes .claude/hillclimb/claim-check/<variant>/results.jsonl (one row per case and rep, written
as each finishes), traces/<id>_rep<k>.json (the full exchange plus the evidence check) and
errors.jsonl (attempts that produced nothing scorable: API errors, timeouts, wrong model). A
rerun skips (case, rep) pairs already in results.jsonl, so a crash loses nothing.

Calls the real entry point, pipeline/check.py, not a copy of it.
"""
import argparse
import concurrent.futures as cf
import json
import os
import random
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import check as C  # noqa: E402

FLOW = Path(os.environ.get("FACTUAL_EVAL_FLOW", ROOT / ".claude/hillclimb/claim-check"))
MODELS = {"claude": C.CLAUDE_MODEL, "gemini": C.GEMINI_MODEL}
TRANSIENT = ("429", "529", "500", "502", "503", "504", "overloaded", "rate", "timed out", "temporarily")
lock = threading.Lock()


def grade(case, r):
    gold = case["expected"]["verdict"]
    v = r["verdict"]
    if r["quotes_total"]:
        qv = r["quotes_verified"] / r["quotes_total"]
    else:
        qv = 1.0 if gold == C.VAL and v == C.VAL else 0.0
    return {
        "correct": float(v == gold),
        "false_conviction": float(v == C.DHU and gold in (C.HU, C.MC, C.VAL)),
        "quotes_verified": round(qv, 3),
        "numbers_ok": float(not r["numbers_unsourced"]),
        "raw_correct": float(r["verdict_raw"] == gold),
    }


def attempt(case, checker, model, rep, vdir, timeout_s):
    """One scored attempt with jittered backoff on transient errors and a hard wall-clock ceiling."""
    start, tries = time.time(), 0
    while True:
        tries += 1
        try:
            with cf.ThreadPoolExecutor(1) as one:
                fut = one.submit(C.check, case["prompt"], checker)
                r = fut.result(timeout=max(1, timeout_s - (time.time() - start)))
            break
        except cf.TimeoutError:
            return error_row(vdir, case, rep, "timeout", f"no answer within {timeout_s}s", tries)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if tries < 4 and any(t in msg.lower() for t in TRANSIENT) and time.time() - start < timeout_s - 30:
                time.sleep(min(60, 2 ** tries) * (0.5 + random.random()))
                continue
            return error_row(vdir, case, rep, "harness_or_serving_error", msg[:600] + "\n" + traceback.format_exc()[-800:], tries)

    served = r.get("served_model") or ""
    if not served.startswith(model):
        return error_row(vdir, case, rep, "served_model_mismatch", f"asked {model}, served {served}", tries, r)

    trace = r.pop("trace")
    trace.append({"role": "assistant", "name": "evidence check", "content": json.dumps({
        "verdict_from_model": r["verdict_raw"], "verdict_after_check": r["verdict"],
        "guard_notes": r["guard_notes"], "numbers_unsourced": r["numbers_unsourced"],
        "evidence": r["evidence_checked"]}, indent=2)})
    (vdir / "traces").mkdir(parents=True, exist_ok=True)
    (vdir / "traces" / f"{case['prompt_id']}_rep{rep}.json").write_text(json.dumps(trace, indent=1))
    row = {
        "prompt_id": case["prompt_id"], "rep": rep, "prompt": case["prompt"], "tags": case["tags"],
        "model": served, "stop_reason": r["stop_reason"],
        "status": "truncated" if r["stop_reason"] == "max_tokens" else "ok",
        "grade": grade(case, r),
        "usage": r["usage"], "latency_s": r["latency_s"], "web_searches": r["web_searches"],
        "meta": {"pair": case["pair"], "lean": case["tags"][1], "gold": case["expected"]["verdict"],
                 "verdict": r["verdict"], "verdict_raw": r["verdict_raw"], "tries": tries,
                 "quotes": f"{r['quotes_verified']}/{r['quotes_total']}", "guard_notes": r["guard_notes"],
                 "numbers_unsourced": r["numbers_unsourced"], "web_fetches": r.get("web_fetches", 0)},
    }
    with lock, open(vdir / "results.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def error_row(vdir, case, rep, kind, detail, tries, r=None):
    row = {"prompt_id": case["prompt_id"], "rep": rep, "failure": kind, "detail": detail, "tries": tries,
           "model": (r or {}).get("served_model"), "usage": (r or {}).get("usage"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with lock, open(vdir / "errors.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", choices=MODELS, required=True)
    ap.add_argument("--variant", required=True, help="baseline or v<N>")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout-s", type=int, default=420)
    a = ap.parse_args()
    C.load_env()

    cases = [json.loads(line) for line in (ROOT / "eval/claims.jsonl").read_text().splitlines() if line.strip()]
    if a.only:
        want = set(a.only.split(","))
        cases = [c for c in cases if c["prompt_id"] in want]
        missing = want - {c["prompt_id"] for c in cases}
        if missing:
            sys.exit(f"unknown case ids: {sorted(missing)}")
    vdir = FLOW / a.variant
    vdir.mkdir(parents=True, exist_ok=True)
    done = set()
    if (vdir / "results.jsonl").exists():
        done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, (vdir / "results.jsonl").read_text().splitlines())}
    todo = [(c, k) for c in cases for k in range(a.reps) if (c["prompt_id"], k) not in done]
    model = MODELS[a.checker]
    print(f"{a.variant}: {model}, {len(todo)} attempts to run ({len(done)} already done)")
    t0 = time.time()
    with cf.ThreadPoolExecutor(a.workers) as pool:
        futs = {pool.submit(attempt, c, a.checker, model, k, vdir, a.timeout_s): (c, k) for c, k in todo}
        for fut in cf.as_completed(futs):
            c, k = futs[fut]
            row = fut.result()
            if "failure" in row:
                print(f"  ERROR {c['prompt_id']} rep{k}: {row['failure']}: {row['detail'][:140]}")
            else:
                g = row["grade"]
                print(f"  {'ok ' if g['correct'] else 'MISS'} {c['prompt_id']:<5} gold={row['meta']['gold']:<16} got={row['meta']['verdict']!s:<16} quotes {row['meta']['quotes']}  {row['latency_s']}s")
    print(f"wall clock {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
