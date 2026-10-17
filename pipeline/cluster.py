"""Stage 2: group articles about the same event into stories, by meaning.

Each article (headline + start of its summary) becomes an embedding from a small
local model, so "Pope Leo discharged" and "Pope leaves hospital after surgery"
land together even with few shared words. No API key, no per-run cost, and the
same input always gives the same groups.

Grouping is average-linkage: a story only absorbs an article that is close to
the story as a whole, not just to one member. That stops chains where A~B and
B~C drag unrelated A and C into one story. Merging two different events is the
worse error for a fact-check app, so the threshold leans strict.

Rules that hold whatever the model:
- A story needs at least two different outlets.
- Opinion pieces never join news stories (see is_opinion).
- Articles more than WINDOW_HOURS apart are never grouped.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

ROOT = Path(__file__).resolve().parent.parent
MODEL = "BAAI/bge-small-en-v1.5"
THRESHOLD = 0.80     # minimum average cosine similarity to join a story
WINDOW_HOURS = 72

# URL path segments and title prefixes that mark opinion, analysis or columns.
OPINION_PATH = re.compile(r"/(opinion|opinions|commentary|columns?|columnists?|editorials?|op-?eds?|analysis|perspective)(/|-)", re.I)
OPINION_TITLE = re.compile(r"^(opinion|analysis|commentary|editorial|column|op-ed)\s*[:|]", re.I)


def is_opinion(art):
    return bool(OPINION_PATH.search(art["url"]) or OPINION_TITLE.search(art["title"]))


def text_for(art):
    summary = art.get("summary") or ""
    return f"{art['title']}. {summary[:300]}"


def hours(art):
    p = art.get("published")
    return datetime.fromisoformat(p).timestamp() / 3600 if p else None


def group(vectors, times):
    """Average-linkage agglomerative clustering on cosine similarity.

    vectors are L2-normalised, so the dot product is the cosine. Returns a list of
    index lists. n is a few hundred per run, so the O(n^2) matrix is cheap.
    """
    n = len(vectors)
    sim = vectors @ vectors.T
    t = np.array([np.nan if x is None else x for x in times])
    gap = np.abs(t[:, None] - t[None, :])
    sim[np.nan_to_num(gap, nan=0.0) > WINDOW_HOURS] = -1.0
    np.fill_diagonal(sim, -1.0)

    members = {i: [i] for i in range(n)}
    # Sum of pairwise similarities between clusters, so the average is sum / (|a| * |b|).
    total = sim.copy()
    active = np.ones(n, dtype=bool)
    sizes = np.ones(n)
    while True:
        avg = total / np.outer(sizes, sizes)
        avg[~active, :] = -np.inf
        avg[:, ~active] = -np.inf
        np.fill_diagonal(avg, -np.inf)
        a, b = np.unravel_index(np.argmax(avg), avg.shape)
        if avg[a, b] < THRESHOLD:
            break
        # A pair that the time window forbids must not slip in through averaging.
        if (sim[np.ix_(members[a], members[b])] == -1.0).any():
            total[a, b] = total[b, a] = -np.inf
            continue
        members[a] += members.pop(b)
        total[a, :] += total[b, :]
        total[:, a] += total[:, b]
        sizes[a] += sizes[b]
        active[b] = False
    return [m for i, m in members.items() if active[i]]


def main():
    articles = json.loads((ROOT / "data/articles.json").read_text())["articles"]
    news = [a for a in articles if not is_opinion(a)]
    opinion = len(articles) - len(news)

    model = TextEmbedding(MODEL)
    vectors = np.array(list(model.embed([text_for(a) for a in news])), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    clusters = group(vectors, [hours(a) for a in news])

    stories = []
    for idx in clusters:
        arts = [news[i] for i in idx]
        sources = sorted({a["source"] for a in arts})
        if len(sources) < 2:
            continue
        # Working title: the article closest to the story's centre of meaning.
        centre = vectors[idx].mean(axis=0)
        lead = arts[int(np.argmax(vectors[idx] @ centre))]
        stories.append({
            "working_title": lead["title"],
            "outlets": len(sources),
            "sources": sources,
            "articles": [{"source": a["source"], "title": a["title"], "url": a["url"], "published": a["published"]}
                         for a in sorted(arts, key=lambda a: a["published"] or "")],
        })
    stories.sort(key=lambda s: (s["outlets"], len(s["articles"])), reverse=True)
    out = {
        "method": {"model": MODEL, "threshold": THRESHOLD, "window_hours": WINDOW_HOURS, "linkage": "average"},
        "count": len(stories),
        "opinion_excluded": opinion,
        "stories": stories,
    }
    (ROOT / "data/stories.json").write_text(json.dumps(out, indent=1))
    print(f"{len(stories)} stories covered by 2+ outlets -> data/stories.json ({opinion} opinion pieces kept out)\n")
    for s in stories[:10]:
        print(f"  {s['outlets']:>2} outlets  {s['working_title'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
