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

Ranking gives left, center and right equal weight. Each outlet's side is computed from
Pew's audience numbers in feeds.json (never set by hand). A story's score is the mean,
over the three sides, of the share of that side's working outlets that covered it, so a
side with more outlets in the list gets no more say than a side with fewer.
"""
import hashlib
import json
from collections import Counter
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
# Audience lean = Republican users / (Republican + Democratic users), from Pew. This treats
# the two parties as equal in size. Below LEFT_BELOW is left, above RIGHT_ABOVE is right.
LEFT_BELOW, RIGHT_ABOVE = 0.40, 0.60
# Stories this close (average similarity) are different angles on one event. They stay
# separate stories, but the lower-ranked one is folded under the higher one on Today, so
# one event never takes two of the five slots. Measured 2026-10-17: every pair above this
# was related (one shooting, one sanctions waiver); no single merge threshold kept
# distinct stories apart, so they are linked rather than merged.
RELATED = 0.74

# Today covers U.S. politics and U.S. policy abroad (Heston's call, 2026-10-18). A story is political
# when its meaning is closer to these examples than to the non-political ones, by POLITICS_MARGIN.
# Tuned by eye on the 2026-10-18 scan: celebrity trials, foreign wars and disasters fall out; Senate
# debates, rallies, sanctions and agency actions stay in.
POLITICS = [
    "U.S. Congress passes a bill; senators and representatives vote", "The White House and the president announce a policy",
    "U.S. election campaign, candidates, voters, polls and midterms", "A federal court rules on a Trump administration policy or a state law",
    "Federal agency, Justice Department, FBI or Pentagon action on policy", "U.S. foreign policy: sanctions, tariffs, military aid, treaties",
    "Government spending, the budget, taxes and the national debt", "Immigration and border policy decided by the U.S. government",
    "Republicans and Democrats clash over legislation", "A White House official or cabinet member resigns or is fired",
    "The president holds a campaign rally for midterm candidates", "Congressional or Senate candidates debate before the election",
]
NOT_POLITICS = [
    "A shooting, crime or police investigation in a city", "A wildfire, storm, earthquake or accident kills people",
    "Sports: a game, a team, a player, a championship", "Business, company earnings, a product launch, technology",
    "Celebrity, entertainment, movies and music", "Religion: the Pope and the Vatican", "Health and science research findings",
    "A foreign country's internal politics, protests or election abroad", "Weather and travel",
    "A celebrity, athlete or murderer on trial; a judge sentences a defendant",
    "A foreign separatist movement or referendum in Canada or Europe", "A war between other countries: battlefield news, drones, front lines",
]
POLITICS_MARGIN = 0.01
SIDES = ("left", "center", "right")

# URL path segments and title prefixes that mark opinion, analysis or columns.
OPINION_PATH = re.compile(r"/(opinion|opinions|commentary|columns?|columnists?|editorials?|op-?eds?|analysis|perspective)(/|-)", re.I)
OPINION_TITLE = re.compile(r"^(opinion|analysis|commentary|editorial|column|op-ed)\s*[:|]", re.I)


LIVE_STORIES = "https://hestonmiles.com/factual/data/stories.json"


def previous_ids():
    """article url -> story id from the scan now on the site. Empty if it can't be read."""
    import ssl
    import urllib.request
    try:
        ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if Path("/etc/ssl/cert.pem").exists() else ssl.create_default_context()
        req = urllib.request.Request(LIVE_STORIES, headers={"User-Agent": "fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)"})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            prev = json.loads(r.read())
        return {a["url"]: st["sid"] for st in prev.get("stories", []) if st.get("sid") for a in st["articles"]}
    except Exception as e:
        print(f"  previous scan not readable ({e}); new ids")
        return {}


def side_of(feed):
    pew = feed.get("pew")
    if not pew:
        return "unplaced"
    share = pew["rep"] / (pew["rep"] + pew["dem"])
    return "left" if share < LEFT_BELOW else "right" if share > RIGHT_ABOVE else "center"


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
    scan = json.loads((ROOT / "data/articles.json").read_text())
    articles = scan["articles"]
    news = [a for a in articles if not is_opinion(a)]
    opinion = len(articles) - len(news)

    model = TextEmbedding(MODEL)
    vectors = np.array(list(model.embed([text_for(a) for a in news])), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    clusters = group(vectors, [hours(a) for a in news])

    feeds = json.loads((ROOT / "pipeline/feeds.json").read_text())
    side = {f["source"]: side_of(f) for f in feeds["feeds"]}
    working = {f["source"] for f in scan.get("feeds", []) if f["ok"]}
    roster = {k: sorted(src for src in working if side.get(src, "unplaced") == k) for k in (*SIDES, "unplaced")}

    prev_sid, used_sids = previous_ids(), set()
    stories = []
    for idx in clusters:
        arts = [news[i] for i in idx]
        sources = sorted({a["source"] for a in arts})
        if len(sources) < 2:
            continue
        # Working title: the article closest to the story's centre of meaning.
        centre = vectors[idx].mean(axis=0)
        lead = arts[int(np.argmax(vectors[idx] @ centre))]
        coverage = {k: [src for src in sources if side.get(src, "unplaced") == k] for k in (*SIDES, "unplaced")}
        shares = [len(coverage[k]) / len(roster[k]) if roster[k] else 0.0 for k in SIDES]
        # A story keeps its id from the last scan when most of its articles were in that story, so
        # links keep working and its summary is not paid for again as old articles age out.
        first = min(arts, key=lambda a: (a["published"] or "", a["url"]))
        votes = Counter(prev_sid[a["url"]] for a in arts if a["url"] in prev_sid)
        carried = next((sid for sid, n in votes.most_common(1) if n >= max(2, 0.3 * len(arts)) and sid not in used_sids), None)
        sid = carried or hashlib.sha1(first["url"].encode()).hexdigest()[:10]
        used_sids.add(sid)
        stories.append({
            "_idx": idx,
            "sid": sid,
            "working_title": lead["title"],
            "outlets": len(sources),
            "sources": sources,
            "coverage": coverage,
            "balance_score": round(sum(shares) / len(SIDES), 4),
            "articles": [{"source": a["source"], "title": a["title"], "url": a["url"], "published": a["published"]}
                         for a in sorted(arts, key=lambda a: a["published"] or "")],
        })
    unit = lambda a: a / np.linalg.norm(a, axis=1, keepdims=True)
    pol = unit(np.array(list(model.embed(POLITICS)), dtype=np.float32))
    other = unit(np.array(list(model.embed(NOT_POLITICS)), dtype=np.float32))
    titles = unit(np.array(list(model.embed([" ".join(a["title"] for a in st["articles"][:6]) for st in stories])), dtype=np.float32)) if stories else np.zeros((0, 384))
    for st, v in zip(stories, titles):
        score = float((pol @ v).max() - (other @ v).max())
        st["politics_score"] = round(score, 3)
        st["topic"] = "politics" if score > POLITICS_MARGIN else "other"
    stories.sort(key=lambda s: (s["balance_score"], s["outlets"], len(s["articles"])), reverse=True)
    for n, st in enumerate(stories):
        st["id"] = n
        st["related"] = []
        st["related_to"] = None
        for earlier in stories[:n]:
            if earlier["related_to"] is None and float((vectors[st["_idx"]] @ vectors[earlier["_idx"]].T).mean()) >= RELATED:
                st["related_to"] = earlier["id"]
                earlier["related"].append(n)
                break
    for st in stories:
        del st["_idx"]
    out = {
        "scanned_at": scan["fetched_at"],
        "articles_scanned": len(articles),
        "feeds": [{**f, "side": side.get(f["source"], "unplaced")} for f in scan.get("feeds", [])],
        "method": {"model": MODEL, "threshold": THRESHOLD, "window_hours": WINDOW_HOURS, "linkage": "average", "related": RELATED,
                   "topic": "U.S. politics and U.S. policy abroad", "politics_margin": POLITICS_MARGIN},
        "placement": {"source": feeds["placement_source"], "left_below": LEFT_BELOW, "right_above": RIGHT_ABOVE,
                      "measure": "Republican users / (Republican + Democratic users)"},
        "roster": roster,
        "count": len(stories),
        "opinion_excluded": opinion,
        "stories": stories,
    }
    (ROOT / "data/stories.json").write_text(json.dumps(out, indent=1))
    print(f"{len(stories)} stories covered by 2+ outlets -> data/stories.json ({opinion} opinion pieces kept out)\n")
    print("  roster: " + " · ".join(f"{k} {len(roster[k])}" for k in (*SIDES, "unplaced")) + "\n")
    print(f"  politics: {sum(st['topic'] == 'politics' for st in stories)} of {len(stories)} stories\n")
    for s in [s for s in stories if s["related_to"] is None and s["topic"] == "politics"][:8]:
        c = " ".join(f"{k[0].upper()}{len(s['coverage'][k])}/{len(roster[k])}" for k in SIDES)
        print(f"  {s['balance_score']:.2f}  {c}  {s['working_title'][:66]}")
        for r in s["related"]:
            print(f"        related: {stories[r]['working_title'][:66]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
