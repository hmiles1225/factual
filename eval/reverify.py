"""Re-run the evidence check on a variant's saved answers, without calling any model.

  python eval/reverify.py v1 v4

Reads each trace's model answer from <src>, runs pipeline/check.py's verify() again (current code),
and writes graded rows to <dst>. Use it when the verifier changes: the model's answers stay
exactly as they were, so any change in score is the verifier's, not the model's.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "eval"))
import check as C  # noqa: E402
import run as R  # noqa: E402

FLOW = Path(os.environ.get("FACTUAL_EVAL_FLOW", ROOT / ".claude/hillclimb/claim-check"))
src, dst = FLOW / sys.argv[1], FLOW / sys.argv[2]
cases = {c["prompt_id"]: c for c in map(json.loads, (ROOT / "eval/claims.jsonl").read_text().splitlines())}
(dst / "traces").mkdir(parents=True, exist_ok=True)
rows_out = []
for line in (src / "results.jsonl").read_text().splitlines():
    row = json.loads(line)
    trace = json.loads((src / "traces" / f"{row['prompt_id']}_rep{row['rep']}.json").read_text())
    answer = next(t["content"] for t in reversed(trace) if t["role"] == "assistant" and t.get("name") != "evidence check")
    r = C.verify({"output": json.loads(answer)})
    trace = [t for t in trace if t.get("name") != "evidence check"] + [{"role": "assistant", "name": "evidence check", "content": json.dumps({
        "verdict_from_model": r["verdict_raw"], "verdict_after_check": r["verdict"], "guard_notes": r["guard_notes"],
        "numbers_unsourced": r["numbers_unsourced"], "evidence": r["evidence_checked"]}, indent=2)}]
    (dst / "traces" / f"{row['prompt_id']}_rep{row['rep']}.json").write_text(json.dumps(trace, indent=1))
    row["grade"] = R.grade(cases[row["prompt_id"]], r)
    row["meta"].update({"verdict": r["verdict"], "verdict_raw": r["verdict_raw"], "quotes": f"{r['quotes_verified']}/{r['quotes_total']}",
                        "guard_notes": r["guard_notes"], "numbers_unsourced": r["numbers_unsourced"], "reverified_from": sys.argv[1]})
    rows_out.append(row)
    print(f"  {row['prompt_id']:<5} {row['meta']['quotes']:>5}  {'ok ' if row['grade']['correct'] else 'MISS'} {r['verdict']}")
pipe = C.PIPE_USAGE
cost = sum(u["input_tokens"] * (0.10 if "haiku" in u["model"] else 2.0) + u["output_tokens"] * (0.50 if "haiku" in u["model"] else 10.0) for u in pipe) / 1e6
(dst / "pipe_usage.json").write_text(json.dumps({"fetches": len(pipe), "usd": round(cost, 4), "calls": pipe}, indent=1))
print(f"verification fetches through Anthropic: {len(pipe)}, about ${cost:.2f}")
(dst / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_out))
(dst / "change.md").write_text(f"{sys.argv[1]}'s answers, re-verified with the current evidence check\n"
                               "No model was called. Same answers as " + sys.argv[1] + "; only the verifier changed (Google grounding redirects resolved to real URLs).\n")
