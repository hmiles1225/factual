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

// Every check attached to a story's differences: one per side's claim, plus older story-level ones.
function checksIn(story, lib) {
  const out = [];
  for (const d of (story.brief && story.brief.differences) || []) {
    for (const k of [d.check, ...d.positions.map(p => p.check)]) {
      const c = claimOf(lib, k);
      if (c) out.push(c);
    }
  }
  return out;
}
// For Today cards: only checks the evidence decided.
function decided(story, lib) {
  return checksIn(story, lib).filter(c => DECIDED.includes(c.verdict)).map(c => ({ c }));
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


// Spectrum: each outlet is a dot on a left-to-right line, placed by its audience (Pew: share of
// Republican users). Gray only; groups are told apart by fill vs hollow, never by color.
const leanLabel = v => v < 0.4 ? "left-leaning" : v > 0.6 ? "right-leaning" : "center";
function spectrum(points, legend, ariaLabel) {
  // points: [{name, lean, style: "fill" | "hollow" | "ghost"}]
  const fig = el("figure", "spectrum");
  const wrap = el("div", "spectrum-wrap");
  const tip = el("div", "chart-tip");
  tip.setAttribute("role", "status");
  fig.append(wrap);
  if (legend && legend.length) {
    const lg = el("div", "spectrum-legend");
    for (const [style, text] of legend) { const k = el("span", "key"); k.append(el("i", `dot ${style}`), el("span", null, text)); lg.append(k); }
    fig.append(lg);
  }
  fig.draw = () => {
    const W = Math.max(260, Math.round(wrap.clientWidth)), padX = 14, axisY = 34, r = 6;
    const x = v => padX + v * (W - 2 * padX);
    // Simple stacking so dots never hide each other: each row holds dots at least 2r+3 apart.
    const rows = [], placed = [];
    for (const p of [...points].sort((a, b) => a.lean - b.lean)) {
      const px = x(p.lean);
      let row = rows.findIndex(last => px - last >= 2 * r + 3);
      if (row < 0) { rows.push(px); row = rows.length - 1; } else rows[row] = px;
      placed.push({ ...p, px, py: axisY - 12 - row * (2 * r + 3) });
    }
    const top = Math.min(...placed.map(p => p.py)) - r - 6;
    const H = axisY + 22 - Math.min(0, top);
    const shift = Math.max(0, -top);
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart-svg", role: "group", "aria-label": ariaLabel });
    const ay = axisY + shift;
    svg.append(svgEl("line", { x1: padX, x2: W - padX, y1: ay + 0.5, y2: ay + 0.5, class: "chart-base" }));
    for (const [v, t, anchor] of [[0, "Left", "start"], [0.5, "Center", "middle"], [1, "Right", "end"]]) {
      svg.append(svgEl("line", { x1: x(v), x2: x(v), y1: ay - 3, y2: ay + 4, class: "chart-base" }));
      const lab = svgEl("text", { x: x(v), y: ay + 18, class: "chart-axis", "text-anchor": anchor });
      lab.textContent = t;
      svg.append(lab);
    }
    for (const p of placed) {
      const g = svgEl("g", { class: "dotg", tabindex: 0, role: "img",
        "aria-label": `${p.name}: ${p.note || leanLabel(p.lean)} (audience ${Math.round(p.lean * 100)}% Republican)` });
      g.append(svgEl("circle", { cx: p.px, cy: p.py + shift, r: 12, class: "hit" }));
      g.append(svgEl("circle", { cx: p.px, cy: p.py + shift, r, class: `dot ${p.style}` }));
      const show = () => {
        tip.replaceChildren(el("strong", null, p.name), el("span", null, `${p.note ? p.note + " · " : ""}audience ${Math.round(p.lean * 100)}% Republican`));
        tip.classList.add("on");
        const tw = tip.offsetWidth;
        tip.style.left = `${Math.max(0, Math.min(W - tw, p.px - tw / 2))}px`;
        tip.style.top = `${p.py + shift - 12}px`;
      };
      const hide = () => tip.classList.remove("on");
      g.addEventListener("pointerenter", show); g.addEventListener("focus", show);
      g.addEventListener("pointerleave", hide); g.addEventListener("blur", hide);
      svg.append(g);
    }
    wrap.replaceChildren(svg, tip);
  };
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(fig.draw, 120); });
  return fig;
}

// Name a group of outlets by where their audiences sit, from Pew data, never by hand.
function sideName(outlets, leanOf) {
  const vals = outlets.map(o => leanOf[o]).filter(v => v != null);
  if (!vals.length) return "Outlets";
  const left = vals.filter(v => v < 0.4).length, right = vals.filter(v => v > 0.6).length;
  if (left === vals.length) return "Left-leaning outlets";
  if (right === vals.length) return "Right-leaning outlets";
  if (left && right) return "Outlets on both sides";
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  return avg < 0.4 ? "Mostly left-leaning outlets" : avg > 0.6 ? "Mostly right-leaning outlets" : "Center and mixed outlets";
}

// "By the numbers": figures the checker found, each verified in code to appear in its quote.
function statTiles(figures) {
  const row = el("div", "stats");
  for (const f of figures) {
    const t = el("div", "stat");
    t.append(el("span", "stat-value", f.value), el("span", "stat-unit", f.unit), el("span", "stat-label", f.label));
    const a = el("a", "stat-src", `${f.source} ↗`);
    a.href = f.url; a.rel = "noopener";
    t.append(a);
    row.append(t);
  }
  return row;
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

function claimDetails(c) {
  const det = el("details", "check-row");
  const sum = el("summary");
  sum.append(chip(c.verdict), el("span", "check-claim", c.claim));
  det.append(sum);
  const body = el("div", "check-body");
  if (c.steelman) body.append(el("p", "why", `Why this sounds right: ${c.steelman}`));
  if (c.figures && c.figures.length) body.append(statTiles(c.figures));
  if (c.finding) body.append(el("p", "finding", c.finding));
  if (c.note) body.append(el("p", "check-note", c.note));
  if (c.evidence && c.evidence.length) {
    const ul = el("ul", "evidence");
    for (const e of c.evidence) {
      const li = el("li");
      li.append(el("span", "ev-quote", `\u201c${e.quote}\u201d`));
      const src = el("a", "ev-src", `${e.publisher}${e.published ? ", " + e.published : ""} \u2197`);
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

// Does a disagreement follow the left-right line? Read from where each version's outlets sit, never by hand.
function splitLine(pos, leanOf) {
  const avg = p => { const v = p.outlets.map(o => leanOf[o]).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const [a, b] = pos.map(avg);
  if (a == null || b == null) return null;
  const shared = pos[0].outlets.filter(o => pos[1].outlets.includes(o));
  const both = shared.length ? ` ${listNames(shared, 3)} reported both.` : "";
  if (Math.min(a, b) < 0.45 && Math.max(a, b) > 0.55) {
    const left = a < b ? 1 : 2;
    return `This one splits along left and right: version ${left} comes mostly from left-leaning outlets, version ${3 - left} from right-leaning ones.${both}`;
  }
  const n = [sideName(pos[0].outlets, leanOf), sideName(pos[1].outlets, leanOf)];
  const same = n[0] === n[1] && /^(Left|Right)-leaning/.test(n[0]) ? n[0].toLowerCase() : "outlets with similar audiences";
  return `Not a left-right split: both versions come from ${same}.${both}`;
}

// One disagreement: the point, whether it is partisan, and each version with where its outlets sit and its claim checked.
function differenceBlock(d, lib, leanOf) {
  const art = el("article", "diff");
  art.append(el("h3", "diff-point", d.point));
  const pos = d.positions.slice(0, 2);
  const line = pos.length === 2 ? splitLine(pos, leanOf) : null;
  if (line) art.append(el("p", "diff-split", line));
  const cols = el("div", "sides");
  pos.forEach((p, i) => {
    const col = el("div", "side");
    col.append(el("p", "side-name", `Version ${i + 1} \u00b7 ${sideName(p.outlets, leanOf)}`), el("p", "side-says", p.says));
    const pts = p.outlets.filter(o => leanOf[o] != null).map(o => ({ name: o, lean: leanOf[o], style: "fill", note: `version ${i + 1}` }));
    if (pts.length) col.append(spectrum(pts, null, `Version ${i + 1} outlets by audience: ${p.outlets.join(", ")}`));
    col.append(el("p", "side-outlets", listNames(p.outlets, 4)));
    const c = claimOf(lib, p.check);
    if (c) col.append(claimDetails(c));
    else if (p.checkable_claim) col.append(el("p", "side-pending", "Checking this version\u2019s claim against primary sources."));
    cols.append(col);
  });
  art.append(cols);
  const shared = claimOf(lib, d.check);  // older briefs: one claim for the whole difference
  if (shared) art.append(claimDetails(shared));
  return art;
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

  // 2. Who covered it: every outlet we read, placed by its audience; filled if it covered this story.
  const leanOf = Object.fromEntries((data.feeds || []).filter(f => f.lean != null).map(f => [f.source, f.lean]));
  const placed = (data.feeds || []).filter(f => f.ok && f.lean != null);
  if (placed.length) {
    const sc = el("section", "block");
    sc.append(el("h2", "block-title", "Who covered it"));
    const covered = new Set(story.sources);
    const fig = spectrum(placed.map(f => ({ name: f.source, lean: f.lean, style: covered.has(f.source) ? "fill" : "ghost",
      note: covered.has(f.source) ? "covered this" : "did not cover this" })),
      [["fill", "Covered this story"], ["ghost", "Did not"]],
      `Outlets that covered this story, placed by audience: ${story.sources.join(", ")}`);
    sc.append(fig);
    const unplaced = story.sources.filter(o => leanOf[o] == null);
    const who = sideName(story.sources, leanOf);
    if (/^(Left|Right)-leaning/.test(who)) fig.before(el("p", "diff-split", `Only ${who.toLowerCase()} covered this story.`));
    sc.append(el("p", "block-note", `Each dot is an outlet we read, placed by the share of its regular audience who are Republican (Pew Research Center, 2025).${unplaced.length ? ` Also covered by ${listNames(unplaced, 4)}, which Pew did not survey.` : ""}`));
    body.append(sc);
    fig.draw();
  }

  // 3. Where left and right differ, with each side's factual claim checked where possible.
  const diffs = (brief && brief.differences) || [];
  if (diffs.length) {
    const s3 = el("section", "block");
    s3.append(el("h2", "block-title", "Where the coverage differs"));
    for (const d of diffs) {
      const blockEl = differenceBlock(d, data.library, leanOf);
      s3.append(blockEl);
    }
    body.append(s3);
    s3.querySelectorAll(".spectrum").forEach(f => f.draw && f.draw());
  }

  // Values questions are the reader's to decide.
  const values = (brief && brief.values_questions) || [];
  if (values.length) {
    const sv = el("section", "block");
    sv.append(el("h2", "block-title", "Yours to decide"));
    const ul = el("ul", "open-list");
    for (const q of values) { const li = el("li"); li.append(el("p", "open-point", q)); ul.append(li); }
    sv.append(ul, el("p", "block-note", "Values questions get no verdict. The facts above are the same whichever way you answer."));
    body.append(sv);
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
