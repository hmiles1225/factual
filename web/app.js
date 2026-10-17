// Renders the latest scan from data/stories.json. Every string from a feed goes in
// through textContent, never innerHTML, so a headline can't inject markup.
"use strict";

const LEAD = 5;
const WORDS = ["zero", "one", "two", "three", "four", "five"];

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const clock = iso => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const stamp = iso => {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? clock(iso) : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const SIDES = [["left", "Left"], ["center", "Center"], ["right", "Right"]];

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

function storyCard(story, i, scanTime, roster, all) {
  const li = el("li", "story");
  const first = lead(story);

  li.append(el("p", "story-meta", `${String(i + 1).padStart(2, "0")} · ${plural(story.outlets, "outlet", "outlets")}`));

  const h = el("h2", "headline");
  const a = el("a", null, story.working_title);
  a.href = first.url;
  h.append(a);
  li.append(h);
  li.append(el("p", "attribution", `Headline from ${first.source}`));
  li.append(coverageLine(story, roster));

  const status = el("p", "unchecked");
  status.append(el("strong", null, "Not checked yet."), document.createTextNode(" No verdict until the claims are checked against their sources."));
  li.append(status);

  const details = el("details", "coverage");
  details.append(el("summary", null, `See all ${plural(story.articles.length, "article", "articles")}`));
  const ul = el("ul");
  for (const art of story.articles) {
    const row = el("li");
    row.append(el("span", "src", art.source));
    const link = el("a", "title", art.title);
    link.href = art.url;
    row.append(link);
    if (art.published) {
      const t = el("time", null, stamp(art.published));
      t.dateTime = art.published;
      row.append(t);
    }
    ul.append(row);
  }
  details.append(ul);
  li.append(details);

  if (story.related.length) {
    const rel = el("div", "related");
    rel.append(el("p", "related-label", "Related coverage"));
    const ul = el("ul");
    for (const r of story.related.map(id => all[id])) {
      const item = el("li");
      const a = el("a", "title", r.working_title);
      a.href = lead(r).url;
      item.append(a, el("span", "attribution", ` Headline from ${lead(r).source} · ${plural(r.outlets, "outlet", "outlets")}`));
      ul.append(item);
    }
    rel.append(ul);
    li.append(rel);
  }

  const basis = el("p", "basis");
  basis.append(el("b", null, "Based on "),
    document.createTextNode(`${plural(story.articles.length, "article", "articles")} from ${story.sources.join(", ")}, grouped in the ${clock(scanTime)} scan`));
  li.append(basis);
  return li;
}

function moreRow(story) {
  const li = el("li");
  const a = el("a", "title", story.working_title);
  a.href = lead(story).url;
  li.append(a);
  li.append(el("p", "attribution", `Headline from ${lead(story).source} · ${plural(story.outlets, "outlet", "outlets")}`));
  return li;
}

function render(data) {
  const feeds = data.feeds || [];
  const ok = feeds.filter(f => f.ok).length;
  const scanned = new Date(data.scanned_at);

  document.getElementById("today-date").textContent =
    scanned.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });

  const top = data.stories.filter(s => s.related_to === null);
  const leadStories = top.slice(0, LEAD);
  document.getElementById("today-count").textContent = WORDS[leadStories.length] || String(leadStories.length);

  document.getElementById("scanline").textContent =
    `Scanned ${data.articles_scanned} articles from ${ok} of ${feeds.length} outlets at ${clock(data.scanned_at)} · scans run hourly`;

  const list = document.getElementById("stories");
  leadStories.forEach((s, i) => list.append(storyCard(s, i, data.scanned_at, data.roster, data.stories)));

  const leadBasis = document.getElementById("lead-basis");
  leadBasis.append(el("b", null, "Based on "),
    document.createTextNode(`which events the most outlets covered, with left, center and right each counting equally however many outlets each side has. ${plural(data.count, "story was", "stories were")} covered by two or more outlets; ${data.opinion_excluded} opinion pieces were kept out.`));
  leadBasis.hidden = false;

  const rest = top.slice(LEAD);
  if (rest.length) {
    const ul = document.getElementById("more-list");
    rest.forEach(s => ul.append(moreRow(s)));
    document.getElementById("more").hidden = false;
  }

  const fl = document.getElementById("feeds");
  for (const [k, label] of [...SIDES, ["unplaced", "Unplaced"]]) {
    const group = feeds.filter(f => f.side === k);
    if (!group.length) continue;
    fl.append(el("li", "feed-side", label));
    for (const f of group.sort((a, b) => a.source.localeCompare(b.source)))
      fl.append(el("li", f.ok ? null : "fail", f.ok ? `${f.source} · ${f.articles}` : `${f.source} · not reachable this scan`));
  }
  const pl = data.placement;
  const basis = document.getElementById("feeds-basis");
  basis.append(el("b", null, "Based on "), document.createTextNode(
    `${pl.source.name} (survey of ${pl.source.survey}): the share of each outlet's regular audience who are Republican, among Republican and Democratic users. Under ${Math.round(pl.left_below * 100)}% is left, over ${Math.round(pl.right_above * 100)}% is right. Outlets Pew did not ask about are unplaced. Nothing is set by hand.`));
}

function fail() {
  document.getElementById("scanline").textContent = "The latest scan didn't load.";
  const box = el("div", "error");
  box.append(el("p", null, "We couldn't load the latest scan. Reload the page in a minute. If it keeps happening, the scan itself may have failed; the last good one stays up when that happens."));
  document.getElementById("stories").after(box);
}

fetch("data/stories.json", { cache: "no-cache" })
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(render)
  .catch(fail);
