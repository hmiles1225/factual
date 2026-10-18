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


/* ---------- Charts: built only from data the scan has. Ink and gray only: yellow and
   vermilion mean Holds up and Doesn't hold up, so a chart never borrows them. ---------- */
const SVGNS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
const hourLabel = d => d.toLocaleTimeString([], { hour: "numeric" }).replace(":00", "");
const dayHour = d => d.toLocaleString([], { weekday: "short", hour: "numeric" });

// Articles per time bin, from the first article to the scan.
function binCoverage(articles, endIso, maxBins = 24) {
  const times = articles.filter(a => a.published).map(a => ({ t: new Date(a.published).getTime(), a }));
  if (!times.length) return [];
  const end = new Date(endIso).getTime(), start = Math.min(...times.map(x => x.t));
  const hour = 3600e3;
  const size = Math.max(1, Math.ceil((end - start) / hour / maxBins)) * hour;
  const n = Math.max(1, Math.ceil((end - start + 1) / size));
  const bins = Array.from({ length: n }, (_, i) => ({ start: new Date(end - (n - i) * size), end: new Date(end - (n - i - 1) * size), items: [] }));
  for (const x of times) bins[Math.min(n - 1, Math.max(0, Math.floor((x.t - (end - n * size)) / size)))].items.push(x.a);
  return bins;
}

// Columns: <=24px, 4px rounded data-end square at the baseline, 2px surface gap.
function columnPath(x, y, w, h, r = 4) {
  if (h <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

function coverageChart(story, scannedAt) {
  const bins = binCoverage(story.articles, scannedAt);
  if (bins.length < 2) return null;
  const fig = el("figure", "chart");
  fig.append(el("h3", "chart-title", "How the coverage built"));
  const hours = Math.round((bins[1].start - bins[0].start) / 3600e3);
  fig.append(el("p", "chart-sub", `Articles published, every ${hours === 1 ? "hour" : hours + " hours"}, up to the latest scan`));
  const wrap = el("div", "chart-wrap");
  const tip = el("div", "chart-tip");
  tip.setAttribute("role", "status");
  fig.append(wrap);
  const max = Math.max(...bins.map(b => b.items.length));
  const peak = bins.reduce((m, b, i) => (b.items.length > bins[m].items.length ? i : m), 0);

  // Drawn at the container's real width, so 11px text stays 11px on a phone.
  fig.draw = () => {
    const W = Math.max(260, Math.round(wrap.clientWidth)), H = 150, pad = { t: 22, b: 26 };
    const band = W / bins.length, bw = Math.max(2, Math.min(24, band - 2));
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart-svg", role: "group",
      "aria-label": `Articles over time. Peak: ${max} articles around ${dayHour(bins[peak].start)}.` });
    svg.append(svgEl("line", { x1: 0, x2: W, y1: H - pad.b + 0.5, y2: H - pad.b + 0.5, class: "chart-base" }));
    bins.forEach((b, i) => {
      const h = max ? (b.items.length / max) * (H - pad.t - pad.b) : 0;
      const x = i * band + (band - bw) / 2, y = H - pad.b - h;
      const g = svgEl("g", { class: "col", tabindex: 0, role: "img",
        "aria-label": `${plural(b.items.length, "article", "articles")}, ${dayHour(b.start)} to ${hourLabel(b.end)}` });
      g.append(svgEl("rect", { x: i * band, y: pad.t - 6, width: band, height: H - pad.t - pad.b + 6, class: "hit" }));
      if (h > 0) g.append(svgEl("path", { d: columnPath(x, y, bw, h), class: "mark" }));
      const show = () => {
        tip.replaceChildren(el("strong", null, plural(b.items.length, "article", "articles")),
          el("span", null, `${dayHour(b.start)} to ${hourLabel(b.end)}`));
        const outs = [...new Set(b.items.map(a => a.source))].sort();
        if (outs.length) tip.append(el("span", "chart-tip-src", listNames(outs, 3)));
        tip.classList.add("on");
        // Keep the tooltip inside the chart: centered on the column, clamped at both edges.
        const tw = tip.offsetWidth, cx = x + bw / 2;
        tip.style.left = `${Math.max(0, Math.min(W - tw, cx - tw / 2))}px`;
      };
      const hide = () => tip.classList.remove("on");
      g.addEventListener("pointerenter", show); g.addEventListener("focus", show);
      g.addEventListener("pointerleave", hide); g.addEventListener("blur", hide);
      svg.append(g);
    });
    const label = svgEl("text", { x: Math.max(8, Math.min(W - 8, peak * band + band / 2)), y: pad.t - 8, class: "chart-label", "text-anchor": "middle" });
    label.textContent = String(max);
    const startLabel = svgEl("text", { x: 0, y: H - 8, class: "chart-axis" });
    startLabel.textContent = dayHour(bins[0].start);
    const endLabel = svgEl("text", { x: W, y: H - 8, class: "chart-axis", "text-anchor": "end" });
    endLabel.textContent = "Latest scan";
    svg.append(label, startLabel, endLabel);
    wrap.replaceChildren(svg, tip);
  };
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(fig.draw, 120); });

  // The same numbers as a table, for screen readers.
  const table = el("table", "sr-only");
  const head = el("tr");
  head.append(el("th", null, "From"), el("th", null, "Articles"));
  table.append(head);
  for (const b of bins) { const r = el("tr"); r.append(el("td", null, dayHour(b.start)), el("td", null, String(b.items.length))); table.append(r); }
  fig.append(table);
  return fig;
}

// A meter: how many of the outlets covering the story state this fact.
function agreementMeter(fact, total) {
  const n = fact.reported_by.length;
  const wrap = el("div", "meter-row");
  const track = el("span", "meter-track");
  track.setAttribute("role", "img");
  track.setAttribute("aria-label", `Stated by ${n} of ${total} outlets covering this story: ${fact.reported_by.join(", ")}`);
  const fill = el("span", "meter-fill");
  fill.style.width = `${Math.min(100, (n / Math.max(total, 1)) * 100)}%`;
  track.append(fill);
  track.title = fact.reported_by.join(", ");
  wrap.append(track, el("span", "meter-text", `Stated by ${n} of ${total} outlets`));
  return wrap;
}

// Sparkline for a Today card: articles over the last 48 hours, in 12 bins.
function sparkline(story, scannedAt) {
  const end = new Date(scannedAt).getTime(), size = 4 * 3600e3, n = 12;
  const counts = Array(n).fill(0);
  for (const a of story.articles) {
    if (!a.published) continue;
    const i = n - 1 - Math.floor((end - new Date(a.published).getTime()) / size);
    if (i >= 0 && i < n) counts[i]++;
  }
  const max = Math.max(...counts);
  if (!max) return null;
  const W = 96, H = 24, band = W / n, bw = band - 2;
  const peakAgo = (n - 1 - counts.indexOf(max)) * 4;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "spark", role: "img",
    "aria-label": `Coverage over the last 48 hours, most articles ${peakAgo ? `about ${peakAgo} hours ago` : "in the last 4 hours"}` });
  counts.forEach((c, i) => {
    const h = Math.max(c ? 3 : 1, (c / max) * H);
    const r = svgEl("path", { d: columnPath(i * band + 1, H - h, bw, h, 2), class: c ? "mark" : "empty" });
    const t = svgEl("title"); t.textContent = `${plural(c, "article", "articles")}, ${(n - i) * 4} to ${(n - i - 1) * 4} hours ago`;
    r.append(t);
    svg.append(r);
  });
  return svg;
}

/* ---------- Today ---------- */

// A license-verified photo with its caption: what, who made it, license, source. Text never sits on it.
function figure(img, cls) {
  const f = el("figure", cls);
  const im = el("img");
  im.src = img.src; im.alt = img.alt; im.loading = "lazy"; im.decoding = "async";
  f.append(im);
  const cap = el("figcaption");
  const a = el("a", null, img.caption);
  a.href = img.source; a.rel = "noopener";
  cap.append(a);
  f.append(cap);
  return f;
}

function storyCard(story, i, data) {
  const li = el("li", i === 0 ? "story story-lead" : "story");
  if (i === 0 && story.image) li.append(figure(story.image, "lead-photo"));
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
  const meta = el("span", "foot-meta");
  const spark = sparkline(story, data.scanned_at);
  if (spark) meta.append(spark);
  meta.append(el("span", "sources-line", `${plural(story.articles.length, "article", "articles")} · ${listNames(story.sources, 3)}`));
  foot.append(meta);
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
  if (story.image) $("story-sub").append(figure(story.image, "story-photo"));

  const brief = story.brief;
  const agreed = (brief && brief.agreed) || [];

  // 1. The story the coverage agrees on.
  const s1 = el("section", "block");
  s1.append(el("h2", "block-title", "The story"));
  if (agreed.length) {
    const ul = el("ul", "facts");
    for (const f of agreed) {
      const li = el("li");
      li.append(el("p", "story-text", f.fact), agreementMeter(f, story.sources.length));
      ul.append(li);
    }
    s1.append(ul);
  } else {
    s1.append(el("p", "story-text muted", "Being summarized. The facts the coverage agrees on will appear here."));
  }
  body.append(s1);
  const chart = coverageChart(story, data.scanned_at);
  if (chart) { const sc = el("section", "block"); sc.append(chart); body.append(sc); chart.draw(); }

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
