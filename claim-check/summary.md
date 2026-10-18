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
- Right verdict: **78%** (39 of 50; 95% range 65% to 87%)
- Before the evidence check: 90%
- False "Doesn't hold up": 1
- Quotes verified: 68% · numbers all sourced: 52%
- By side: left 74% of 19 · right 68% of 19 · neutral 100% of 12
- Mirror pairs judged unevenly: 7 of 19 (p02, p06, p07, p10, p12, p14, p19)
- Cost: $9.15 total, $0.183 a claim (range $0.003-$0.604)
- Time: median 59s a claim · searches 498
- Errors (not scored): 6

| case | correct | got | before check | quotes | unsourced numbers |
|---|---|---|---|---|---|
| n01 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/2 |  |
| n02 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/4 |  |
| n03 | Holds up | ✓ Holds up | Holds up | 1/1 |  |
| n04 | Holds up | ✓ Holds up | Holds up | 2/2 |  |
| n05 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/3 | 36 |
| n06 | Holds up | ✓ Holds up | Holds up | 3/3 |  |
| n07 | Holds up | ✓ Holds up | Holds up | 1/1 |  |
| n08 | Holds up | ✓ Holds up | Holds up | 1/2 | 7.01, 5.40, 1.78, 41 |
| p01L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/2 |  |
| p01R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 1/4 | 9.3%, 1119768, 327.6, 100000, 362.9, 22.5 |
| p02L | Doesn't hold up | ✗ Unproven | Doesn't hold up | 0/2 | 350, 325, 500, 312, 285 |
| p02R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 |  |
| p03L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 |  |
| p03R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/4 | 8870, 97% |
| p04L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/4 | 7.7 |
| p04R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/3 |  |
| p05L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/7 | 20.5 |
| p05R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 1/2 | 2, 1194764, 0.93, 95%, 0.85, 1.01 |
| p06L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/6 | 7.01, 4.2, 1.9 |
| p06R | Doesn't hold up | ✗ Unproven | Doesn't hold up | 0/2 | 1634, 2258, 1084, 167 |
| p07L | Holds up | ✓ Holds up | Holds up | 2/3 | 2255, 2126 |
| p07R | Missing context | ✗ Unproven | Holds up | 0/2 | 4, 275, 1 |
| p08L | Holds up | ✓ Holds up | Holds up | 5/5 |  |
| p08R | Holds up | ✓ Holds up | Holds up | 2/2 |  |
| p09L | Holds up | ✓ Holds up | Holds up | 2/5 | 967, 17.2%, 9.3% |
| p09R | Holds up | ✓ Holds up | Holds up | 1/2 |  |
| p10L | Holds up | ✓ Holds up | Holds up | 3/3 |  |
| p10R | Holds up | ✗ Unproven | Holds up | 0/2 | 4.1, 100000 |
| p11L | Holds up | ✓ Holds up | Holds up | 3/4 | 2.32, 1.29 |
| p11R | Holds up | ✓ Holds up | Holds up | 3/3 | 69% |
| p12L | Missing context | ✗ Holds up | Holds up | 2/3 | 3.12 |
| p12R | Missing context | ✓ Missing context | Missing context | 7/7 |  |
| p13L | Missing context | ✗ Unproven | Missing context | 4/5 | 557, 3.9 |
| p13R | Missing context | ✗ Unproven | Missing context | 0/8 | 587, 361, 331, 284, 268, 719, 13.9, 100000, 13, 62 |
| p14L | Missing context | ✗ Unproven | Missing context | 1/4 | 7.1, 18, 0.73, 6.7, 5.8 |
| p14R | Missing context | ✓ Missing context | Missing context | 1/2 |  |
| p15L | Missing context | ✗ Doesn't hold up | Doesn't hold up | 4/5 |  |
| p15R | Missing context | ✗ Holds up | Holds up | 3/3 |  |
| p16L | Missing context | ✓ Missing context | Missing context | 3/5 | 150.9, 130.4, 142.9 |
| p16R | Missing context | ✓ Missing context | Missing context | 6/6 |  |
| p17L | Unproven | ✓ Unproven | Unproven | 1/2 | 0.7, 0.3 |
| p17R | Unproven | ✓ Unproven | Unproven | 0/4 | 15, 1.4, 0.9, 15, 1.3, 3.7 |
| p18L | Unproven | ✓ Unproven | Unproven | 2/3 |  |
| p18R | Unproven | ✓ Unproven | Unproven | 4/4 |  |
| p19L | Unproven | ✓ Unproven | Unproven | 2/3 |  |
| p19R | Unproven | ✗ Doesn't hold up | Doesn't hold up | 1/4 | 600, 342183, 0.91, 0.65, 60 |
| v01 | Values | ✓ Values | Values | 0/0 |  |
| v02 | Values | ✓ Values | Values | 0/0 |  |
| v03 | Values | ✓ Values | Values | 0/0 |  |
| v04 | Values | ✓ Values | Values | 0/0 |  |

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

### v3 · claude-opus-5-5
- Right verdict: **94%** (16 of 17; 95% range 73% to 99%)
- Before the evidence check: 100%
- False "Doesn't hold up": 0
- Quotes verified: 91% · numbers all sourced: 53%
- By side: left 100% of 7 · right 86% of 7 · neutral 100% of 3
- Mirror pairs judged unevenly: 1 of 6 (p03)
- Cost: $8.71 total, $0.513 a claim (range $0.218-$1.439)
- Time: median 83s a claim · searches 113
- Errors (not scored): 0

| case | correct | got | before check | quotes | unsourced numbers |
|---|---|---|---|---|---|
| n01 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 5/5 | 180 |
| n02 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 7/7 |  |
| n05 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/3 |  |
| p01L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 5/5 |  |
| p01R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 6/6 |  |
| p02L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 | 1000, 1000 |
| p02R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 7/7 |  |
| p03L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 | 50 |
| p03R | Doesn't hold up | ✗ Unproven | Doesn't hold up | 1/3 | 16, 98708, 99000, 95%, 1.8, 60%, 249740, 95% |
| p04L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 5/5 |  |
| p04R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 6/6 |  |
| p05L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 5/5 |  |
| p05R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 1/2 | 6517, 0.93, 95%, 0.85, 1.02 |
| p06L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 5/5 | 30, 1654, 1143 |
| p06R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/3 |  |
| p15L | Missing context | ✓ Missing context | Missing context | 6/6 | 34170, 0.1% |
| p19R | Unproven | ✓ Unproven | Unproven | 2/3 | 2 |

### v5 · gemini-3.8-flash
- Right verdict: **86%** (43 of 50; 95% range 74% to 93%)
- Before the evidence check: 90%
- False "Doesn't hold up": 1
- Quotes verified: 89% · numbers all sourced: 78%
- By side: left 84% of 19 · right 79% of 19 · neutral 100% of 12
- Mirror pairs judged unevenly: 5 of 19 (p07, p12, p13, p14, p19)
- Cost: $9.15 total, $0.183 a claim (range $0.003-$0.604)
- Time: median 59s a claim · searches 498
- Errors (not scored): 0

| case | correct | got | before check | quotes | unsourced numbers |
|---|---|---|---|---|---|
| n01 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/2 |  |
| n02 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 |  |
| n03 | Holds up | ✓ Holds up | Holds up | 1/1 |  |
| n04 | Holds up | ✓ Holds up | Holds up | 2/2 |  |
| n05 | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/3 |  |
| n06 | Holds up | ✓ Holds up | Holds up | 3/3 |  |
| n07 | Holds up | ✓ Holds up | Holds up | 1/1 |  |
| n08 | Holds up | ✓ Holds up | Holds up | 1/2 | 7.01, 5.40, 1.78, 41 |
| p01L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/2 |  |
| p01R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/4 | 9.3% |
| p02L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/2 |  |
| p02R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 |  |
| p03L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 |  |
| p03R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/4 | 8870, 97% |
| p04L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 4/4 |  |
| p04R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 3/3 |  |
| p05L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 6/7 | 20.5 |
| p05R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 1/2 | 2, 1194764, 0.93, 95%, 0.85, 1.01 |
| p06L | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 5/6 | 7.01 |
| p06R | Doesn't hold up | ✓ Doesn't hold up | Doesn't hold up | 2/2 |  |
| p07L | Holds up | ✓ Holds up | Holds up | 3/3 |  |
| p07R | Missing context | ✗ Holds up | Holds up | 2/2 |  |
| p08L | Holds up | ✓ Holds up | Holds up | 5/5 |  |
| p08R | Holds up | ✓ Holds up | Holds up | 2/2 |  |
| p09L | Holds up | ✓ Holds up | Holds up | 5/5 |  |
| p09R | Holds up | ✓ Holds up | Holds up | 2/2 |  |
| p10L | Holds up | ✓ Holds up | Holds up | 3/3 |  |
| p10R | Holds up | ✓ Holds up | Holds up | 2/2 |  |
| p11L | Holds up | ✓ Holds up | Holds up | 4/4 |  |
| p11R | Holds up | ✓ Holds up | Holds up | 3/3 | 69% |
| p12L | Missing context | ✗ Holds up | Holds up | 3/3 |  |
| p12R | Missing context | ✓ Missing context | Missing context | 7/7 |  |
| p13L | Missing context | ✓ Missing context | Missing context | 5/5 | 3.9 |
| p13R | Missing context | ✗ Unproven | Missing context | 0/8 | 587, 361, 331, 284, 268, 719, 13.9, 100000, 13, 62 |
| p14L | Missing context | ✗ Unproven | Missing context | 1/4 | 7.1, 18, 0.73, 6.7, 5.8 |
| p14R | Missing context | ✓ Missing context | Missing context | 1/2 |  |
| p15L | Missing context | ✗ Doesn't hold up | Doesn't hold up | 5/5 |  |
| p15R | Missing context | ✗ Holds up | Holds up | 3/3 |  |
| p16L | Missing context | ✓ Missing context | Missing context | 5/5 |  |
| p16R | Missing context | ✓ Missing context | Missing context | 6/6 |  |
| p17L | Unproven | ✓ Unproven | Unproven | 2/2 |  |
| p17R | Unproven | ✓ Unproven | Unproven | 4/4 |  |
| p18L | Unproven | ✓ Unproven | Unproven | 3/3 |  |
| p18R | Unproven | ✓ Unproven | Unproven | 4/4 |  |
| p19L | Unproven | ✓ Unproven | Unproven | 2/3 |  |
| p19R | Unproven | ✗ Doesn't hold up | Doesn't hold up | 1/4 | 600, 342183, 0.91, 0.65, 60 |
| v01 | Values | ✓ Values | Values | 0/0 |  |
| v02 | Values | ✓ Values | Values | 0/0 |  |
| v03 | Values | ✓ Values | Values | 0/0 |  |
| v04 | Values | ✓ Values | Values | 0/0 |  |

### As the product runs it: Gemini (v5) checks everything, Opus re-checks its Doesn't hold up
- Right verdict: **86%** of 50 (95% range 74% to 93%) · false "Doesn't hold up": 0
- Second opinions needed: 17 · their cost $8.71
- By side: left 84% of 19 · neutral 100% of 12 · right 79% of 19

### As the product runs it: Gemini (v1) checks everything, Opus re-checks its Doesn't hold up
- Right verdict: **78%** of 50 (95% range 65% to 87%) · false "Doesn't hold up": 0
- Second opinions needed: 15 · their cost $8.71
- By side: left 74% of 19 · neutral 100% of 12 · right 68% of 19

### Two-model system: Gemini (v1) decides, Claude (baseline) second opinion
- Right verdict: **83%** of 6 · false "Doesn't hold up": 0

### Two-model system: Claude (baseline) decides, Gemini (v1) second opinion
- Right verdict: **100%** of 6 · false "Doesn't hold up": 0

### Two-model system: Gemini (v1) decides, Claude (v2) second opinion
- Right verdict: **100%** of 5 · false "Doesn't hold up": 0

### Two-model system: Claude (v2) decides, Gemini (v1) second opinion
- Right verdict: **100%** of 5 · false "Doesn't hold up": 0
