"""Score the same-claim matcher's recorded answers (library.json "same_claim") against the hand labels in
eval/same_claim_labels.json. The bar for SAME_LIVE = True is zero wrong "same" answers: a wrong one gives a claim
someone else's verdict. A wrong "different" only means the claim is checked again, as it would be today.

    python eval/score_same.py            # reads the live library
    python eval/score_same.py lib.json   # or a saved copy
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import check as C  # noqa: E402  (its SSL context carries the CA bundle)
LIVE = "https://hestonmiles.com/factual/data/library.json"

if len(sys.argv) > 1:
    lib = json.loads(Path(sys.argv[1]).read_text())
else:
    req = urllib.request.Request(LIVE, headers={"User-Agent": "fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)"})
    lib = json.loads(urllib.request.urlopen(req, timeout=30, context=C.SSL_CTX).read())
labels = json.loads((ROOT / "eval/same_claim_labels.json").read_text())["pairs"]
answers = {frozenset((r["a"], r["b"])): r["same"] for r in lib.get("same_claim", {}).values() if isinstance(r, dict)}

rows, wrong_same, wrong_diff = [], 0, 0
for p in labels:
    if not p["num_match"]:
        got = "different (numbers differ, in code)"
        ok = p["label"] == "different"
    elif frozenset((p["a"], p["b"])) in answers:
        said = "same" if answers[frozenset((p["a"], p["b"]))] else "different"
        got, ok = f"{said} (model)", said == p["label"]
        wrong_same += said == "same" and not ok
        wrong_diff += said == "different" and not ok
    else:
        rows.append((p["n"], p["label"], "not asked yet", None))
        continue
    rows.append((p["n"], p["label"], got, ok))

for n, label, got, ok in rows:
    print(f"{n:>2}  hand: {label:<9}  matcher: {got:<38} {'' if ok is None else 'right' if ok else 'WRONG'}")
scored = [r for r in rows if r[3] is not None]
print(f"\n{sum(r[3] for r in scored)} of {len(scored)} right; wrong 'same': {wrong_same}; wrong 'different': {wrong_diff}; "
      f"not asked yet: {len(rows) - len(scored)}")
print("SAME_LIVE can be turned on." if scored and len(scored) == len(rows) and not wrong_same else "Keep SAME_LIVE = False.")
