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
  li.append(h, el("p", "attribution", `Headline from ${lead(story).source}`), coverageLine(story, data.roster), unchecked());
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

  // The verdict comes first on every story. Until the checking stage runs, say so plainly
  // rather than drawing empty sections that look like content.
  const verdict = el("section", "verdict pending");
  verdict.setAttribute("aria-labelledby", "verdict-title");
  const vt = el("h2", null, "The verdict");
  vt.id = "verdict-title";
  verdict.append(vt,
    el("p", null, "Not checked yet. Once this story is checked, this is where you'll see what's true, what's not true and what's still open, followed by the numbers that put it in perspective. Each line will name its source."),
    el("p", "pending-note", "Nothing here is filled in until then."));
  body.append(verdict);

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

fetch("data/stories.json", { cache: "no-cache" })
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(data => (document.body.dataset.page === "story" ? renderStory : renderToday)(data))
  .catch(fail);
