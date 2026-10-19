// Renders the latest scan: Today (index.html), one story (story.html?s=<id>[&d=<day>]) and the
// archive (archive.html), which keeps every story that was on Today, by day.
// Every string from a feed or a model goes in through textContent, never innerHTML,
// so a headline or a claim can't inject markup.
//
// Reading order on every story: common ground (what both sides report), who covered it and when,
// where the left and the right differ with each side's claim checked, then the values questions.
"use strict";

const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen"];
// Today's sections. Politics moves by the day; the others are grouped over the week.
const TOPICS = [
  { key: "politics", name: "Politics", span: "Today" },
  { key: "environment", name: "Environment", span: "This week" },
  { key: "science", name: "Science", span: "This week" },
  { key: "health", name: "Health", span: "This week" },
];
const topicName = k => (TOPICS.find(t => t.key === k) || { name: "" }).name;
const DECIDED = ["Holds up", "Missing context", "Doesn't hold up"];

// Verdicts: always a glyph and a word, never color alone (Figma Foundations 5:119).
const VERDICT = {
  "Holds up": { cls: "hold", glyph: "✓", label: "Confirmed" },   // stored as "Holds up"; readers see Confirmed
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
const storyHref = (story, day) => `story.html?s=${encodeURIComponent(story.sid)}${day ? `&d=${day}` : ""}`;
const dayName = d => new Date(`${d}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
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
  c.append(el("span", "chip-glyph", v.glyph), el("span", "chip-word", v.label || verdict));
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

// Spectrum: each outlet is a dot on a left-to-right line, placed by how its use splits between
// Republicans and Democrats (Pew). Gray only; groups are told apart by fill vs hollow, never by color.
const leanLabel = v => v < 0.4 ? "left-leaning" : v > 0.6 ? "right-leaning" : "center";
// What Pew measured, stated symmetrically: how much more likely one party's members are to get news
// from the outlet than the other's. No party is the baseline. (lean = Rep% / (Rep% + Dem%).)
let PEW = {};  // outlet -> Pew's own percentages, set from the scan, so ratios are exact
function leanPhrase(v, name) {
  const pw = PEW[name];
  if (pw) v = pw.rep / (pw.rep + pw.dem);
  const r = v >= 0.5 ? v / (1 - v) : (1 - v) / v;
  if (r < 1.15) return "used about equally by Democrats and Republicans";
  const x = r >= 10 ? Math.round(r) : Math.round(r * 10) / 10;
  return v >= 0.5 ? `Republicans ${x}\u00d7 as likely as Democrats to get news here` : `Democrats ${x}\u00d7 as likely as Republicans to get news here`;
}
// AllSides gives a category, not a measurement: those outlets sit at their rating's position, drawn as
// squares so they are never mistaken for Pew's measured dots.
const RATING_POS = { "Left": 0.1, "Lean Left": 0.3, "Center": 0.5, "Lean Right": 0.7, "Right": 0.9 };
let ALLSIDES = {};  // outlet -> AllSides rating, for outlets Pew did not survey

function spectrum(points, legend, ariaLabel) {
  // points: [{name, lean | rating, style: "fill" | "hollow" | "ghost", note}]
  // Round dots: placed by Pew's audience data (lean). Squares: outlets Pew did not survey, at their
  // AllSides rating. One row, one Left / Center / Right axis.
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
    const W = Math.max(200, Math.round(wrap.clientWidth)), padX = 14, axisY = 34, r = 6, step = 2 * r + 3;
    const x = v => padX + v * (W - 2 * padX);
    const posOf = p => p.lean ?? RATING_POS[p.rating];
    // Dots never hide each other: each row keeps them a step apart, stacking upward.
    const rows = [], all = [];
    for (const p of points.filter(q => posOf(q) != null).sort((a, b) => posOf(a) - posOf(b))) {
      const px = x(posOf(p));
      let row = rows.findIndex(last => px - last >= step);
      if (row < 0) { rows.push(px); row = rows.length - 1; } else rows[row] = px;
      all.push({ ...p, px, row });
    }
    const ay = Math.max(axisY, 12 + rows.length * step + r);
    const H = ay + 22;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart-svg", role: "group", "aria-label": ariaLabel });
    svg.append(svgEl("line", { x1: padX, x2: W - padX, y1: ay + 0.5, y2: ay + 0.5, class: "chart-base" }));
    for (const [v, t, anchor] of [[0, "Left", "start"], [0.5, "Center", "middle"], [1, "Right", "end"]]) {
      svg.append(svgEl("line", { x1: x(v), x2: x(v), y1: ay - 3, y2: ay + 4, class: "chart-base" }));
      const lab = svgEl("text", { x: x(v), y: ay + 18, class: "chart-axis", "text-anchor": anchor });
      lab.textContent = t;
      svg.append(lab);
    }
    for (const p of all) {
      const cy = ay - 12 - p.row * step;
      const line2 = p.lean != null ? leanPhrase(p.lean, p.name) : `Rated ${p.rating} by AllSides (Pew did not survey it)`;
      const g = svgEl("g", { class: "dotg", tabindex: 0, role: "img", "aria-label": `${p.name}: ${p.note ? p.note + ". " : ""}${line2}` });
      g.append(svgEl("circle", { cx: p.px, cy, r: 12, class: "hit" }));
      g.append(p.lean == null
        ? svgEl("rect", { x: p.px - r + 0.5, y: cy - r + 0.5, width: 2 * r - 1, height: 2 * r - 1, rx: 2, class: `dot ${p.style}` })
        : svgEl("circle", { cx: p.px, cy, r, class: `dot ${p.style}` }));
      const show = () => {
        tip.replaceChildren(el("strong", null, p.note ? `${p.name} \u00b7 ${p.note}` : p.name), el("span", null, line2));
        tip.classList.add("on");
        const tw = tip.offsetWidth;
        tip.style.left = `${Math.max(0, Math.min(W - tw, p.px - tw / 2))}px`;
        tip.style.top = `${cy - 12}px`;
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
let SIDE = {};  // outlet -> left/center/right, placed in the scan from Pew, else AllSides
const sidesIn = outlets => new Set(outlets.map(o => SIDE[o]).filter(x => x && x !== "unplaced"));
function sideName(outlets, leanOf) {
  // Names exactly what is in the group, the same way for both sides. No averages, no "mostly".
  const has = sidesIn(outlets);
  if (!has.size) return "Outlets Pew did not survey";
  if (has.has("left") && has.has("right")) return "Outlets on both sides";
  const words = { left: "Left-leaning", center: "Center", right: "Right-leaning" };
  const list = ["left", "center", "right"].filter(k => has.has(k));
  return list.length === 1 ? `${words[list[0]]} outlets` : `${words[list[0]]} and ${words[list[1]].toLowerCase()} outlets`;
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

function storyCard(story, i, data, isLead) {
  const li = el("li", isLead ? "story story-lead" : "story");
  if (isLead && story.image) li.append(figure(story.image, "lead-photo"));
  const main = el("div", "story-main");
  main.append(el("p", "story-num", String(i + 1).padStart(2, "0")));
  const h = el("h2", "headline");
  const a = el("a", null, story.working_title);
  a.href = storyHref(story);
  h.append(a);
  main.append(h);

  const agreed = (story.brief && story.brief.agreed) || [];
  main.append(...storyProse(agreed, isLead ? 4 : 3, "gist"));
  li.append(main);

  const rows = decided(story, data.library).slice(0, 2);
  if (rows.length) {
    const ul = el("ul", "checks");
    for (const { c } of rows) {
      const r = el("li");
      const txt = el("div");
      txt.append(el("span", "check-claim", c.claim));
      const src = sourcesLine(c);
      if (src) txt.append(src);
      r.append(chip(c.verdict), txt);
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
  $("today-date").textContent = new Date(data.scanned_at).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  $("scanline").textContent = `Updated ${clock(data.scanned_at)}`;

  // Only stories with a written summary, chosen by the scan for Today (covered by both sides). Never a bare headline.
  const shown = s => s.related_to === null && s.on_today && s.brief && (s.brief.agreed || []).some(acrossSides);
  let total = 0;
  const nav = $("topic-nav");
  for (const t of TOPICS) {
    const list = data.stories.filter(s => shown(s) && s.topic === t.key);
    total += list.length;
    const sec = el("section", "topic-section");
    sec.id = t.key;
    const head = el("div", "topic-head");
    head.append(el("h2", "topic-name", t.name), el("p", "topic-span", `${t.span} \u00b7 ${list.length ? `${WORDS[list.length] || list.length} ${list.length === 1 ? "story" : "stories"}` : "none yet"}`));
    sec.append(head);
    if (list.length) {
      const ol = el("ol", "stories");
      ol.setAttribute("aria-label", `${t.name} stories`);
      list.forEach((s, i) => ol.append(storyCard(s, i, data, t.key === "politics" && i === 0)));
      sec.append(ol);
    } else {
      sec.append(el("p", "topic-empty", `No ${t.name.toLowerCase()} story ${t.span === "Today" ? "today" : "this week"} has been covered by both left- and right-leaning outlets yet. We only summarize stories both sides are covering.`));
    }
    $("sections").append(sec);
    const chip = el("a", "topic-chip", t.name);
    chip.href = `#${t.key}`;
    chip.append(el("span", "topic-count", String(list.length)));
    nav.append(chip);
  }
  $("today-count").textContent = WORDS[total] || String(total);

  const ok = feeds.filter(f => f.ok).sort((a, b) => a.source.localeCompare(b.source));
  $("feeds").append(el("p", "feeds-list", ok.map(f => f.source).join(", ")));
  const down = feeds.filter(f => !f.ok).map(f => f.source);
  if (down.length) $("feeds").append(el("p", "feeds-down", `Not reachable in the last scan: ${down.join(", ")}.`));
}

/* ---------- Archive ---------- */

function renderArchive(index) {
  const box = $("archive-days");
  const days = (index && index.days) || [];
  if (!days.length) { box.append(el("p", "topic-empty", "The archive starts with today. Stories are kept here once they have been on Today.")); return; }
  days.forEach((d, n) => {
    const det = el("details", "arch-day");
    const sum = el("summary");
    sum.append(el("span", "arch-date", dayName(d.date)), el("span", "arch-count", `${d.count} ${d.count === 1 ? "story" : "stories"}`));
    det.append(sum);
    const body = el("div", "arch-body");
    det.append(body);
    let loaded = false;
    det.addEventListener("toggle", () => {
      if (!det.open || loaded) return;
      loaded = true;
      getJSON(`data/archive/${d.date}.json`).then(arch => {
        const stories = Object.values(arch.stories || {});
        for (const t of TOPICS) {
          const list = stories.filter(s => s.topic === t.key);
          if (!list.length) continue;
          body.append(el("h3", "arch-topic", t.name));
          const ul = el("ul", "arch-list");
          for (const s of list) {
            const li = el("li");
            const a = el("a", "arch-link", s.working_title);
            a.href = storyHref(s, d.date);
            const cg = ((s.brief && s.brief.agreed) || []).filter(acrossSides).length;
            li.append(a, el("span", "arch-meta", `${s.sources.length} outlets${cg ? ` \u00b7 ${cg} common-ground ${cg === 1 ? "fact" : "facts"}` : ""}`));
            ul.append(li);
          }
          body.append(ul);
        }
      }).catch(() => body.append(el("p", "topic-empty", "This day could not be loaded.")));
    });
    if (n === 0) det.open = true;
    box.append(det);
  });
}

/* ---------- One story ---------- */

// The sources a check rests on, always visible: one link per page, publisher named.
function sourcesLine(c) {
  const seen = new Set(), links = [];
  for (const e of c.evidence || []) {
    if (!e.url || seen.has(e.url)) continue;
    seen.add(e.url);
    const a = el("a", "src-link", `${e.publisher} \u2197`);
    a.href = e.url;
    a.rel = "noopener";
    links.push(a);
  }
  if (!links.length) return null;
  const p = el("p", "check-sources");
  p.append(el("span", null, links.length === 1 ? "Source: " : "Sources: "));
  links.slice(0, 4).forEach((a, i) => { if (i) p.append(document.createTextNode(" \u00b7 ")); p.append(a); });
  if (links.length > 4) p.append(document.createTextNode(` and ${links.length - 4} more`));
  return p;
}

function claimDetails(c) {
  const wrap = el("div", "check");
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
  wrap.append(det);
  // Partly confirmed: say plainly what the sources do establish and what they don't, so an Unproven
  // never reads as doubt about the part that is true.
  const missing = (c.note || "").match(/not all of it as stated:\s*(.+)$/);
  if (c.verdict === "Unproven" && c.support === "partial" && c.finding && missing) {
    const part = el("div", "check-partial");
    part.append(el("p", null, `Partly confirmed: ${c.finding.split(/(?<=[a-z0-9)\u201d"]\.)\s+(?=[A-Z])/)[0]}`),
      el("p", null, `Not established: ${missing[1].replace(/\.?$/, ".")}`));
    wrap.append(part);
  }
  const src = sourcesLine(c);
  if (src) wrap.append(src);
  return wrap;
}

// For ordering only (left account first): Pew position, else the middle of the outlet's AllSides side.
const meanLean = (outlets, leanOf) => { const v = outlets.map(o => leanOf[o] ?? { left: 0.2, center: 0.5, right: 0.8 }[SIDE[o]]).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };

// Does a disagreement follow the left-right line? Read from where each side's outlets sit, never by hand.
function splitLine(pos, leanOf) {
  const [a, b] = pos.map(p => sidesIn(p.outlets));
  if (!a.size || !b.size) return null;
  const shared = pos[0].outlets.filter(o => pos[1].outlets.includes(o));
  const both = shared.length ? ` ${listNames(shared, 3)} reported both.` : "";
  const only = (s, k, not) => s.has(k) && !s.has(not);
  if ((only(a, "left", "right") && only(b, "right", "left")) || (only(a, "right", "left") && only(b, "left", "right")))
    return `This one splits along left and right.${both}`;
  const n = pos.map(p => sideName(p.outlets, leanOf));
  const same = n[0] === n[1] && /^(Left|Right)-leaning/.test(n[0]) ? n[0].toLowerCase() : "outlets with similar audiences";
  return `Not a left-right split: both accounts come from ${same}.${both}`;
}

// The words that are the actual difference, in bold. The phrase was checked in code to be in the text.
function withCrux(node, text, crux) {
  text = text.charAt(0).toUpperCase() + text.slice(1);  // the summarizer sometimes starts mid-sentence
  const i = crux ? text.indexOf(crux) : -1;
  if (i < 0) { node.textContent = text; return node; }
  node.append(document.createTextNode(text.slice(0, i)), el("strong", null, crux), document.createTextNode(text.slice(i + crux.length)));
  return node;
}

// One disagreement: the point, whether it is partisan, and each side's account with where its outlets
// sit and its claim checked. The more left-leaning account always comes first, so left reads left.
function differenceBlock(d, lib, leanOf) {
  const art = el("article", "diff");
  art.append(el("h3", "diff-point", d.point));
  const pos = d.positions.slice(0, 2).sort((p, q) => (meanLean(p.outlets, leanOf) ?? 0.5) - (meanLean(q.outlets, leanOf) ?? 0.5));
  const line = pos.length === 2 ? splitLine(pos, leanOf) : null;
  if (line) art.append(el("p", "diff-split", line));
  const names = pos.map(p => sideName(p.outlets, leanOf));
  const heads = names.length === 2 && names[0] === names[1] ? [`Some ${names[0].toLowerCase()}`, `Other ${names[1].toLowerCase()}`] : names;
  const cols = el("div", "sides");
  pos.forEach((p, i) => {
    const col = el("div", "side");
    const head = el("p", "side-head");
    head.append(el("span", "side-tag", heads[i]), document.createTextNode(" say"));
    col.append(head, withCrux(el("p", "side-says"), p.says, p.crux));
    const pts = p.outlets.filter(o => leanOf[o] != null || ALLSIDES[o]).map(o => ({ name: o, lean: leanOf[o], rating: ALLSIDES[o], style: "fill", note: heads[i].toLowerCase() }));
    if (pts.length) col.append(spectrum(pts, null, `${heads[i]}: ${p.outlets.join(", ")}, placed by audience`));
    col.append(el("p", "side-outlets", listNames(p.outlets, 4)));
    const c = claimOf(lib, p.check);
    if (c) col.append(claimDetails(c));
    else if (p.checkable_claim) col.append(el("p", "side-pending", "Checking this claim against primary sources."));
    else if (p.no_claim) col.append(el("p", "side-pending", "Nothing to fact-check here: this account is about emphasis or framing, not a factual claim."));
    cols.append(col);
  });
  art.append(cols);
  const shared = claimOf(lib, d.check);  // older briefs: one claim for the whole difference
  if (shared) art.append(claimDetails(shared));
  return art;
}

// A fact is common ground when outlets on both the left and the right report it.
const acrossSides = f => (f.sides || []).includes("left") && (f.sides || []).includes("right");
// The story as prose, from facts outlets on both the left and the right report. Nothing else.
function storyProse(agreed, max, cls) {
  const facts = agreed.filter(acrossSides).slice(0, max);
  const out = [];
  let p = el("p", cls);
  facts.forEach((f, i) => {
    if (i && i % 4 === 0 && max > 4) { out.push(p); p = el("p", cls); }
    p.append(document.createTextNode((p.childNodes.length ? " " : "") + f.fact));
  });
  if (facts.length) out.push(p);
  return out;
}

function renderStory(data) {
  const sid = new URLSearchParams(location.search).get("s");
  const story = data.stories.find(s => s.sid === sid);
  const body = $("story-body");
  if (!story) {
    $("story-title").textContent = "This story is no longer on Today, and we could not find it in the archive.";
    const back = el("a", "read-more", "See today's stories");
    back.href = "./";
    body.append(back);
    return;
  }
  document.title = `${story.working_title} · fACTUAL`;
  $("story-meta").textContent = `${topicName(story.topic) ? topicName(story.topic) + " \u00b7 " : ""}${data.archiveDay ? `From the archive \u00b7 ${dayName(data.archiveDay)}` : `Updated ${clock(data.scanned_at)}`}`;
  $("story-title").textContent = story.working_title;
  $("story-sub").append(el("p", "byline", `Headline from ${lead(story).source}`));
  if (story.image) $("story-sub").append(figure(story.image, "story-photo"));

  const brief = story.brief;
  const agreed = (brief && brief.agreed) || [];

  const leanOf = Object.fromEntries((data.feeds || []).filter(f => f.lean != null).map(f => [f.source, f.lean]));
  PEW = Object.fromEntries((data.feeds || []).filter(f => f.pew).map(f => [f.source, f.pew]));
  SIDE = Object.fromEntries((data.feeds || []).map(f => [f.source, f.side]));
  ALLSIDES = Object.fromEntries((data.feeds || []).filter(f => f.lean == null && f.allsides).map(f => [f.source, f.allsides]));
  // 1. The story: every fact several outlets confirm, both-sides facts first, one-side facts tagged.
  // 1. The story: only facts outlets on both the left and the right report.
  if (agreed.some(acrossSides)) {
    const s1 = el("section", "block story-panel");
    s1.append(el("h2", "block-title", "The story"));
    s1.append(...storyProse(agreed, 12, "lede"));
    const by = [...new Set(agreed.filter(acrossSides).flatMap(f => f.reported_by))];
    s1.append(el("p", "block-note", `Every sentence here was reported by outlets on both the left and the right (${listNames(by, 6)}), and no outlet we read contradicted any of it.`));
    body.append(s1);
  }

  // 2. Where left and right differ, with each side's factual claim checked where possible.
  const diffs = (brief && brief.differences) || [];
  if (diffs.length) {
    const s3 = el("section", "block");
    s3.append(el("h2", "block-title", "Where the coverage differs"));
    for (const d of diffs) s3.append(differenceBlock(d, data.library, leanOf));
    body.append(s3);
    s3.querySelectorAll(".spectrum").forEach(f => f.draw && f.draw());
  }

  // 3. Who covered it: every outlet we read, placed by its audience; filled if it covered this story.
  const placed = (data.feeds || []).filter(f => f.ok && (f.lean != null || ALLSIDES[f.source]));
  if (placed.length) {
    const sc = el("section", "block");
    sc.append(el("h2", "block-title", "Who covered it"));
    const covered = new Set(story.sources);
    const fig = spectrum(placed.map(f => ({ name: f.source, lean: f.lean, rating: ALLSIDES[f.source], style: covered.has(f.source) ? "fill" : "ghost",
      note: covered.has(f.source) ? "covered this" : "did not cover this" })),
      [["fill", "Covered this story"], ["ghost", "Did not"], ["sq", "Square: placed by AllSides rating"]],
      `Outlets that covered this story, placed by audience: ${story.sources.join(", ")}`);
    sc.append(fig);
    const unplaced = story.sources.filter(o => leanOf[o] == null && !ALLSIDES[o]);
    const who = sideName(story.sources, leanOf);
    if (/^(Left|Right)-leaning outlets$/.test(who)) fig.before(el("p", "diff-split", `Only ${who.toLowerCase()} covered this story.`));
    sc.append(el("p", "block-note", `Each dot is an outlet we read. Toward the left, Democrats are more likely than Republicans to get news there; toward the right, Republicans are. Center outlets are used about equally (Pew Research Center, 2025). Squares are outlets Pew did not survey, placed at their AllSides rating (Left, Lean Left, Center, Lean Right, Right).${unplaced.length ? ` Also covered by ${listNames(unplaced, 4)}, which neither rates.` : ""}`));
    body.append(sc);
    fig.draw();
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
  ($("sections") || $("story-body") || $("archive-days")).after(box);
}

const getJSON = (url, optional) => fetch(url, { cache: "no-cache" })
  .then(r => { if (!r.ok) { if (optional) return null; throw new Error(r.status); } return r.json(); })
  .catch(e => { if (optional) return null; throw e; });

// An archived day, shaped like a scan so the story page can render it.
const fromArchive = (arch, day) => ({ stories: Object.values(arch.stories || {}), feeds: arch.feeds, scanned_at: arch.updated_at, archiveDay: day });

async function load() {
  const page = document.body.dataset.page;
  if (page === "archive") return renderArchive(await getJSON("data/archive/index.json", true));
  const library = getJSON("data/library.json", true);
  const params = new URLSearchParams(location.search);
  let data;
  if (page === "story" && params.get("d")) {
    data = fromArchive(await getJSON(`data/archive/${params.get("d")}.json`), params.get("d"));
  } else {
    data = await getJSON("data/stories.json");
    // A story that has left the live scan is still in the archive: look back up to a week.
    if (page === "story" && !data.stories.some(s => s.sid === params.get("s"))) {
      const index = await getJSON("data/archive/index.json", true);
      for (const d of ((index && index.days) || []).slice(0, 7)) {
        const arch = await getJSON(`data/archive/${d.date}.json`, true);
        if (arch && arch.stories && arch.stories[params.get("s")]) { data = fromArchive(arch, d.date); break; }
      }
    }
  }
  data.library = await library;
  (page === "story" ? renderStory : renderToday)(data);
}

load().catch(fail);
