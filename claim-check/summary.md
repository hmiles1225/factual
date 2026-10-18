# Claim-check eval summary

### baseline · claude-opus-5-5
- Right verdict: **100%** (6 of 6; 95% range 61% to 100%)
- Before the evidence check: 100%
- False "Doesn't hold up": 0
- Quotes verified: 93% · numbers all sourced: 67%
- By side: left 100% of 2 · right 100% of 2 · neutral 100% of 2
- Mirror pairs judged unevenly: 0 of 0
- Cost: $3.37 total, $0.561 a claim (range $0.041-$0.938)
- Time: median 74s a claim · searches 20
- Errors (not scored): 1

| case | correct | got | before check | quotes | unsourced numbers |
|---|---|---|---|---|---|
| n04 | Holds up | ✓ Holds up | Holds up | 4/4 |  |
| p01L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 | 500000 |
| p07R | Missing context | ✓ Missing context | Missing context | 4/4 |  |
| p12R | Missing context | ✓ Missing context | Missing context | 3/5 | 3.951, 3.304 |
| p17L | Unproven | ✓ Unproven | Unproven | 4/4 |  |
| v01 | Values | ✓ Values | Values | 0/0 |  |

### v1 · gemini-3.8-flash
- Right verdict: **83%** (5 of 6; 95% range 44% to 97%)
- Before the evidence check: 83%
- False "Doesn't hold up": 0
- Quotes verified: 75% · numbers all sourced: 67%
- By side: left 100% of 2 · right 50% of 2 · neutral 100% of 2
- Mirror pairs judged unevenly: 0 of 0
- Cost: $1.16 total, $0.194 a claim (range $0.003-$0.561)
- Time: median 39s a claim · searches 67
- Errors (not scored): 6

| case | correct | got | before check | quotes | unsourced numbers |
|---|---|---|---|---|---|
| n04 | Holds up | ✓ Holds up | Holds up | 2/2 |  |
| p01L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/2 |  |
| p07R | Missing context | ✗ Unproven | Holds up | 0/2 | 4, 275, 1 |
| p12R | Missing context | ✓ Missing context | Missing context | 7/7 |  |
| p17L | Unproven | ✓ Unproven | Unproven | 1/2 | 0.7, 0.3 |
| v01 | Values | ✓ Values | Values | 0/0 |  |

### v2 · claude-opus-5-5
- Right verdict: **100%** (5 of 5; 95% range 57% to 100%)
- Before the evidence check: 100%
- False "Doesn't hold up": 0
- Quotes verified: 80% · numbers all sourced: 40%
- By side: left 100% of 2 · right 100% of 1 · neutral 100% of 2
- Mirror pairs judged unevenly: 0 of 0
- Cost: $2.47 total, $0.494 a claim (range $0.042-$1.087)
- Time: median 43s a claim · searches 16
- Errors (not scored): 1

| case | correct | got | before check | quotes | unsourced numbers |
|---|---|---|---|---|---|
| n04 | Holds up | ✓ Holds up | Holds up | 3/3 | 9, 3 |
| p01L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 5/5 |  |
| p12R | Missing context | ✓ Missing context | Missing context | 5/5 | 260.4 |
| p17L | Unproven | ✓ Unproven | Unproven | 0/3 | 0.7, 0.3, 1.5, 3.0 |
| v01 | Values | ✓ Values | Values | 0/0 |  |

### Two-model system: Gemini (v1) decides, Claude (baseline) second opinion
- Right verdict: **83%** of 6 · false "Doesn't hold up": 0

### Two-model system: Claude (baseline) decides, Gemini (v1) second opinion
- Right verdict: **100%** of 6 · false "Doesn't hold up": 0

### Two-model system: Gemini (v1) decides, Claude (v2) second opinion
- Right verdict: **100%** of 5 · false "Doesn't hold up": 0

### Two-model system: Claude (v2) decides, Gemini (v1) second opinion
- Right verdict: **100%** of 5 · false "Doesn't hold up": 0
