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

// The working title is one outlet's headline, so it is shown as their words.
function lead(story) {
  return story.articles.find(a => a.title === story.working_title) || story.articles[0];
}

function storyCard(story, i, scanTime) {
  const li = el("li", "story");
  const first = lead(story);

  li.append(el("p", "story-meta", `${String(i + 1).padStart(2, "0")} · ${plural(story.outlets, "outlet", "outlets")}`));

  const h = el("h2", "headline");
  const a = el("a", null, story.working_title);
  a.href = first.url;
  h.append(a);
  li.append(h);
  li.append(el("p", "attribution", `Headline from ${first.source}`));

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

  const leadStories = data.stories.slice(0, LEAD);
  document.getElementById("today-count").textContent = WORDS[leadStories.length] || String(leadStories.length);

  document.getElementById("scanline").textContent =
    `Scanned ${data.articles_scanned} articles from ${ok} of ${feeds.length} outlets at ${clock(data.scanned_at)} · scans run hourly`;

  const list = document.getElementById("stories");
  leadStories.forEach((s, i) => list.append(storyCard(s, i, data.scanned_at)));

  const leadBasis = document.getElementById("lead-basis");
  leadBasis.append(el("b", null, "Based on "),
    document.createTextNode(`which events the most outlets covered. ${plural(data.count, "story was", "stories were")} covered by two or more outlets; ${data.opinion_excluded} opinion pieces were kept out.`));
  leadBasis.hidden = false;

  const rest = data.stories.slice(LEAD);
  if (rest.length) {
    const ul = document.getElementById("more-list");
    rest.forEach(s => ul.append(moreRow(s)));
    document.getElementById("more").hidden = false;
  }

  const fl = document.getElementById("feeds");
  for (const f of [...feeds].sort((a, b) => a.source.localeCompare(b.source))) {
    const li = el("li", f.ok ? null : "fail", f.ok ? `${f.source} · ${f.articles}` : `${f.source} · not reachable this scan`);
    fl.append(li);
  }
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
