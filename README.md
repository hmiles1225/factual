# fACTUAL scan

The pipeline behind fACTUAL. Its method is public so anyone can check it.

## Stages

1. **Fetch** (`pipeline/fetch.py`). Reads every feed in `pipeline/feeds.json` and prints a line per
   feed, so a blocked feed shows up instead of going missing. If fewer than two thirds of the
   feeds work, the scan fails and the site keeps its last good data.
2. **Group** (`pipeline/cluster.py`). Groups articles about the same event by meaning, using a
   small local embedding model (`BAAI/bge-small-en-v1.5`). A story needs two or more outlets.
   Opinion pieces never join news stories. Articles more than 72 hours apart are never grouped.
   The model, threshold and window are written into every `stories.json`.

Checking (stage 3) is not built yet. The verdict rules it will follow are in `method/verdicts.md`. How outlets are
balanced left, center and right is in `method/balance.md`.

## Privacy

The site sets no cookies and loads nothing from other domains. A reader's ZIP code, when the app asks
for one, stays on their device: the app downloads statewide race and ad data and filters it locally.
No server ever receives it.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pipeline/fetch.py && .venv/bin/python pipeline/cluster.py
```

## The site

`web/` is the front end: static HTML, CSS and JS that read `data/stories.json`. No build step.
Fonts are self-hosted (SIL Open Font License), so readers' browsers never call Google.
Caching rules are in `web/.htaccess`.

## Deploy

`.github/workflows/scan.yml` runs both stages every hour and on every push to `main`, then uploads
`web/` and `data/*.json` over FTPS to https://hestonmiles.com/factual/.
