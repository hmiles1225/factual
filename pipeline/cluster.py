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

# Today has four sections: U.S. politics (and U.S. policy abroad), and three topics that get
# politicized: environment, science and health (Heston's call, 2026-10-18). A story takes the topic
# whose examples its meaning is closest to, if that beats the non-topic examples by TOPIC_MARGIN.
# Politics examples tuned by eye on the 2026-10-18 scan: celebrity trials, foreign wars and disasters
# fall out; Senate debates, rallies, sanctions and agency actions stay in.
POLITICS = [
    "U.S. Congress passes a bill; senators and representatives vote", "The White House and the president announce a policy",
    "U.S. election campaign, candidates, voters, polls and midterms", "A federal court rules on a Trump administration policy or a state law",
    "Federal agency, Justice Department, FBI or Pentagon action on policy", "U.S. foreign policy: sanctions, tariffs, military aid, treaties",
    "Government spending, the budget, taxes and the national debt", "Immigration and border policy decided by the U.S. government",
    "Republicans and Democrats clash over legislation", "A White House official or cabinet member resigns or is fired",
    "The president holds a campaign rally for midterm candidates", "Congressional or Senate candidates debate before the election",
]
ENVIRONMENT = [
    "Climate change policy: emissions rules, the Paris agreement, carbon pollution",
    "The EPA changes environmental rules on air, water or chemical pollution",
    "Oil and gas drilling, pipelines, coal and fossil fuel policy",
    "Renewable energy, electric vehicles, solar and wind power subsidies",
    "Public lands, national parks, endangered species and conservation",
    "Scientists link extreme heat, floods or drought to climate change",
]
SCIENCE = [
    "NASA, space missions and rocket launches",
    "Federal science funding, research grants and the National Science Foundation",
    "Scientists publish a study in a journal; new research findings",
    "Gene editing, genetics, evolution and scientific consensus",
    "Government regulation of artificial intelligence and its risks",
    "Nuclear power, fusion and energy research",
]
HEALTH = [
    "Vaccines: safety, schedules, mandates and vaccine advisers",
    "The FDA approves or restricts a drug; the CDC issues health guidance",
    "The health secretary and HHS change federal health policy",
    "Abortion, reproductive health and access to care",
    "Medicaid, Medicare, health insurance and prescription drug prices",
    "Disease outbreaks: measles, flu, COVID and the public health response",
    "Fluoride, food dyes, nutrition and chronic disease policy",
]
TOPICS = {"politics": POLITICS, "environment": ENVIRONMENT, "science": SCIENCE, "health": HEALTH}
NOT_POLITICS = [
    "A shooting, crime or police investigation in a city", "A wildfire, storm, earthquake or accident kills people",
    "Sports: a game, a team, a player, a championship", "Business, company earnings, a product launch, technology",
    "Celebrity, entertainment, movies and music", "Religion: the Pope and the Vatican",
    "A foreign country's internal politics, protests or election abroad", "Weather and travel",
    "A celebrity, athlete or murderer on trial; a judge sentences a defendant",
    "A celebrity's looks, body, diet, weight loss or fitness routine",
    "A foreign separatist movement or referendum in Canada or Europe", "A war between other countries: battlefield news, drones, front lines",
]
TOPIC_MARGIN = 0.01
# Politics moves by the day; environment, science and health move by the week. Politics is grouped from
# the last RECENT_HOURS of articles; the slow topics from the whole pool (fetch.py keeps POOL_DAYS).
SLOW_TOPICS = ("environment", "science", "health")
RECENT_HOURS = 48
POOL_DAYS = 7
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


ALLSIDES_SIDE = {"Left": "left", "Lean Left": "left", "Center": "center", "Lean Right": "right", "Right": "right"}


def side_of(feed):
    """Pew's audience data first. An outlet Pew did not survey is placed from its published AllSides
    rating, if it has one (feeds.json says which). Never set by hand."""
    pew = feed.get("pew")
    if pew:
        share = pew["rep"] / (pew["rep"] + pew["dem"])
        return "left" if share < LEFT_BELOW else "right" if share > RIGHT_ABOVE else "center"
    rating = (feed.get("allsides") or {}).get("rating")
    return ALLSIDES_SIDE.get(rating, "unplaced")


def is_opinion(art):
    return bool(OPINION_PATH.search(art["url"]) or OPINION_TITLE.search(art["title"]))


def text_for(art):
    summary = art.get("summary") or ""
    return f"{art['title']}. {summary[:300]}"


def hours(art):
    p = art.get("published")
    return datetime.fromisoformat(p).timestamp() / 3600 if p else None


def group(vectors, times, window=None):
    """Average-linkage agglomerative clustering on cosine similarity.

    vectors are L2-normalised, so the dot product is the cosine. Returns a list of
    index lists. n is a few hundred per run, so the O(n^2) matrix is cheap.
    """
    n = len(vectors)
    sim = vectors @ vectors.T
    t = np.array([np.nan if x is None else x for x in times])
    gap = np.abs(t[:, None] - t[None, :])
    sim[np.nan_to_num(gap, nan=0.0) > (window or WINDOW_HOURS)] = -1.0
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
    unit = lambda a: a / np.linalg.norm(a, axis=1, keepdims=True)
    protos = {t: unit(np.array(list(model.embed(ex)), dtype=np.float32)) for t, ex in TOPICS.items()}
    other = unit(np.array(list(model.embed(NOT_POLITICS)), dtype=np.float32))

    def sub(ids, window):  # cluster a subset; return clusters as indices into news
        return [[ids[j] for j in m] for m in group(vectors[ids], [hours(news[i]) for i in ids], window)] if ids else []

    now_h = datetime.fromisoformat(scan["fetched_at"]).timestamp() / 3600
    dated = [i for i, a in enumerate(news) if hours(a) is not None]
    recent = [i for i in dated if now_h - hours(news[i]) <= RECENT_HOURS]
    # The week's environment, science and health articles, sorted one by one, then grouped over the pool.
    base = (vectors @ other.T).max(axis=1)
    art = {t: (vectors @ m.T).max(axis=1) - base for t, m in protos.items()}
    top_topic = lambda i: max(art, key=lambda t: art[t][i])
    slow = [i for i in dated if top_topic(i) in SLOW_TOPICS and art[top_topic(i)][i] > 0]
    # Week clusters go first, so a story carried over from the last scan keeps its id in its week form.
    clusters = [(m, "week") for m in sub(slow, POOL_DAYS * 24)] + [(m, "day") for m in sub(recent, WINDOW_HOURS)]

    feeds = json.loads((ROOT / "pipeline/feeds.json").read_text())
    side = {f["source"]: side_of(f) for f in feeds["feeds"]}
    # Audience lean, 0 = all Democratic users, 1 = all Republican users (Pew), for the spectrum charts.
    lean = {f["source"]: round(f["pew"]["rep"] / (f["pew"]["rep"] + f["pew"]["dem"]), 3) for f in feeds["feeds"] if f.get("pew")}
    pew = {f["source"]: {"rep": f["pew"]["rep"], "dem": f["pew"]["dem"]} for f in feeds["feeds"] if f.get("pew")}
    allsides = {f["source"]: f["allsides"]["rating"] for f in feeds["feeds"] if not f.get("pew") and (f.get("allsides") or {}).get("rating") in ALLSIDES_SIDE}
    working = {f["source"] for f in scan.get("feeds", []) if f["ok"]}
    roster = {k: sorted(src for src in working if side.get(src, "unplaced") == k) for k in (*SIDES, "unplaced")}

    prev_sid, used_sids = previous_ids(), set()
    stories = []
    for idx, span in clusters:
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
            "span": span,
            "working_title": lead["title"],
            "outlets": len(sources),
            "sources": sources,
            "coverage": coverage,
            "balance_score": round(sum(shares) / len(SIDES), 4),
            "articles": [{"source": a["source"], "title": a["title"], "url": a["url"], "published": a["published"]}
                         for a in sorted(arts, key=lambda a: a["published"] or "")],
        })
    titles = unit(np.array(list(model.embed([" ".join(a["title"] for a in st["articles"][:6]) for st in stories])), dtype=np.float32)) if stories else np.zeros((0, 384))
    for st, v in zip(stories, titles):
        base = float((other @ v).max())
        scores = {t: float((m @ v).max()) - base for t, m in protos.items()}
        best = max(scores, key=scores.get)
        st["topic_scores"] = {t: round(x, 3) for t, x in scores.items()}
        st["politics_score"] = round(scores["politics"], 3)
        st["topic"] = best if scores[best] > TOPIC_MARGIN else "other"
    # Slow topics come from the week pass; politics and the rest from the day pass. A day story on a slow
    # topic is kept only if the week pass did not already group its articles.
    week_urls = {a["url"] for st in stories if st["span"] == "week" and st["topic"] in SLOW_TOPICS for a in st["articles"]}
    stories = [st for st in stories if (st["span"] == "week" and st["topic"] in SLOW_TOPICS)
               or (st["span"] == "day" and not (st["topic"] in SLOW_TOPICS and any(a["url"] in week_urls for a in st["articles"])))]
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
        "feeds": [{**f, "side": side.get(f["source"], "unplaced"), "lean": lean.get(f["source"]), "pew": pew.get(f["source"]),
                   "placed_by": "Pew" if f["source"] in pew else "AllSides" if allsides.get(f["source"]) else None,
                   "allsides": allsides.get(f["source"])}
                  for f in scan.get("feeds", [])],
        "method": {"model": MODEL, "threshold": THRESHOLD, "window_hours": WINDOW_HOURS, "linkage": "average", "related": RELATED,
                   "topics": {"politics": "U.S. politics and U.S. policy abroad", "environment": "Environment and climate",
                              "science": "Science", "health": "Health"}, "topic_margin": TOPIC_MARGIN},
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
    for t in TOPICS:
        print(f"  {t}: {sum(st['topic'] == t for st in stories)} of {len(stories)} stories")
        for s in [s for s in stories if s["related_to"] is None and s["topic"] == t][:8]:
            c = " ".join(f"{k[0].upper()}{len(s['coverage'][k])}/{len(roster[k])}" for k in SIDES)
            print(f"    {s['balance_score']:.2f}  {c}  {s['working_title'][:66]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
