# fACTUAL eval results

Written by the `eval` workflow on `main`. Each folder under `claim-check/` is one checker:
`baseline` is Claude Opus 5.5, `v1` is Gemini 3.8 Flash. `results.jsonl` holds one graded row per
claim, `traces/` the full exchange and evidence check for each, `errors.jsonl` the attempts that
produced nothing scorable, and `summary.md` the headline numbers.
