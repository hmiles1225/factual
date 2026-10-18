// Renders the latest scan: Today (index.html) and one story (story.html?s=<id>).
// Every string from a feed or a model goes in through textContent, never innerHTML,
// so a headline or a claim can't inject markup.
//
// Reading order on every story: the story the coverage agrees on, then what's true or not
// (only claims the evidence decided), then what's still open. Everything else is folded away.
"use strict";

const LEAD = 5;
const WORDS = ["no", "one", "two", "three", "four", "five"];
const DECIDED = ["Holds up", "Missing context", "Doesn't hold up"];

// Verdicts: always a glyph and a word, never color alone (Figma Foundations 5:119).
const VERDICT = {
  "Holds up": { cls: "hold", glyph: "✓" },
  "Missing context": { cls: "ctx", glyph: "◐" },
  "Doesn't hold up": { cls: "no", glyph: "✕" },
  "Unproven": { cls: "unk", glyph: "?" },
};
const MODEL_NAMES = { "gemini-3.8-flash": "Gemini 3.8 Flash", "claude-opus-5-5": "Claude Opus 5.5" };

const $ = id => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const clock = iso => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const stamp = iso => {
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString()
    ? clock(iso) : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const storyHref = story => `story.html?s=${encodeURIComponent(story.sid)}`;
const lead = story => story.articles.find(a => a.title === story.working_title) || story.articles[0];
const claimOf = (lib, key) => (lib && lib.claims && lib.claims[key]) || null;
const listNames = (names, max = 4) => names.length <= max
  ? names.join(", ").replace(/, ([^,]*)$/, " and $1")
  : `${names.slice(0, max).join(", ")} and ${names.length - max} more`;

// Differences whose checked claim the evidence decided, and the ones it didn't.
function decided(story, lib) {
  return ((story.brief && story.brief.differences) || [])
    .map(d => ({ d, c: claimOf(lib, d.check) }))
    .filter(({ c }) => c && DECIDED.includes(c.verdict));
}
function stillOpen(story, lib) {
  return ((story.brief && story.brief.differences) || [])
    .filter(d => !(claimOf(lib, d.check) && DECIDED.includes(claimOf(lib, d.check).verdict)));
}

function chip(verdict) {
  const v = VERDICT[verdict] || VERDICT.Unproven;
  const c = el("span", `chip chip-${v.cls}`);
  c.append(el("span", "chip-glyph", v.glyph), el("span", "chip-word", verdict));
  return c;
}

/* ---------- Today ---------- */

function storyCard(story, i, data) {
  const li = el("li", i === 0 ? "story story-lead" : "story");
  const main = el("div", "story-main");
  main.append(el("p", "story-num", String(i + 1).padStart(2, "0")));
  const h = el("h2", "headline");
  const a = el("a", null, story.working_title);
  a.href = storyHref(story);
  h.append(a);
  main.append(h);

  const agreed = (story.brief && story.brief.agreed) || [];
  if (agreed.length) main.append(el("p", "gist", agreed.slice(0, 2).map(f => f.fact).join(" ")));
  li.append(main);

  const rows = decided(story, data.library).slice(0, 2);
  if (rows.length) {
    const ul = el("ul", "checks");
    for (const { c } of rows) {
      const r = el("li");
      r.append(chip(c.verdict), el("span", "check-claim", c.claim));
      ul.append(r);
    }
    li.append(ul);
  }

  const foot = el("div", "story-foot");
  foot.append(el("span", "sources-line", `${plural(story.articles.length, "article", "articles")} · ${listNames(story.sources, 3)}`));
  const more = el("a", "read-more", "Read the story");
  more.href = storyHref(story);
  foot.append(more);
  li.append(foot);
  return li;
}

function renderToday(data) {
  const feeds = data.feeds || [];
  $("today-date").textContent = "Politics · " + new Date(data.scanned_at).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  $("scanline").textContent = `Updated ${clock(data.scanned_at)}`;

  // Only stories with a written summary (agreed facts) are shown. Never a bare headline.
  const summarized = data.stories.filter(s => s.related_to === null && s.topic === "politics" && s.brief && s.brief.agreed && s.brief.agreed.length);
  const leadStories = summarized.slice(0, LEAD);
  if (!leadStories.length) {
    $("today-title").textContent = "Today’s stories are being summarized.";
    $("stories").replaceWith(el("p", "dek", "Check back shortly. A story appears here once the coverage has been summarized."));
  } else {
    $("today-count").textContent = WORDS[leadStories.length] || String(leadStories.length);
    leadStories.forEach((s, i) => $("stories").append(storyCard(s, i, data)));
  }

  const ok = feeds.filter(f => f.ok).sort((a, b) => a.source.localeCompare(b.source));
  $("feeds").append(el("p", "feeds-list", ok.map(f => f.source).join(", ")));
  const down = feeds.filter(f => !f.ok).map(f => f.source);
  if (down.length) $("feeds").append(el("p", "feeds-down", `Not reachable in the last scan: ${down.join(", ")}.`));
}

/* ---------- One story ---------- */

function claimDetails(d, c) {
  const det = el("details", "check-row");
  const sum = el("summary");
  sum.append(chip(c.verdict), el("span", "check-claim", c.claim));
  det.append(sum);
  const body = el("div", "check-body");
  if (c.steelman) body.append(el("p", "why", `Why this sounds right: ${c.steelman}`));
  if (c.finding) body.append(el("p", "finding", c.finding));
  if (c.note) body.append(el("p", "check-note", c.note));
  const said = d.positions.map(p => `${listNames(p.outlets, 3)}: ${p.says}`).join(" · ");
  if (said) body.append(el("p", "who-said", said));
  if (c.evidence && c.evidence.length) {
    const ul = el("ul", "evidence");
    for (const e of c.evidence) {
      const li = el("li");
      li.append(el("span", "ev-quote", `“${e.quote}”`));
      const src = el("a", "ev-src", `${e.publisher}${e.published ? ", " + e.published : ""} ↗`);
      src.href = e.url;
      src.rel = "noopener";
      li.append(src);
      ul.append(li);
    }
    body.append(ul);
  }
  const by = [c.checked_by, c.second_opinion].filter(Boolean).map(m => MODEL_NAMES[m] || m).join(" and ");
  body.append(el("p", "check-meta", `Checked ${stamp(c.checked_at)} by ${by}. Every quote above was found on its source page.`));
  det.append(body);
  return det;
}

function renderStory(data) {
  const sid = new URLSearchParams(location.search).get("s");
  const story = data.stories.find(s => s.sid === sid);
  const body = $("story-body");
  if (!story) {
    $("story-title").textContent = "This story has moved off the latest scan.";
    const back = el("a", "read-more", "See today's stories");
    back.href = "./";
    body.append(back);
    return;
  }
  document.title = `${story.working_title} · fACTUAL`;
  $("story-meta").textContent = `${story.topic === "politics" ? "Politics · " : ""}Updated ${clock(data.scanned_at)}`;
  $("story-title").textContent = story.working_title;
  $("story-sub").append(el("p", "byline", `Headline from ${lead(story).source}`));

  const brief = story.brief;
  const agreed = (brief && brief.agreed) || [];

  // 1. The story the coverage agrees on.
  const s1 = el("section", "block");
  s1.append(el("h2", "block-title", "The story"));
  if (agreed.length) {
    s1.append(el("p", "story-text", agreed.map(f => f.fact).join(" ")));
    const reporters = [...new Set(agreed.flatMap(f => f.reported_by))].sort();
    s1.append(el("p", "block-note", `Reported across ${listNames(reporters, 6)}. Each line is stated by at least two of them.`));
  } else {
    s1.append(el("p", "story-text muted", "Being summarized. The facts the coverage agrees on will appear here."));
  }
  body.append(s1);

  // 2. True or not: only what the evidence decided.
  const rows = decided(story, data.library);
  if (rows.length) {
    const s2 = el("section", "block");
    s2.append(el("h2", "block-title", "True or not"));
    for (const { d, c } of rows) s2.append(claimDetails(d, c));
    body.append(s2);
  }

  // 3. Still open: disagreements the evidence hasn't settled, and values questions.
  const open = stillOpen(story, data.library);
  const values = (brief && brief.values_questions) || [];
  if (open.length || values.length) {
    const s3 = el("section", "block");
    s3.append(el("h2", "block-title", "Still open"));
    const ul = el("ul", "open-list");
    for (const d of open) {
      const li = el("li");
      li.append(el("p", "open-point", d.point));
      li.append(el("p", "open-sides", d.positions.map(p => `${listNames(p.outlets, 3)}: ${p.says}`).join(" · ")));
      ul.append(li);
    }
    for (const q of values) {
      const li = el("li");
      li.append(el("p", "open-point", q), el("p", "open-sides", "A values question. That’s yours to decide."));
      ul.append(li);
    }
    s3.append(ul);
    body.append(s3);
  }

  // 4. Sources, folded away.
  const s4 = el("section", "block");
  const det = el("details", "sources-all");
  det.append(el("summary", null, `Sources: ${plural(story.articles.length, "article", "articles")} from ${listNames(story.sources, 3)}`));
  const ul = el("ul", "articles");
  for (const art of [...story.articles].sort((a, b) => a.source.localeCompare(b.source))) {
    const li = el("li");
    const a = el("a", null, art.title);
    a.href = art.url;
    a.rel = "noopener";
    li.append(el("span", "src", art.source), a);
    ul.append(li);
  }
  det.append(ul);
  s4.append(det);
  s4.append(el("p", "block-note", "Summaries and checks are written by AI from the coverage and from primary sources. No person reviews them before they appear."));
  body.append(s4);
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
