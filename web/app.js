// Renders the latest scan from data/stories.json: Today (index.html) and one story
// (story.html?s=<id>). Every string from a feed goes in through textContent, never
// innerHTML, so a headline can't inject markup.
"use strict";

const LEAD = 5;
const WORDS = ["zero", "one", "two", "three", "four", "five"];
const SIDES = [["left", "Left"], ["center", "Center"], ["right", "Right"]];

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const $ = id => document.getElementById(id);

const clock = iso => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const stamp = iso => {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? clock(iso) : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const storyHref = story => `story.html?s=${encodeURIComponent(story.sid)}`;

// Verdicts: always a glyph and a word, never color alone (Figma Foundations 5:119).
const VERDICT = {
  "Holds up": { cls: "hold", glyph: "\u2713" },
  "Missing context": { cls: "ctx", glyph: "\u25D0" },
  "Doesn't hold up": { cls: "no", glyph: "\u2715" },
  "Unproven": { cls: "unk", glyph: "?" },
};
function chip(verdict) {
  const v = VERDICT[verdict] || VERDICT.Unproven;
  const c = el("span", `chip chip-${v.cls}`);
  c.append(el("span", "chip-glyph", v.glyph), document.createTextNode(verdict));
  return c;
}
const claimOf = (lib, key) => (lib && lib.claims && lib.claims[key]) || null;
const MODEL_NAMES = { "gemini-3.8-flash": "Gemini 3.8 Flash", "claude-opus-5-5": "Claude Opus 5.5" };
const modelName = id => MODEL_NAMES[id] || id;

// "Left 4 of 10 · Center 2 of 4 · Right 3 of 3": positions on a line, never teams or colors.
function coverageLine(story, roster) {
  const parts = SIDES.filter(([k]) => roster[k].length).map(([k, label]) => `${label} ${story.coverage[k].length} of ${roster[k].length}`);
  const p = el("p", "sides", parts.join(" · "));
  if (story.coverage.unplaced.length) p.append(el("span", "unplaced", ` · Unplaced: ${story.coverage.unplaced.join(", ")}`));
  return p;
}

// The working title is one outlet's headline, so it is shown as their words.
function lead(story) {
  return story.articles.find(a => a.title === story.working_title) || story.articles[0];
}

function basisLine(text) {
  const p = el("p", "basis");
  p.append(el("b", null, "Based on "), document.createTextNode(text));
  return p;
}

function unchecked() {
  const p = el("p", "unchecked");
  p.append(el("strong", null, "Not checked yet."), document.createTextNode(" No verdict until the claims are checked against their sources."));
  return p;
}

function relatedList(story, all, label = "Related coverage") {
  const rel = el("div", "related");
  rel.append(el("p", "related-label", label));
  const ul = el("ul");
  for (const r of story.related.map(id => all[id])) {
    const item = el("li");
    const a = el("a", "title", r.working_title);
    a.href = storyHref(r);
    item.append(a, el("span", "attribution", ` Headline from ${lead(r).source} · ${plural(r.outlets, "outlet", "outlets")}`));
    ul.append(item);
  }
  rel.append(ul);
  return rel;
}

/* ---------- Today ---------- */

function storyCard(story, i, data) {
  const li = el("li", "story");
  li.append(el("p", "story-meta", `${String(i + 1).padStart(2, "0")} · ${plural(story.outlets, "outlet", "outlets")}`));
  const h = el("h2", "headline");
  const a = el("a", null, story.working_title);
  a.href = storyHref(story);
  h.append(a);
  li.append(h, el("p", "attribution", `Headline from ${lead(story).source}`), coverageLine(story, data.roster));
  const checked = (story.checks || []).map(k => claimOf(data.library, k)).filter(Boolean);
  if (checked.length) {
    const ul = el("ul", "card-claims");
    for (const c of checked) {
      const item = el("li");
      item.append(chip(c.verdict), el("span", "card-claim", c.claim));
      ul.append(item);
    }
    li.append(ul);
  } else {
    li.append(unchecked());
  }
  if (story.related.length) li.append(relatedList(story, data.stories));
  li.append(basisLine(`${plural(story.articles.length, "article", "articles")} from ${story.sources.join(", ")}, grouped in the ${clock(data.scanned_at)} scan`));
  return li;
}

function moreRow(story) {
  const li = el("li");
  const a = el("a", "title", story.working_title);
  a.href = storyHref(story);
  li.append(a, el("p", "attribution", `Headline from ${lead(story).source} · ${plural(story.outlets, "outlet", "outlets")}`));
  return li;
}

function renderToday(data) {
  const feeds = data.feeds || [];
  const ok = feeds.filter(f => f.ok).length;
  $("today-date").textContent = new Date(data.scanned_at).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });

  const top = data.stories.filter(s => s.related_to === null);
  const leadStories = top.slice(0, LEAD);
  $("today-count").textContent = WORDS[leadStories.length] || String(leadStories.length);
  $("scanline").textContent = `Scanned ${data.articles_scanned} articles from ${ok} of ${feeds.length} outlets at ${clock(data.scanned_at)} · scans run hourly`;

  leadStories.forEach((s, i) => $("stories").append(storyCard(s, i, data)));
  if (leadStories.some(s => (s.checks || []).length)) {
    $("preview-title").textContent = "Early version: checked by AI, no human editor";
    $("preview-title").nextElementSibling.textContent =
      "Claims in these stories are checked by AI against primary sources, and every quote shown was found on its source page by our code. No person reviews a check before it appears. A Doesn't hold up needs two different AI models to agree. Stories still waiting say so.";
  }
  const leadBasis = $("lead-basis");
  leadBasis.replaceWith(basisLine(`which events the most outlets covered, with left, center and right each counting equally however many outlets each side has. ${plural(data.count, "story was", "stories were")} covered by two or more outlets; ${data.opinion_excluded} opinion pieces were kept out.`));

  const rest = top.slice(LEAD);
  if (rest.length) {
    rest.forEach(s => $("more-list").append(moreRow(s)));
    $("more").hidden = false;
  }

  const fl = $("feeds");
  for (const [k, label] of [...SIDES, ["unplaced", "Unplaced"]]) {
    const group = feeds.filter(f => f.side === k);
    if (!group.length) continue;
    fl.append(el("li", "feed-side", label));
    for (const f of group.sort((a, b) => a.source.localeCompare(b.source)))
      fl.append(el("li", f.ok ? null : "fail", f.ok ? `${f.source} · ${f.articles}` : `${f.source} · not reachable this scan`));
  }
  const pl = data.placement;
  $("feeds-basis").replaceWith(basisLine(`${pl.source.name} (survey of ${pl.source.survey}): the share of each outlet's regular audience who are Republican, among Republican and Democratic users. Under ${Math.round(pl.left_below * 100)}% is left, over ${Math.round(pl.right_above * 100)}% is right. Outlets Pew did not ask about are unplaced. Nothing is set by hand.`));
}

/* ---------- One story ---------- */

function pendingVerdict() {
  // Until a story's claims are checked, say so plainly rather than drawing empty sections.
  const verdict = el("section", "verdict pending");
  const vt = el("h2", null, "The verdict");
  verdict.append(vt,
    el("p", null, "Not checked yet. Once this story is checked, this is where you'll see what's true, what's not true and what's still open, followed by the numbers that put it in perspective. Each line will name its source."),
    el("p", "pending-note", "Nothing here is filled in until then."));
  return verdict;
}

// Built only from checked claims: nothing appears here that a claim below doesn't support.
function verdictBlock(story, lib) {
  const box = el("section", "verdict");
  box.setAttribute("aria-labelledby", "verdict-title");
  const h = el("h2", null, "The verdict");
  h.id = "verdict-title";
  box.append(h);
  const groups = [["true", "What\u2019s true"], ["not_true", "What\u2019s not true"], ["open", "Still open"]];
  for (const [k, label] of groups) {
    const g = el("div", "vgroup");
    g.append(el("h3", null, label));
    const items = story.verdict[k] || [];
    if (!items.length) g.append(el("p", "vnone", k === "not_true" ? "No checked claim here was found false." : "Nothing checked here."));
    for (const it of items) {
      const row = el("p", "vline");
      if (it.values) {
        row.append(el("span", "vtag", "Values question"), document.createTextNode(` ${it.values} That\u2019s yours to decide.`));
      } else {
        const c = claimOf(lib, it.key);
        if (!c) continue;
        const a = el("a", "vclaim", c.claim);
        a.href = `#claim-${it.key}`;
        row.append(chip(c.verdict), document.createTextNode(" "), a);
      }
      g.append(row);
    }
    box.append(g);
  }
  const sources = new Set(story.checks.flatMap(k => (claimOf(lib, k)?.evidence || []).map(e => e.url)));
  const models = [...new Set(story.checks.flatMap(k => [claimOf(lib, k)?.checked_by, claimOf(lib, k)?.second_opinion]).filter(Boolean))];
  box.append(basisLine(`${plural(story.verdict.checked, "checked claim", "checked claims")} and ${plural(sources.size, "source", "sources")}. Checked by ${models.map(modelName).join(" and ")}; every quote was found on its source page. No person reviews a check before it appears.`));
  return box;
}

function claimCards(checks) {
  const sec = el("section", "claims");
  sec.setAttribute("aria-labelledby", "claims-title");
  const h = el("h2", null, "Each claim, checked");
  h.id = "claims-title";
  sec.append(h);
  for (const [key, c] of checks) {
    const card = el("article", "claim-card");
    card.id = `claim-${key}`;
    card.append(el("p", "claim-text", `\u201c${c.claim}\u201d`));
    if (c.said_by && c.said_by.length) card.append(el("p", "attribution", `In coverage from ${c.said_by.join(", ")}`));
    if (c.steelman) {
      card.append(el("h3", null, "Why this sounds right"), el("p", "steelman", c.steelman));
    }
    const vrow = el("div", "claim-verdict");
    vrow.append(chip(c.verdict));
    for (const f of c.reasoning_flags || []) vrow.append(el("span", "flag", f));
    card.append(vrow);
    if (c.finding) card.append(el("p", "finding", c.finding));
    if (c.note) card.append(el("p", "claim-note", c.verdict === "Unproven" && c.model_verdict && c.model_verdict !== "Unproven"
      ? `Shown as Unproven: ${c.note}.` : c.note));
    if (c.evidence && c.evidence.length) {
      const ul = el("ul", "evidence");
      for (const e of c.evidence) {
        const li = el("li");
        li.append(el("span", "ev-quote", `\u201c${e.quote}\u201d`));
        const src = el("a", "ev-src", `${e.publisher}${e.published ? " \u00b7 " + e.published : ""} \u2197`);
        src.href = e.url;
        src.rel = "noopener";
        li.append(src);
        ul.append(li);
      }
      card.append(ul);
    }
    card.append(basisLine(`${c.newest_data || "the sources above"} Checked ${stamp(c.checked_at)}.`));
    sec.append(card);
  }
  return sec;
}

function renderStory(data) {
  const sid = new URLSearchParams(location.search).get("s");
  const story = data.stories.find(s => s.sid === sid);
  if (!story) {
    $("story-title").textContent = "This story has moved off the latest scan.";
    $("story-body").append(el("p", "lede", "Stories drop out once their coverage is more than 48 hours old."));
    const back = el("a", null, "See today's stories");
    back.href = "./";
    $("story-body").append(back);
    return;
  }
  document.title = `${story.working_title} · fACTUAL`;
  $("story-meta").textContent = `Updated ${clock(data.scanned_at)} · ${plural(story.outlets, "outlet", "outlets")}`;
  $("story-title").textContent = story.working_title;
  const body = $("story-body");
  body.append(el("p", "attribution", `Headline from ${lead(story).source}`), coverageLine(story, data.roster));

  const checks = (story.checks || []).map(k => [k, claimOf(data.library, k)]).filter(([, c]) => c);
  if (checks.length && story.verdict) {
    body.append(verdictBlock(story, data.library), claimCards(checks));
  } else {
    body.append(pendingVerdict());
  }

  const cov = el("section", "who");

  cov.setAttribute("aria-labelledby", "who-title");
  const ct = el("h2", null, "Who covered it");
  ct.id = "who-title";
  cov.append(ct, el("p", "who-note", "Each link opens the outlet's own site."));
  for (const [k, label] of [...SIDES, ["unplaced", "Unplaced"]]) {
    const arts = story.articles.filter(a => story.coverage[k].includes(a.source));
    if (!arts.length) continue;
    cov.append(el("h3", null, label));
    const ul = el("ul", "articles");
    for (const art of arts) {
      const li = el("li");
      li.append(el("span", "src", art.source));
      const a = el("a", "title", art.title);
      a.href = art.url;
      a.rel = "noopener";
      li.append(a);
      const meta = el("span", "art-meta", art.published ? `${stamp(art.published)} · ` : "");
      meta.append(document.createTextNode(`at ${new URL(art.url).hostname.replace(/^www\./, "")} ↗`));
      li.append(meta);
      ul.append(li);
    }
    cov.append(ul);
  }
  const missing = SIDES.filter(([k]) => data.roster[k].length && !story.coverage[k].length).map(([, label]) => label.toLowerCase());
  if (missing.length) cov.append(el("p", "gap", `No ${missing.join(" or ")}-audience outlet in our list covered this in the last 48 hours.`));
  body.append(cov);

  if (story.related.length) body.append(relatedList(story, data.stories, "Related coverage of the same event"));
  body.append(basisLine(`${plural(story.articles.length, "article", "articles")} from ${plural(story.outlets, "outlet", "outlets")}, grouped by meaning in the ${clock(data.scanned_at)} scan. Outlet sides from Pew Research Center audience data.`));
}

function fail() {
  const box = el("div", "error");
  box.append(el("p", null, "We couldn't load the latest scan. Reload the page in a minute. If it keeps happening, the scan itself may have failed; the last good one stays up when that happens."));
  ($("stories") || $("story-body")).after(box);
}

const getJSON = (url, optional) => fetch(url, { cache: "no-cache" })
  .then(r => { if (!r.ok) { if (optional) return null; throw new Error(r.status); } return r.json(); })
  .catch(e => { if (optional) return null; throw e; });

Promise.all([getJSON("data/stories.json"), getJSON("data/library.json", true)])
  .then(([data, library]) => { data.library = library; (document.body.dataset.page === "story" ? renderStory : renderToday)(data); })
  .catch(fail);
