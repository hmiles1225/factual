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

# Today's sections: U.S. politics and the topics that get politicized (Heston's calls, 2026-10-18 and -19).
# A story takes the topic whose examples its meaning is closest to, if that beats the non-topic examples by
# TOPIC_MARGIN. Elections and immigration have their own sections, so their examples left POLITICS.
# Politics examples tuned by eye on the 2026-10-18 scan: celebrity trials, foreign wars and disasters
# fall out; Senate debates, sanctions and agency actions stay in.
POLITICS = [
    "U.S. Congress passes a bill; senators and representatives vote", "The White House and the president announce a policy",
    "A federal court rules on a Trump administration policy or a state law",
    "Federal agency, Justice Department, FBI or Pentagon action on policy", "U.S. foreign policy: sanctions, tariffs, military aid, treaties",
    "Government spending, the budget, taxes and the national debt",
    "Republicans and Democrats clash over legislation", "A White House official or cabinet member resigns or is fired",
    "The vice president holds a town hall or gives a major interview",
]
ELECTIONS = [
    "U.S. election campaign, candidates, voters, polls and midterms",
    "The president holds a campaign rally for midterm candidates",
    "Congressional or Senate candidates debate before the election",
    "Early voting, mail ballots, voter ID and how elections are run",
    "Redistricting, gerrymandering and lawsuits over election rules",
    "A poll shows a tight race for governor, Senate or the House",
    "A candidate drops out of the race or ends a campaign after a scandal",
    "A Senate or House candidate's remarks at a campaign event draw criticism",
]
IMMIGRATION = [
    "Immigration and border policy decided by the U.S. government",
    "ICE arrests, deportations and immigration raids",
    "Asylum seekers, refugees and the southern border",
    "Birthright citizenship, visas, green cards and denaturalization",
    "Sanctuary cities and states clash with federal immigration enforcement",
    "Temporary protected status ends for immigrants from a country",
]
CRIME = [
    "Crime rates, policing and public safety in American cities",
    "A shooting or killing in a U.S. city and the police investigation",
    "Prosecutors, district attorneys, bail and criminal justice reform",
    "Gun laws, gun violence and the Second Amendment",
    "Prisons, sentencing, pardons and the death penalty",
    "The Justice Department charges or drops a case against a public figure",
]
ECONOMY = [
    "Inflation, consumer prices and the cost of living",
    "The monthly jobs report: unemployment, hiring and wages",
    "The Federal Reserve raises or cuts interest rates",
    "Tariffs and trade policy raise prices for businesses and shoppers",
    "Gas prices, housing costs and mortgage rates",
    "Recession fears, economic growth and the stock market",
    "Taxes, wages and the federal budget's effect on households",
]
ENVIRONMENT = [  # shown as "Energy & environment"
    "Climate change policy: emissions rules, the Paris agreement, carbon pollution",
    "The EPA changes environmental rules on air, water or chemical pollution",
    "Oil and gas drilling, pipelines, coal and fossil fuel policy",
    "Renewable energy, electric vehicles, solar and wind power subsidies",
    "Public lands, national parks, endangered species and conservation",
    "Scientists link extreme heat, floods or drought to climate change",
    "Electricity prices, the power grid and utility bills",
    "OPEC, oil prices and the supply of gasoline",
    "Nuclear power plants and data centers' demand for electricity",
]
TECH = [
    "Artificial intelligence companies, chatbots and AI models",
    "Government regulation of artificial intelligence and its risks",
    "Big Tech antitrust cases, social media and online speech",
    "Data privacy, surveillance and cybersecurity breaches",
    "Chips, semiconductors and technology export controls",
    "A tech company or billionaire announces a deal, stake, investment or giveaway",
    "An OpenAI, Google or Meta employee is accused of spying for a foreign government",
    "Elon Musk and his companies: Tesla, SpaceX, X and xAI",
]
SCIENCE = [
    "NASA, space missions and rocket launches",
    "Federal science funding, research grants and the National Science Foundation",
    "Scientists publish a study in a journal; new research findings",
    "Gene editing, genetics, evolution and scientific consensus",
    "Fusion and physics research",
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
EDUCATION = [
    "Schools, teachers, curriculum and school boards",
    "Student loans, college tuition and higher education",
    "The Education Department and federal school funding",
    "Universities, campus protests and federal research money",
    "School choice, vouchers and charter schools",
    "What schools teach about race, gender and history; book removals",
]
# Abroad, without a U.S. decision at its center (that is Politics: sanctions, aid, an endorsement).
WORLD = [
    "Israel, Gaza and the West Bank: the war, hostages, settlers and ceasefire talks",
    "Russia and Ukraine: battlefield news, drone strikes and peace talks",
    "A foreign country's internal politics, protests, riots or election",
    "China, Taiwan and tensions in Asia",
    "A foreign separatist movement or referendum in Canada or Europe",
    "Iran, its nuclear program and conflict in the Middle East",
]
TOPICS = {"politics": POLITICS, "elections": ELECTIONS, "economy": ECONOMY, "immigration": IMMIGRATION, "crime": CRIME,
          "world": WORLD, "environment": ENVIRONMENT, "health": HEALTH, "tech": TECH, "science": SCIENCE, "education": EDUCATION}
NOT_POLITICS = [
    "An accident, fire or animal attack injures or kills people", "A wildfire, storm, earthquake or accident kills people",
    "Sports: a game, a team, a player, a championship", "Business, company earnings and a product launch",
    "Celebrity, entertainment, movies and music", "Religion: the Pope and the Vatican",
    "Weather and travel",
    "A celebrity or athlete on trial; a judge sentences a celebrity",
    "A celebrity's looks, body, diet, weight loss or fitness routine",
    "A football, basketball or baseball player is ejected, suspended or injured", "College football and basketball games and coaches",
    "A TV news anchor or journalist leaves a network, is suspended or apologizes for a post",
    "A pro team fires its coach or general manager", "An athlete's or celebrity's marriage, divorce or family life",
]
TOPIC_MARGIN = 0.01
# Politics moves by the day; energy and environment, science, health and education move by the week. Politics is grouped from
# the last RECENT_HOURS of articles; the slow topics from the whole pool (fetch.py keeps POOL_DAYS).
SLOW_TOPICS = ("environment", "science", "health", "education")
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
        out = {}
        for st in prev.get("stories", []):
            for a in st.get("articles", []) if st.get("sid") else []:
                out.setdefault(a["url"], set()).add(st["sid"])
        return out
    except Exception as e:
        print(f"  previous scan not readable ({e}); new ids")
        return {}


# The Texas demo edition: election coverage about Texas, from Texas outlets and national ones alike.
# An article is in only when it is about a Texas race, not when it merely mentions Texas and politics. Measured
# 2026-10-20: the old rule (any Texas word, including city names, plus any of "Senate", "Republicans", "vote", or
# an election-topic score above zero, which nearly every political article has) let in 13 of 41 off-topic
# articles: a Temu settlement, a 9/11 plea deal, "Top 1940s Girl Names", "Tyler Austin Harper", the Spurs.
TX_CHALLENGERS = re.compile(r"\b(Talarico|Hinojosa)\b")  # statewide challengers: national outlets cover them for the race
TX_OFFICEHOLDERS = re.compile(r"\b(Paxton|Greg Abbott|Gov\. Abbott|Dan Patrick|Cornyn)\b")  # official acts are not the race
TX_TITLE = re.compile(r"\b(Texas|Texans?)\b")  # in the headline, so a passing mention ("...and Texas") is not enough
CAMPAIGN_TEXT = re.compile(r"\b(elections?|voters?|voting|ballots?|polls?|polling|campaign(s|ing|ed)?|candidates?|candidacy|"
                           r"(Senate|governor'?s?|House|tight|close|statewide) race|race for|bids?|rall(y|ies)|endorse\w*|ads?|"
                           r"debates?|primary|runoff|midterms?|turnout|redistrict\w*|congressional district|nominee)\b", re.I)


def tx_admit(art, from_region):
    """True when an article belongs in the Texas Election section."""
    text = text_for(art)
    if TX_CHALLENGERS.search(text):
        return True
    about_texas = from_region or TX_TITLE.search(art["title"]) or TX_OFFICEHOLDERS.search(text)
    return bool(about_texas and CAMPAIGN_TEXT.search(text))
TX_SID = "tx"  # Texas story ids start with this, so they never collide with a national story's id
# Texas Election is grouped by race, not by event: one story per race, updated through Election Day. First match
# wins, so an article on Paxton's Senate bid is a Senate story even though he is attorney general.
# Races, in this order (first match wins): used to sort Texas articles by race for the numbers (tx_numbers.py).
# Stories are grouped by event, not by race. Names in ballot order (the governor's party first).
TX_RACES = [
    ("senate", "Texas Senate race: Paxton vs. Talarico", re.compile(r"(?<!State )\b(Senate|Paxton|Talarico|Cornyn)\b")),  # not the state Senate
    ("governor", "Texas Governor race: Abbott vs. Hinojosa", re.compile(r"\b(governor|gubernatorial|Abbott|Hinojosa)\b", re.I)),
    ("statewide", "Texas Attorney General and Lieutenant Governor", re.compile(r"\b(attorney general|lieutenant governor|Dan Patrick)\b", re.I)),
    ("house", "Texas House races and redistricting", re.compile(r"\b(redistrict\w*|congressional|district|U\.S\. House)\b", re.I)),
    ("voting", "Voting in Texas: early voting, turnout and rules", re.compile(r"\b(early voting|turnout|ballots?|polling places?|voter rolls?|voter registration|mail-in|election officials?)\b", re.I)),
    ("trail", "On the Texas campaign trail", re.compile(r".")),
]

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


MEDIA_TITLE = re.compile(r"[\u2013\u2014|:-]\s*(video|watch|in pictures|photos?|gallery|live( updates| blog)?|podcast|audio)\s*\)?$|^(watch|video|live( updates)?|photos?|in pictures)\s*[:|]|\((video|watch|photos)\)", re.I)
MEDIA_PATH = re.compile(r"/(video|videos|gallery|galleries|pictures|in-pictures|photos|podcasts?|audio)(/|-)|/live(/|-updates|-blog)", re.I)


def is_media(art):
    """A video, gallery, live or audio page: real coverage, but not a headline for a written summary."""
    return bool(MEDIA_TITLE.search(art["title"]) or MEDIA_PATH.search(art["url"]))


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

    feeds = json.loads((ROOT / "pipeline/feeds.json").read_text())
    region_of = {f["source"]: f["region"] for f in feeds["feeds"] if f.get("region")}
    tx = feeds.get("regions", {}).get("tx")
    tx_live = bool(tx) and datetime.fromisoformat(scan["fetched_at"]) < datetime.fromisoformat(tx["until"])

    now_h = datetime.fromisoformat(scan["fetched_at"]).timestamp() / 3600
    # Region outlets (the Texas demo) never feed the national sections.
    dated = [i for i, a in enumerate(news) if hours(a) is not None and a["source"] not in region_of]
    recent = [i for i in dated if now_h - hours(news[i]) <= RECENT_HOURS]
    # The week's environment, science and health articles, sorted one by one, then grouped over the pool.
    base = (vectors @ other.T).max(axis=1)
    art = {t: (vectors @ m.T).max(axis=1) - base for t, m in protos.items()}
    top_topic = lambda i: max(art, key=lambda t: art[t][i])
    slow = [i for i in dated if top_topic(i) in SLOW_TOPICS and art[top_topic(i)][i] > 0]
    # Week clusters go first, so a story carried over from the last scan keeps its id in its week form.
    clusters = [(m, "week") for m in sub(slow, POOL_DAYS * 24)] + [(m, "day") for m in sub(recent, WINDOW_HOURS)]
    # Texas Election: recent election coverage that is about Texas (or from a Texas outlet), grouped on its own.
    if tx_live:
        # A week of it: election stories build over days, and the demo runs to Election Day.
        # Grouped by event like every other section, each story under its own outlet headline (Heston,
        # 2026-10-23: one rolling story per race put every headline under one title). TX_RACES still sorts
        # articles by race for the numbers (tx_numbers.py).
        tx_ids = [i for i, a in enumerate(news) if hours(a) is not None and tx_admit(a, a["source"] in region_of)]
        clusters += [(m, "texas") for m in sub(tx_ids, POOL_DAYS * 24)]

    side = {f["source"]: side_of(f) for f in feeds["feeds"]}
    # Audience lean, 0 = all Democratic users, 1 = all Republican users (Pew), for the spectrum charts.
    lean = {f["source"]: round(f["pew"]["rep"] / (f["pew"]["rep"] + f["pew"]["dem"]), 3) for f in feeds["feeds"] if f.get("pew")}
    pew = {f["source"]: {"rep": f["pew"]["rep"], "dem": f["pew"]["dem"]} for f in feeds["feeds"] if f.get("pew")}
    allsides = {f["source"]: f["allsides"]["rating"] for f in feeds["feeds"] if not f.get("pew") and (f.get("allsides") or {}).get("rating") in ALLSIDES_SIDE}
    working = {f["source"] for f in scan.get("feeds", []) if f["ok"]}
    roster = {k: sorted(src for src in working if side.get(src, "unplaced") == k and src not in region_of) for k in (*SIDES, "unplaced")}
    roster_tx = {k: sorted(src for src in working if side.get(src, "unplaced") == k) for k in (*SIDES, "unplaced")}  # national + Texas outlets

    prev_sid, used_sids = previous_ids(), set()
    stories = []
    for idx, span in clusters:
        arts = [news[i] for i in idx]
        sources = sorted({a["source"] for a in arts})
        if len(sources) < 2:
            continue
        # Working title: the article closest to the story's centre of meaning, preferring a written article:
        # a video, gallery, live blog or podcast headline ("... - video") promises media we don't show.
        centre = vectors[idx].mean(axis=0)
        closeness = vectors[idx] @ centre
        order = [int(i) for i in np.argsort(-closeness)]
        lead = next((arts[i] for i in order if not is_media(arts[i])), arts[order[0]])
        coverage = {k: [src for src in sources if side.get(src, "unplaced") == k] for k in (*SIDES, "unplaced")}
        texas = span == "texas"
        r = roster_tx if texas else roster
        shares = [len(coverage[k]) / len(r[k]) if r[k] else 0.0 for k in SIDES]
        # A story keeps its id from the last scan when most of its articles were in that story, so
        # links keep working and its summary is not paid for again as old articles age out.
        first = min(arts, key=lambda a: (a["published"] or "", a["url"]))
        # Texas ids are "tx" + hash; the retired race ids ("tx-senate") are never carried onto an event story.
        votes = Counter(s for a in arts for s in prev_sid.get(a["url"], ()) if s.startswith(TX_SID) == texas and not s.startswith(TX_SID + "-"))
        carried = next((sid for sid, n in votes.most_common(1) if n >= max(2, 0.3 * len(arts)) and sid not in used_sids), None)
        sid = carried or (TX_SID if texas else "") + hashlib.sha1(first["url"].encode()).hexdigest()[:8 if texas else 10]
        while sid in used_sids:  # a new id can match one carried from the last scan: never reuse one
            sid = (TX_SID if texas else "") + hashlib.sha1((sid + "+").encode()).hexdigest()[:8 if texas else 10]
        used_sids.add(sid)
        stories.append({
            "_idx": idx,
            "sid": sid,
            "span": "day" if texas else span,
            "region": "tx" if texas else None,
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
        st["topic"] = "texas" if st.get("region") == "tx" else best if scores[best] > TOPIC_MARGIN else "other"
    # Slow topics come from the week pass; politics and the rest from the day pass. A day story on a slow
    # topic is kept only if the week pass did not already group its articles.
    week_urls = {a["url"] for st in stories if st["span"] == "week" and st["topic"] in SLOW_TOPICS for a in st["articles"]}
    stories = [st for st in stories if (st["span"] == "week" and st["topic"] in SLOW_TOPICS)
               or (st["span"] == "day" and not (st["topic"] in SLOW_TOPICS and any(a["url"] in week_urls for a in st["articles"])))]
    # A national story that is mostly the same articles as a Texas one is marked, so a reader who follows the
    # Texas section sees it once, there.
    tx_urls = {a["url"] for st in stories if st.get("region") == "tx" for a in st["articles"]}
    for st in stories:
        if st.get("region") != "tx" and tx_urls and sum(a["url"] in tx_urls for a in st["articles"]) >= 0.5 * len(st["articles"]):
            st["also_in"] = "texas"
    stories.sort(key=lambda s: (s["balance_score"], s["outlets"], len(s["articles"])), reverse=True)
    for n, st in enumerate(stories):
        st["id"] = n
        st["related"] = []
        st["related_to"] = None
        for earlier in stories[:n]:
            if earlier["related_to"] is None and (earlier.get("region") == st.get("region")) and float((vectors[st["_idx"]] @ vectors[earlier["_idx"]].T).mean()) >= RELATED:
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
                   "allsides": allsides.get(f["source"]), "region": region_of.get(f["source"])}
                  for f in scan.get("feeds", [])],
        "regions": feeds.get("regions", {}),
        "method": {"model": MODEL, "threshold": THRESHOLD, "window_hours": WINDOW_HOURS, "linkage": "average", "related": RELATED,
                   "topics": {"politics": "U.S. politics and U.S. policy abroad", "elections": "Elections", "economy": "Economy",
                              "immigration": "Immigration", "crime": "Crime and justice", "world": "World", "environment": "Energy and environment",
                              "health": "Health", "tech": "AI and tech", "science": "Science", "education": "Education", "texas": "Texas Election (demo)"}, "topic_margin": TOPIC_MARGIN},
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
