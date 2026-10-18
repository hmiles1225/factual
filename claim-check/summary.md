# Claim-check eval summary

### baseline · claude-opus-5-5
- Right verdict: **80%** (4 of 5, ±35% at 95%)
- Before the evidence check: 80%
- False "Doesn't hold up": 0
- Quotes verified: 92% · numbers all sourced: 60%
- By side: left 100% of 1 · right 50% of 2 · neutral 100% of 2
- Mirror pairs judged unevenly: 0 of 0
- Cost: $2.57 total, $0.514 a claim (range $0.041-$0.938)
- Time: median 54s a claim · searches 12
- Errors (not scored): 1

| case | correct | got | before check | quotes | unsourced numbers |
|---|---|---|---|---|---|
| n04 | Holds up | ✓ Holds up | Holds up | 4/4 |  |
| p01L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 | 500000 |
| p07R | Holds up | ✗ Missing context | Missing context | 4/4 |  |
| p12R | Missing context | ✓ Missing context | Missing context | 3/5 | 3.951, 3.304 |
| v01 | Values | ✓ Values | Values | 0/0 |  |

### v1
No scored rows (6 errors).


