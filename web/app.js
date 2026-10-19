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
const TOPICS = [  // in this order everywhere; the first five are followed until a reader chooses
  { key: "politics", name: "Politics", span: "Today" },
  { key: "texas", name: "Texas Election", span: "This week", local: "TX" },  // only with Local politics set to Texas
  { key: "elections", name: "Elections", span: "Today" },
  { key: "economy", name: "Economy", span: "Today" },
  { key: "immigration", name: "Immigration", span: "Today" },
  { key: "crime", name: "Crime & justice", span: "Today" },
  { key: "world", name: "World", span: "Today" },
  { key: "environment", name: "Energy & environment", span: "This week" },
  { key: "health", name: "Health", span: "This week" },
  { key: "tech", name: "AI & tech", span: "Today" },
  { key: "science", name: "Science", span: "This week" },
  { key: "education", name: "Education", span: "This week" },
];
const NATIONAL = TOPICS.filter(t => !t.local);
const DEFAULT_TOPICS = NATIONAL.slice(0, 5).map(t => t.key);
// Local politics: a state the reader picked (this device), or ?state=xx for this visit. The Texas demo
// edition runs to its cutoff; after it, ?state=tx with the investors' key opens the time capsule.
const STATES = { AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware",
  DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
  MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia",
  WI: "Wisconsin", WY: "Wyoming" };
let LOCAL_ON = false;   // set once the scan says a region edition is running (or a time capsule is open)
let CAPSULE = null;     // the frozen edition being shown, if any
const sget = (k, store) => { try { return (store || localStorage).getItem(k); } catch (e) { return null; } };
const sset = (k, v, store) => { try { if (v == null) (store || localStorage).removeItem(k); else (store || localStorage).setItem(k, v); } catch (e) {} };
const localState = () => sget("fx-state", sessionStorage) || sget("fx-local");
// The sections a reader follows, kept on this device only. null until they have chosen.
function chosenTopics() {
  try {
    const v = JSON.parse(localStorage.getItem("fx-topics"));
    if (Array.isArray(v)) { const keys = v.filter(k => NATIONAL.some(t => t.key === k)); if (keys.length) return keys; }
  } catch (e) {}
  return null;
}
function followedTopics() {
  const base = chosenTopics() || DEFAULT_TOPICS;
  const st = localState();
  if (!LOCAL_ON || !st) return base;
  // The local section sits right under Politics (or first, if Politics isn't followed).
  const at = base.indexOf("politics") + 1;
  return [...base.slice(0, at), st === "TX" ? "texas" : "local", ...base.slice(at)];
}
function saveTopics(keys) {
  try { localStorage.setItem("fx-topics", JSON.stringify(keys)); } catch (e) {}
  document.dispatchEvent(new CustomEvent("fx-topics"));
}
const topicName = k => (TOPICS.find(t => t.key === k) || { name: "" }).name;
const DECIDED = ["Holds up", "Missing context", "Doesn't hold up"];

// Verdicts: always a glyph and a word, never color alone (Figma Foundations 5:119).
const VERDICT = {
  "Holds up": { cls: "hold", glyph: "✓", label: "Confirmed" },   // stored as "Holds up"; readers see Confirmed
  "Missing context": { cls: "ctx", glyph: "◐" },
  "Doesn't hold up": { cls: "no", glyph: "✕", label: "False" },   // stored as "Doesn't hold up"; readers see False
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
  tip.setAttribute("aria-hidden", "true");
  // Touch has no hover, so the tooltip used to last only while a finger was held down. A tap now opens it
  // and rings the dot; it closes after TIP_MS, on a tap anywhere else, or when another dot is tapped.
  // Touching the tooltip itself restarts the time. A mouse keeps the hover behaviour.
  const TIP_MS = 5000;
  const closeTip = () => { clearTimeout(tip._t); tip.classList.remove("on"); wrap.querySelectorAll(".is-picked").forEach(n => n.classList.remove("is-picked")); };
  const holdTip = () => { clearTimeout(tip._t); tip._t = setTimeout(closeTip, TIP_MS); };
  tip.addEventListener("pointerup", e => { if (e.pointerType !== "mouse") holdTip(); });
  document.addEventListener("pointerdown", e => { if (tip.classList.contains("on") && !wrap.contains(e.target)) closeTip(); });
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
    // The picture is for sighted pointer users; every fact in it is also in text (the outlet list, the
    // outlets line), so the SVG is hidden from assistive tech and its dots are not tab stops.
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart-svg", "aria-hidden": "true" });
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
      const g = svgEl("g", { class: "dotg" });
      g.append(svgEl("circle", { cx: p.px, cy, r: 12, class: "hit" }));
      g.append(svgEl("circle", { cx: p.px, cy, r: r + 3.5, class: "ring" }));
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
      // WCAG 1.4.13: the tooltip stays while the pointer moves onto it, and Escape dismisses it.
      const hide = () => { clearTimeout(tip._t); tip._t = setTimeout(() => { if (!tip.matches(":hover")) tip.classList.remove("on"); }, 150); };
      g.addEventListener("pointerenter", e => { if (e.pointerType !== "mouse") return; clearTimeout(tip._t); if (!tip._dismissed) show(); });
      g.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") hide(); });
      g.addEventListener("pointerup", e => {
        if (e.pointerType === "mouse") return;
        closeTip();
        show();
        g.classList.add("is-picked");
        holdTip();
      });
      svg.append(g);
    }
    tip.onpointerleave = () => tip.classList.remove("on");
    wrap.replaceChildren(svg, tip);
  };
  // Escape closes it and keeps it closed until the pointer leaves the chart, so the dot under the pointer
  // doesn't reopen it at once.
  document.addEventListener("keydown", e => { if (e.key === "Escape" && tip.classList.contains("on")) { tip.classList.remove("on"); tip._dismissed = true; } });
  wrap.addEventListener("pointerleave", () => { tip._dismissed = false; });
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(fig.draw, 120); });
  return fig;
}

// Name a group of outlets by where their audiences sit, from Pew data, never by hand.
let ARTICLE = {};  // outlet -> its article in the story on screen, so a name can link to what it said
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
function figure(img, cls, href) {
  const f = el("figure", cls);
  const im = el("img");
  im.src = img.src; im.alt = img.alt; im.loading = "lazy"; im.decoding = "async";
  if (href) {
    // On Today the picture opens the story too. The headline is the one link screen readers and the
    // keyboard use, so this one is skipped by both instead of repeating it.
    const a = el("a", "photo-link");
    a.href = href; a.tabIndex = -1; a.setAttribute("aria-hidden", "true");
    a.append(im);
    f.append(a);
  } else f.append(im);
  const cap = el("figcaption");
  const a = el("a", null, img.caption);
  a.href = img.source; a.rel = "noopener";
  cap.append(a);
  f.append(cap);
  return f;
}

// The numbers that lead every story: outlets, facts both sides report, splits, loaded words.
function metrics(story) {
  const b = story.brief || {};
  const n = (b.differences || []).length;
  return [[story.sources.length, "outlets"], [(b.agreed || []).filter(acrossSides).length, "agreed"],
    [n, n === 1 ? "split" : "splits"], [(b.loaded || []).length, "loaded"]];
}
function metricRow(story, cls) {
  const ul = el("ul", cls);
  const tiles = cls.includes("tiles");
  for (const [n, l] of metrics(story)) {
    const li = el("li", l === "agreed" ? "is-agreed" : null);
    li.append(el("span", "m-n", String(n)), document.createTextNode(" "), el("span", "m-l", l === "loaded" && !tiles ? (n === 1 ? "loaded word" : "loaded words") : l));
    ul.append(li);
  }
  return ul;
}

// Each number at the top of a story jumps to its section, when that section is on the page.
const TILE_TARGET = { outlets: "outlets", agreed: "agreed", split: "splits", splits: "splits", loaded: "loaded" };
function linkTiles(ul) {
  if (!ul) return;
  for (const li of ul.children) {
    const id = TILE_TARGET[li.querySelector(".m-l").textContent];
    if (!id || !document.getElementById(id) || li.querySelector(".m-n").textContent === "0") continue;
    const a = el("a", "tile-link");
    a.href = `#${id}`;
    a.append(...li.childNodes);
    li.append(a);
    li.classList.add("is-link");
  }
}

// When a story broke: its first article. Shown on every card, since Today is in this order.
const brokeAt = s => Math.min(...s.articles.map(a => Date.parse(a.published) || Infinity));
function brokeAgo(s) {
  const t = brokeAt(s);
  if (!isFinite(t)) return null;
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 60) return `Broke ${Math.max(m, 1)} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `Broke ${h}h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "Broke yesterday" : `Broke ${d} days ago`;
}

// Photo subjects already on the home page, top to bottom. A repeat uses the story's second picture, or none.
let SHOWN = new Set();
function photoFor(story) {
  for (const img of [story.image, story.image_alt]) if (img && !SHOWN.has(img.subject)) { SHOWN.add(img.subject); return img; }
  return null;
}

// The first sentence of a text. A period after a title or an initial ("Rep.", "U.S.") doesn't end one.
const ABBREV = /\b(?:Rep|Reps|Sen|Sens|Gov|Lt|Dr|Mr|Mrs|Ms|St|Jr|Sr|Gen|Col|Sgt|Capt|Adm|Rev|Prof|No|vs|Inc|Co|Corp|Mt|Ft|Jan|Feb|Mar|Apr|Aug|Sep|Sept|Oct|Nov|Dec|[A-Z])\.$/;
function firstSentence(text) {
  const re = /[.!?][\u201d"]?\s+(?=[A-Z\u201c"])/g;
  let m;
  while ((m = re.exec(text))) {
    const end = m.index + m[0].trimEnd().length;
    if (!ABBREV.test(text.slice(0, m.index + 1))) return text.slice(0, end);
  }
  return text;
}

function storyCard(story, i, data, isLead) {
  const li = el("li", isLead ? "story story-lead" : "story");
  // The first story in each section shows its photo, when it has one, and never one already shown higher up.
  const img = (isLead || i === 0) ? photoFor(story) : null;
  if (img) li.append(figure(img, isLead ? "lead-photo" : "card-photo", storyHref(story)));
  const main = el("div", "story-main");
  const when = brokeAgo(story);
  if (when) main.append(el("p", "story-when", when));
  main.append(metricRow(story, "metrics"));
  const h = el("h2", "headline");
  const a = el("a", null, story.working_title);
  a.href = storyHref(story);
  h.append(a);
  main.append(h);
  // The first story in each section carries its summary; the rest are headline, time and counts only.
  // One sentence: the first thing outlets on both sides report.
  if (isLead || i === 0) {
    const first = ((story.brief && story.brief.agreed) || []).find(acrossSides);
    if (first) main.append(el("p", "gist", firstSentence(first.fact)));
  }
  li.append(main);
  return li;
}

function renderToday(data) {
  const feeds = data.feeds || [];
  $("scanline").replaceChildren(el("span", "sr-only", "Live. Updated "), document.createTextNode(clock(data.scanned_at)),
    el("span", "scan-extra", ` \u00b7 ${feeds.filter(f => f.ok && !f.region).length} outlets`));
  if (CAPSULE) $("scanline").replaceChildren(el("span", "sr-only", "Frozen. "), document.createTextNode("Time capsule"));

  TODAY = data;
  drawToday();
  document.addEventListener("fx-topics", drawToday);
  // Coming back from a story: Today is drawn after the browser would restore the scroll, so keep the
  // position ourselves (this tab only) and put it back once the stories are on the page.
  try { history.scrollRestoration = "manual"; } catch (e) {}
  const nav = (performance.getEntriesByType("navigation")[0] || {}).type;
  let y = null;
  try { y = sessionStorage.getItem("fx-today-y"); } catch (e) {}
  if (nav === "back_forward" && y && !location.hash) window.scrollTo({ top: +y, behavior: "instant" });
  else if (location.hash) { const target = document.getElementById(decodeURIComponent(location.hash.slice(1))); if (target) target.scrollIntoView({ behavior: "instant" }); }
  window.addEventListener("pagehide", () => { try { sessionStorage.setItem("fx-today-y", String(Math.round(window.scrollY))); } catch (e) {} });
}

let TODAY = null;
// Only stories with a written summary, chosen by the scan for Today (covered by both sides). Never a bare headline.
const shownToday = s => s.related_to === null && s.on_today && s.brief && (s.brief.agreed || []).some(acrossSides);

function drawToday() {
  const data = TODAY;
  const follow = new Set(followedTopics());
  SHOWN = new Set();
  const nav = $("topic-nav");
  nav.replaceChildren();
  $("sections").replaceChildren();
  drawPicker();
  let total = 0;
  const order = TOPICS.filter(t => follow.has(t.key));
  if (follow.has("local")) order.splice(order.findIndex(t => t.key === "politics") + 1, 0, { key: "local", name: `${STATES[localState()] || "Local"} Election`, span: "" });
  for (const t of order) {
    // A national story that is mostly the same articles as a Texas race shows once, in Texas Election.
    const ranked = data.stories.filter(s => shownToday(s) && s.topic === t.key && !(follow.has("texas") && s.also_in === "texas"));
    // Newest first, all of it (Heston): a ranked lead jumped around as later scans found more outlets.
    const list = ranked.sort((a, b) => brokeAt(b) - brokeAt(a));
    total += list.length;
    const sec = el("section", "topic-section");
    sec.id = t.key;
    const head = el("div", "topic-head");
    head.append(el("h2", "topic-name", t.name), el("p", "topic-span", `${t.span} \u00b7 ${list.length}`));
    sec.append(head);
    if (list.length) {
      const ol = el("ol", "stories");
      ol.setAttribute("aria-label", `${t.name} stories`);
      list.forEach((s, i) => ol.append(storyCard(s, i, data, i === 0)));  // every section opens with a full-width lead
      sec.append(ol);
    } else {
      sec.append(el("p", "topic-empty", t.key === "local" ? `Local coverage is a Texas-only demo for now.` : `Nothing yet that both sides are covering.`));
    }
    $("sections").append(sec);
    const link = el("a", list.length ? "strip-link" : "strip-link is-empty", t.name);
    link.href = `#${t.key}`;
    link.dataset.key = t.key;
    link.append(el("span", "strip-n", String(list.length)));
    nav.append(link);
  }
  const edit = el("button", "strip-edit");
  edit.type = "button";
  edit.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h4M12 17h8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="16" cy="7" r="2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="10" cy="17" r="2" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
  edit.append(document.createTextNode("Edit"));
  edit.setAttribute("aria-label", "Edit topics");
  edit.addEventListener("click", () => openSettings("topic"));
  nav.append(edit);
  spyStrip();
  if ($("today-count")) $("today-count").textContent = WORDS[total] || String(total);
}

// The section strip stays pinned while reading and underlines the section in view (scroll-spy). The
// active name is kept visible inside the strip, which scrolls sideways on a phone.
let spyOn = false;
function spyStrip() {
  const nav = $("topic-nav");
  const update = () => {
    const links = [...nav.querySelectorAll(".strip-link")];
    if (!links.length) return;
    // The reading line: under the strip (phone, tablet), or under the header beside the index (wide screens).
    const rail = getComputedStyle(nav).flexDirection === "column";
    const line = rail ? document.querySelector(".masthead").getBoundingClientRect().bottom + 40 : nav.getBoundingClientRect().bottom + 24;
    let active = links[0];
    for (const a of links) { const sec = document.getElementById(a.dataset.key); if (sec && sec.getBoundingClientRect().top <= line) active = a; }
    for (const a of links) { if (a === active) a.setAttribute("aria-current", "location"); else a.removeAttribute("aria-current"); }
    const l = active.offsetLeft, r = l + active.offsetWidth;
    if (!rail && (l < nav.scrollLeft + 16 || r > nav.scrollLeft + nav.clientWidth - 16)) nav.scrollTo({ left: Math.max(0, l - 16), behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    nav.classList.toggle("more-right", nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4);
    nav.classList.toggle("more-left", nav.scrollLeft > 4);
  };
  update();
  if (spyOn) return;
  spyOn = true;
  let queued = false;
  const later = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; update(); }); } };
  window.addEventListener("scroll", later, { passive: true });
  window.addEventListener("resize", later);
  nav.addEventListener("scroll", () => { nav.classList.toggle("more-right", nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4); nav.classList.toggle("more-left", nav.scrollLeft > 4); }, { passive: true });
}

// First visit: choose what to follow, the first five already chosen. Not a modal: Today shows underneath.
function drawPicker() {
  const old = $("picker");
  if (chosenTopics() || CAPSULE || sget("fx-state", sessionStorage)) { if (old) old.remove(); return; }  // a demo link skips it
  if (old) return;
  const box = el("section", "picker");
  box.id = "picker";
  box.setAttribute("aria-labelledby", "picker-title");
  const h = el("h2", "picker-title", "What do you want to follow?");
  h.id = "picker-title";
  box.append(h, el("p", "picker-sub", "Choose any. You can change this any time in Settings."));
  const grid = el("div", "picker-grid");
  for (const t of NATIONAL) {
    const lab = el("label", "pick");
    const box2 = el("input");
    box2.type = "checkbox"; box2.value = t.key; box2.checked = DEFAULT_TOPICS.includes(t.key);
    lab.append(box2, el("span", null, t.name));
    grid.append(lab);
  }
  // Local politics, with its state, while an edition runs. Unchecked by default.
  let pickState = null;
  if (LOCAL_ON) {
    const lab = el("label", "pick pick-local");
    const cb = el("input");
    cb.type = "checkbox"; cb.value = "__local";
    pickState = el("select", "pick-state");
    pickState.setAttribute("aria-label", "Your state");
    pickState.append(el("option", null, "Local politics: choose a state"));
    pickState.firstChild.value = "";
    for (const [code, name] of Object.entries(STATES)) { const o = el("option", null, name); o.value = code; pickState.append(o); }
    pickState.addEventListener("change", () => { cb.checked = !!pickState.value; });
    cb.addEventListener("change", () => { if (cb.checked && !pickState.value) pickState.focus(); });
    lab.append(cb, el("span", null, "Local politics"));
    grid.append(lab, pickState);
  }
  const done = el("button", "picker-done", "Show my stories");
  done.type = "button";
  const sync = () => { done.disabled = !grid.querySelector("input:checked"); };
  grid.addEventListener("change", sync);
  done.addEventListener("click", () => {
    const keys = [...grid.querySelectorAll("input:checked")].map(i => i.value).filter(k => k !== "__local");
    if (!keys.length) return;
    if (pickState) sset("fx-local", grid.querySelector('input[value="__local"]').checked && pickState.value ? pickState.value : null);
    box.remove();
    saveTopics(keys);
    $("topic-nav").querySelector("a, button").focus();
  });
  box.append(grid, done);
  $("topic-nav").before(box);
}

/* ---------- How it works: the outlets we read, by side ---------- */
function renderHow(data) {
  const feeds = (data && data.feeds) || [];
  if (!$("feeds")) return;
  for (const [k, name] of [["left", "Left-leaning"], ["center", "Center"], ["right", "Right-leaning"], ["unplaced", "Not placed"]]) {
    const list = feeds.filter(f => f.ok && !f.region && (f.side || "unplaced") === k).map(f => f.source).sort();
    if (!list.length) continue;
    $("feeds").append(el("p", "feeds-side", `${name} \u00b7 ${list.length}`), el("p", "feeds-list", list.join(", ")));
  }
  const down = feeds.filter(f => !f.ok).map(f => f.source);
  if (down.length) $("feeds").append(el("p", "feeds-down", `Not reachable in the last scan: ${down.join(", ")}.`));
  const tx = feeds.filter(f => f.ok && f.region === "tx");
  if (tx.length) $("feeds").append(el("p", "feeds-down", `Texas Election (a demo edition, until Nov 4) also reads ${tx.map(f => `${f.source} (AllSides ${f.allsides})`).join(", ")} and Breitbart\u2019s Texas section, alongside the national outlets\u2019 Texas coverage. Texas outlets never feed the national sections.`));
}

/* ---------- Common ground: shared ground, and what we get wrong about each other ---------- */
function sourceLink(text, href) {
  const a = el("a", null, text);
  a.href = href; a.rel = "noopener";
  return a;
}

function renderCommon(cg) {
  const box = $("common");
  const u = cg.unites;
  const s1 = el("section", "block");
  s1.append(el("h2", "block-title", "What unites us"));
  s1.append(el("p", "cg-lede", "Policies backed by at least three in four Republicans and three in four Democrats."));
  const ul = el("ul", "agree-list");
  for (const it of u.items) {
    const li = el("li", "agree");
    li.append(el("p", "agree-policy", it.policy));
    for (const [label, v] of [["Republicans", it.rep], ["Democrats", it.dem]]) {
      const row = el("div", "agree-row");
      const bar = el("span", "agree-bar");
      const fill = el("span", "agree-fill");
      fill.style.width = `${v}%`;
      bar.append(fill);
      row.append(el("span", "agree-who", label), bar, el("span", "agree-v", `${v}%`));
      li.append(row);
    }
    // Every figure carries its own source: the question it answers, in the published questionnaire.
    const cite = el("p", "agree-cite", `${u.survey}, February 2026, ${it.q} · `);
    cite.append(sourceLink("Question and results ↗", `${u.questionnaire}#page=${it.page}`));
    li.append(cite);
    ul.append(li);
  }
  s1.append(ul);
  const src = el("p", "cg-source");
  src.append(document.createTextNode("Source: "), sourceLink(`${u.source}, “${u.title}”`, u.url),
    document.createTextNode(`. ${u.survey}, fielded ${u.fielded}: ${u.sample}. ${u.method} `),
    sourceLink("Full questionnaire (PDF) ↗", u.questionnaire));
  s1.append(src);
  box.append(s1);

  const g = cg.gap;
  const s2 = el("section", "block");
  s2.append(el("h2", "block-title", "What we get wrong about each other"));
  s2.append(el("p", "cg-lede", "Asked what share of the other party holds a mainstream view, both sides guessed too low, often by half."));
  const heads = el("div", "gap-heads");
  for (const grp of g.groups) {
    const t = el("div", "gap-head");
    t.append(el("span", "gap-head-n", `${grp.avg_gap}`), el("span", "gap-head-l", `points: how far ${grp.guesser} missed, on average, about ${grp.who}`));
    heads.append(t);
  }
  s2.append(heads);
  const key = el("p", "gap-key");
  key.append(el("span", "gap-key-guess"), document.createTextNode("Their guess"), el("span", "gap-key-actual"), document.createTextNode("What the other side actually said"));
  key.querySelectorAll("span").forEach(n => n.setAttribute("aria-hidden", "true"));
  s2.append(key);
  for (const grp of g.groups) {
    s2.append(el("h3", "gap-title", `What ${grp.guesser} think ${grp.who} believe`));
    const list = el("ul", "gap-list");
    for (const [stmt, actual, guess, asked] of grp.rows) {
      const li = el("li", "gap-row");
      li.append(el("p", "gap-stmt", stmt));
      if (asked) li.append(el("p", "gap-asked", asked));  // the survey's own wording, when we restate it
      const track = el("div", "gap-track");
      track.setAttribute("aria-hidden", "true");
      const span = el("span", "gap-span");
      span.style.left = `${Math.min(actual, guess)}%`;
      span.style.width = `${Math.abs(actual - guess)}%`;
      const gd = el("span", "gap-guess"), ad = el("span", "gap-actual");
      gd.style.left = `${guess}%`; ad.style.left = `${actual}%`;
      track.append(span, gd, ad);
      li.append(track, el("p", "gap-nums", `${grp.guesser} guessed ${guess}% of ${grp.who} hold this view. ${actual}% do.`));
      list.append(li);
    }
    s2.append(list);
  }
  const gsrc = el("p", "cg-source");
  gsrc.append(document.createTextNode("Source: "), sourceLink(`${g.source}, “${g.title}” (${g.published}), tables 1 and 2 ↗`, `${g.url}#page=${g.page}`),
    document.createTextNode(`. Fielded ${g.fielded}: ${g.sample}. ${g.method} The latest full run of this survey; newer research below tests how far it holds.`));
  s2.append(gsrc);

  s2.append(el("h3", "gap-title", "What newer research says"));
  const ol = el("ol", "misread-list");
  for (const m of cg.misread) {
    const li = el("li", "misread");
    li.append(el("h4", "misread-finding", m.finding), el("p", "misread-detail", m.detail));
    const meta = el("p", "cg-source");
    meta.append(document.createTextNode("Source: "), sourceLink(`${m.source} ↗`, m.url), document.createTextNode(` · ${m.date} · ${m.sample}`));
    li.append(meta);
    ol.append(li);
  }
  s2.append(ol);
  box.append(s2, el("p", "disclosure", `Figures read from each primary source on ${new Date(cg.checked + "T12:00:00").toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" })}.`));
}

/* ---------- Pinned header: on a phone it steps aside while reading down, and returns on any scroll up ---------- */
function initHeader() {
  const phone = matchMedia("(max-width: 719px)");
  let last = window.scrollY, queued = false, holdUntil = 0;
  const root = document.documentElement;
  // On a phone, a section picked in the strip lands right under the strip: the header steps aside first.
  document.addEventListener("click", e => {
    if (phone.matches && e.target.closest(".strip-link")) { root.classList.add("mast-away"); holdUntil = Date.now() + 1000; }
  });
  const update = () => {
    queued = false;
    const y = window.scrollY;
    if (Date.now() < holdUntil) { last = y; return; }  // a jump from the section strip: stay as set
    const open = document.querySelector(".settings[open]");
    root.classList.toggle("scrolled", y > 4);
    if (!phone.matches || open || y < 120) root.classList.remove("mast-away");
    else if (y > last + 6) root.classList.add("mast-away");
    else if (y < last - 6) root.classList.remove("mast-away");
    last = y;
  };
  window.addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(update); } }, { passive: true });
  update();
  // Keyboard focus in the header brings it back.
  document.querySelector(".masthead")?.addEventListener("focusin", () => root.classList.remove("mast-away"));
}

/* ---------- Back to top: appears once the reader is a screen and a half down ---------- */
function initToTop() {
  const main = document.getElementById("main");
  if (!main) return;
  const btn = el("button", "to-top");
  btn.type = "button";
  btn.setAttribute("aria-label", "Back to top");
  btn.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  btn.addEventListener("click", () => {
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: still ? "auto" : "smooth" });
    if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
    main.focus({ preventScroll: true });  // keyboard and screen reader users land at the top too
  });
  document.body.append(btn);
  let on = false, queued = false;
  const update = () => { queued = false; const want = window.scrollY > innerHeight * 1.5; if (want !== on) { on = want; btn.classList.toggle("is-on", on); } };
  window.addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(update); } }, { passive: true });
  update();
}

/* ---------- Settings: theme, remembered on this device only ---------- */
// The browser's own bar takes the page colour of the theme in use, and follows the device when on Auto.
function barColour() {
  const m = document.querySelector('meta[name="theme-color"]');
  if (!m) return;
  const t = document.documentElement.dataset.theme || "dark";
  const light = t === "light" || (t === "auto" && matchMedia("(prefers-color-scheme: light)").matches);
  m.content = light ? "#F5F6F8" : "#0F1113";
}
if (window.matchMedia) matchMedia("(prefers-color-scheme: light)").addEventListener("change", barColour);

function openSettings(focus) {
  const d = document.querySelector(".settings");
  if (!d) return;
  d.open = true;
  const target = focus === "topic" ? d.querySelector('input[name="topic"]') : d.querySelector("input");
  if (target) target.focus();
}

function initSettings() {
  const form = document.querySelector(".settings-panel");
  if (!form) return;
  let current = "auto";  // match the device until the reader chooses
  try { current = localStorage.getItem("fx-theme") || "auto"; } catch (e) {}
  const box = form.querySelector(`input[value="${current}"]`);
  if (box) box.checked = true;
  // Topics: which sections Today shows. At least one stays on.
  const fs = el("fieldset", "settings-topics");
  fs.append(el("legend", null, "Topics"));
  for (const t of NATIONAL) {
    const lab = el("label");
    const cb = el("input");
    cb.type = "checkbox"; cb.name = "topic"; cb.value = t.key;
    lab.append(cb, document.createTextNode(` ${t.name}`));
    fs.append(lab);
  }
  form.append(fs);
  // Local politics: off until a reader turns it on and picks a state. Shown only while an edition runs.
  const loc = el("fieldset", "settings-local");
  loc.hidden = true;
  loc.append(el("legend", null, "Local politics"));
  const lab = el("label");
  const on = el("input");
  on.type = "checkbox"; on.name = "local-on";
  lab.append(on, document.createTextNode(" Show my state"));
  const sel = el("select");
  sel.name = "local-state";
  sel.setAttribute("aria-label", "State");
  sel.append(el("option", null, "Choose a state"));
  sel.firstChild.value = "";
  for (const [code, name] of Object.entries(STATES)) { const o = el("option", null, name); o.value = code; sel.append(o); }
  loc.append(lab, sel);
  form.append(loc);
  const syncLocal = () => { loc.hidden = !LOCAL_ON; const st = localState(); on.checked = !!st; sel.value = st || ""; sel.disabled = !st && !on.checked; };
  syncLocal();
  document.addEventListener("fx-local", syncLocal);
  document.addEventListener("fx-topics", syncLocal);
  const saveLocal = () => {
    sset("fx-state", null, sessionStorage);  // a choice in Settings replaces a ?state= visit
    sset("fx-local", on.checked && sel.value ? sel.value : null);
    sel.disabled = !on.checked;
    document.dispatchEvent(new CustomEvent("fx-topics"));
  };
  on.addEventListener("change", () => { sel.disabled = !on.checked; if (on.checked && !sel.value) sel.focus(); saveLocal(); });
  sel.addEventListener("change", () => { if (sel.value) on.checked = true; saveLocal(); });
  const syncTopics = () => { const f = new Set(followedTopics()); fs.querySelectorAll("input").forEach(i => { i.checked = f.has(i.value); }); };
  syncTopics();
  document.addEventListener("fx-topics", syncTopics);
  form.addEventListener("change", e => {
    if (e.target.name === "local-on" || e.target.name === "local-state") return;  // handled above
    if (e.target.name === "topic") {
      const keys = [...fs.querySelectorAll("input:checked")].map(i => i.value);
      if (!keys.length) { e.target.checked = true; return; }
      saveTopics(keys);
      return;
    }
    const v = e.target.value;
    if (v === "dark") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v;
    try { localStorage.setItem("fx-theme", v); } catch (err) {}
    barColour();
  });
  const close = (refocus) => { const d = document.querySelector(".settings[open]"); if (d) { d.open = false; if (refocus) d.querySelector("summary").focus(); } };
  document.addEventListener("keydown", e => { if (e.key === "Escape") close(true); });
  // A click or tap anywhere else closes it, and so does tabbing out of it.
  document.addEventListener("pointerdown", e => { const d = document.querySelector(".settings[open]"); if (d && !d.contains(e.target) && !e.target.closest(".strip-edit")) close(false); });
  document.addEventListener("focusin", e => { const d = document.querySelector(".settings[open]"); if (d && !d.contains(e.target)) close(false); });
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

// The outlets on one side, each linked to its own article in this story.
function outletLinks(outlets, max) {
  const out = el("p", "side-outlets");
  const shown = outlets.slice(0, max);
  shown.forEach((o, i) => {
    if (i) out.append(document.createTextNode(i === shown.length - 1 && outlets.length <= max ? " and " : ", "));
    const url = ARTICLE[o];
    if (url) out.append(sourceLink(o, url)); else out.append(document.createTextNode(o));
  });
  if (outlets.length > max) out.append(document.createTextNode(` and ${outlets.length - max} more`));
  return out;
}

// A claim waiting for its check: the same chip shape as a verdict, and the claim itself unless it repeats the line above.
function pendingCheck(claim, above) {
  const wrap = el("div", "check check-pending");
  const c = el("span", "chip chip-wait");
  c.append(el("span", "chip-glyph", "\u2026"), el("span", "chip-word", "Checking"));
  wrap.append(c);
  if (!restates(claim, above)) wrap.append(el("p", "check-claim", claim));
  return wrap;
}

// True when the checked claim restates the line printed just above it, nearly word for word.
function restates(claim, says) {
  const words = t => (t || "").toLowerCase().match(/[a-z0-9']+/g) || [];
  const said = new Set(words(says));
  const w = words(claim);
  return w.length > 0 && w.filter(x => said.has(x)).length / w.length >= 0.85;
}

function claimDetails(c, above) {
  const wrap = el("div", "check");
  const det = el("details", "check-row");
  const sum = el("summary");
  // Don't print the same sentence twice: when the claim is the line above, the row just opens the check.
  sum.append(chip(c.verdict));
  if (!(above && restates(c.claim, above))) sum.append(el("span", "check-claim", c.claim));
  // The verdict chip is a label; this says the row opens.
  const why = el("span", "check-why", "See why");
  why.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>');
  sum.append(why);
  det.append(sum);
  const body = el("div", "check-body");
  if (c.steelman) body.append(el("p", "why", `Why this sounds right: ${c.steelman}`));
  if (c.figures && c.figures.length) body.append(statTiles(c.figures));
  if (c.finding) body.append(el("p", "finding", c.finding));
  if (c.note) body.append(el("p", "check-note", c.note.charAt(0).toUpperCase() + c.note.slice(1)));
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
  // Missing context, said plainly and visible without a tap: what the claim leaves out.
  if (c.verdict === "Missing context") {
    wrap.classList.add("is-ctx");
    if (c.left_out) {
      const p = el("p", "left-out");
      p.append(el("span", "left-out-k", "True, but left out: "), document.createTextNode(c.left_out));
      wrap.append(p);
    }
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
// Short side tag for a group of outlets, from where they are placed: LEFT, RIGHT, LEFT + CENTER, BOTH.
function sideTagText(outlets) {
  const has = sidesIn(outlets);
  if (has.has("left") && has.has("right")) return "Both sides";
  const parts = ["left", "center", "right"].filter(k => has.has(k)).map(k => k[0].toUpperCase() + k.slice(1));
  return parts.length ? parts.join(" + ") : "Unrated";
}

// One disagreement: the point, then each side's account in its own panel, its claim checked inside it.
// The more left-leaning account always comes first, so left reads left.
function differenceBlock(d, lib, leanOf) {
  const art = el("article", "diff");
  art.append(el("h3", "diff-point", d.point));
  const pos = d.positions.slice(0, 2).sort((p, q) => (meanLean(p.outlets, leanOf) ?? 0.5) - (meanLean(q.outlets, leanOf) ?? 0.5));
  const line = pos.length === 2 ? splitLine(pos, leanOf) : null;
  if (line && !/^This one splits/.test(line)) art.append(el("p", "diff-split", line));
  let tags = pos.map(p => sideTagText(p.outlets));
  if (tags.length === 2 && tags[0] === tags[1]) tags = tags.map((t, i) => `${t} \u00b7 ${i ? "B" : "A"}`);
  const cols = el("div", "sides");
  pos.forEach((p, i) => {
    const col = el("div", "side");
    col.append(el("p", "side-tag", tags[i]));
    col.append(withCrux(el("p", "side-says"), p.says, p.crux));
    col.append(outletLinks(p.outlets, 4));
    const c = claimOf(lib, p.check);
    if (c) col.append(claimDetails(c, p.says));
    else if (p.checkable_claim) col.append(pendingCheck(p.checkable_claim, p.says));
    else if (p.no_claim) col.append(el("p", "side-pending", "Framing, not a factual claim."));
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

// The chart in words: every outlet we read, by side, whether it covered the story, and where it is placed.
function outletList(feeds, covered) {
  const det = el("details", "outlet-list");
  det.append(el("summary", null, `List of outlets (${covered.size} of ${feeds.length} covered this story)`));
  const grid = el("div", "outlet-cols");
  for (const [k, name] of [["left", "Left-leaning"], ["center", "Center"], ["right", "Right-leaning"]]) {
    const col = el("div");
    col.append(el("h3", "sub-title", name));
    const ul = el("ul", "outlet-ul");
    for (const f of feeds.filter(f => SIDE[f.source] === k).sort((a, b) => covered.has(b.source) - covered.has(a.source) || a.source.localeCompare(b.source))) {
      const li = el("li", covered.has(f.source) ? "covered" : null);
      li.append(el("span", "outlet-name", `${covered.has(f.source) ? "\u25cf " : "\u25cb "}${f.source}`),
        el("span", "outlet-why", `${covered.has(f.source) ? "Covered this story. " : "Did not cover it. "}${f.lean != null ? (t => t.charAt(0).toUpperCase() + t.slice(1))(leanPhrase(f.lean, f.source)) : `Rated ${ALLSIDES[f.source]} by AllSides`}.`));
      ul.append(li);
    }
    col.append(ul);
    grid.append(col);
  }
  det.append(grid);
  return det;
}

function loadedItem(t, side) {
  const li = el("li", "loaded-item");
  const top = el("p", "loaded-line");
  top.append(el("span", "side-tag loaded-tag", side), el("span", "sr-only", " loaded word: "), el("s", "loaded-term", t.term));
  if (t.neutral) top.append(el("span", "loaded-arrow", " \u2192 "), el("span", "sr-only", "plainer: "), el("span", "loaded-neutral", t.neutral));
  li.append(top, el("p", "loaded-why", `${listNames(t.outlets, 3)}${t.why ? ". " + t.why.replace(/\.?$/, ".") : ""}`));
  // The word in its sentence, as the outlet wrote it, with the term marked.
  // Outlets that ran the same sentence (often a shared wire headline) share one quote.
  const same = new Map();
  for (const q of t.quotes || []) { const k = q.text.trim().toLowerCase(); if (same.has(k)) same.get(k).by.push(q); else same.set(k, { ...q, by: [q] }); }
  for (const q of same.values()) {
    const bq = el("blockquote", "loaded-quote");
    const p = el("p");
    const at = q.text.toLowerCase().indexOf(t.term.toLowerCase());
    if (at < 0) p.textContent = `\u201c${q.text}\u201d`;
    else p.append(document.createTextNode(`\u201c${q.text.slice(0, at)}`), el("mark", null, q.text.slice(at, at + t.term.length)), document.createTextNode(`${q.text.slice(at + t.term.length)}\u201d`));
    const by = el("p", "loaded-by");
    q.by.forEach((o, i) => { if (i) by.append(document.createTextNode(" \u00b7 ")); by.append(sourceLink(`${o.outlet} \u2197`, o.url)); });
    bq.append(p, by);
    li.append(bq);
  }
  return li;
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
  const tools = el("div", "story-tools");
  tools.append(backLink(story, data));
  $("story-meta").before(tools);
  // Share sits top right, beside Settings: an icon the size of the gear.
  const top = shareButton(story, data, "Share");
  top.classList.add("share-top");
  top.setAttribute("aria-label", "Share this story");
  document.querySelector(".mast-right").prepend(top);
  $("story-sub").append(el("p", "byline", `Headline \u00b7 ${lead(story).source}`));
  if (story.image) $("story-sub").append(figure(story.image, "story-photo"));

  const brief = story.brief;
  const agreed = (brief && brief.agreed) || [];

  const leanOf = Object.fromEntries((data.feeds || []).filter(f => f.lean != null).map(f => [f.source, f.lean]));
  PEW = Object.fromEntries((data.feeds || []).filter(f => f.pew).map(f => [f.source, f.pew]));
  SIDE = Object.fromEntries((data.feeds || []).map(f => [f.source, f.side]));
  ARTICLE = {};
  for (const a of story.articles) if (!ARTICLE[a.source]) ARTICLE[a.source] = a.url;
  ALLSIDES = Object.fromEntries((data.feeds || []).filter(f => f.lean == null && f.allsides).map(f => [f.source, f.allsides]));
  $("story-sub").querySelector(".byline").after(metricRow(story, "metrics metrics-tiles"));

  // 1. Agreed: only facts outlets on both the left and the right report.
  if (agreed.some(acrossSides)) {
    const s1 = el("section", "block");
    s1.id = "agreed";
    s1.append(el("h2", "block-title", "Agreed \u00b7 left and right"));
    const ul = el("ul", "facts");
    for (const f of agreed.filter(acrossSides).slice(0, 12)) {
      const li = el("li");
      li.append(el("span", "fact-mark", "\u2713"), el("span", "fact-text", f.fact));
      ul.append(li);
    }
    s1.append(ul);
    body.append(s1);
  }

  // 2. Splits, each side's claim checked inside its panel.
  const diffs = (brief && brief.differences) || [];
  if (diffs.length) {
    const s3 = el("section", "block");
    s3.id = "splits";
    s3.append(el("h2", "block-title", diffs.length === 1 ? "Split" : `Splits \u00b7 ${diffs.length}`));
    for (const d of diffs) s3.append(differenceBlock(d, data.library, leanOf));
    body.append(s3);
  }

  // 3. Loaded words: the outlets' own charged words, left then right.
  if (brief && brief.loaded_v) {
    const loaded = brief.loaded || [];
    const group = t => { const p = t.sides.filter(x => x !== "unplaced"); return p.length && p.every(x => x === "left") ? "Left" : p.length && p.every(x => x === "right") ? "Right" : "Both"; };
    const by = k => loaded.filter(t => group(t) === k);
    const sl = el("section", "block");
    sl.id = "loaded";
    sl.append(el("h2", "block-title", `Loaded words \u00b7 ${by("Left").length} left \u00b7 ${by("Right").length} right`));
    if (!loaded.length) sl.append(el("p", "topic-empty", "None found on either side."));
    else {
      const ul = el("ul", "loaded-list");
      for (const k of ["Left", "Right", "Both"]) for (const t of by(k)) ul.append(loadedItem(t, k === "Both" ? "Left + right" : k));
      sl.append(ul);
    }
    body.append(sl);
  }

  // 4. Who covered it.
  const placed = (data.feeds || []).filter(f => f.ok && (f.lean != null || ALLSIDES[f.source]) && (!f.region || f.region === story.region));
  if (placed.length) {
    const sc = el("section", "block");
    sc.id = "outlets";
    sc.append(el("h2", "block-title", "Who covered it"));
    const covered = new Set(story.sources);
    const fig = spectrum(placed.map(f => ({ name: f.source, lean: f.lean, rating: ALLSIDES[f.source], style: covered.has(f.source) ? "fill" : "ghost",
      note: covered.has(f.source) ? "covered this" : "did not cover this" })),
      [["fill", "Covered"], ["ghost", "Did not"], ["sq", "AllSides-rated"]],
      `Outlets that covered this story: ${story.sources.join(", ")}`);
    sc.append(fig);
    const who = sideName(story.sources, leanOf);
    if (/^(Left|Right)-leaning outlets$/.test(who)) fig.before(el("p", "diff-split", `Only ${who.toLowerCase()} covered this.`));
    sc.append(outletList(placed, covered));
    body.append(sc);
    fig.draw();
  }

  // 5. Values questions.
  const values = (brief && brief.values_questions) || [];
  if (values.length) {
    const sv = el("section", "block");
    sv.append(el("h2", "block-title", "Your call"));
    const polls = (brief && brief.polls) || [];
    if (polls.length) for (const p of polls) sv.append(pollCard(p));
    else {
      const ul = el("ul", "open-list");
      for (const q of values) { const li = el("li"); li.append(el("p", "open-point", q)); ul.append(li); }
      sv.append(ul);
    }
    body.append(sv);
  }

  // 6. Sources, the disclosure, and the method.
  const s4 = el("section", "block");
  const det = el("details", "sources-all");
  det.append(el("summary", null, `Sources \u00b7 ${plural(story.articles.length, "article", "articles")}`));
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
  const foot = el("p", "disclosure");
  foot.append(document.createTextNode("Written and checked by AI. No human review. "));
  const m = el("a", null, "Method \u2192");
  m.href = "how.html";
  foot.append(m);
  s4.append(foot);
  body.append(s4);
  linkTiles($("story-sub").querySelector(".metrics-tiles"));
  const end = el("div", "share-end");
  end.append(shareButton(story, data, "Share this story"));
  body.append(end);
  const more = moreStories(story, data);
  if (more) body.append(more);
}

// The link to share: the story's preview page (s/<sid>.html, written by each scan) so messages and posts
// show its headline, what both sides agree on and its picture. An older archived story has none: its own link.
function shareURL(story, data) {
  const base = new URL("./", location.href).href;
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  return data.archiveDay && data.archiveDay !== today ? `${base}${storyHref(story, data.archiveDay)}` : `${base}s/${story.sid}.html`;
}

// The phone's own share sheet where there is one; otherwise copy the link and say so.
function shareButton(story, data, label) {
  return makeShare(() => story.working_title, () => shareURL(story, data), label);
}
function makeShare(titleOf, urlOf, label) {
  const b = el("button", "share-btn");
  b.type = "button";
  b.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M5 11v8a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const word = el("span", "share-label", label);
  const said = el("span", "sr-only");
  said.setAttribute("aria-live", "polite");
  b.append(word, said);
  b.addEventListener("click", async () => {
    const url = urlOf();
    if (navigator.share) {
      try { await navigator.share({ title: titleOf(), url }); } catch (e) { /* closed the sheet */ }
      return;
    }
    let ok = false;
    try { await navigator.clipboard.writeText(url); ok = true; } catch (e) {
      const t = el("textarea"); t.value = url; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
      document.body.append(t); t.select();
      try { ok = document.execCommand("copy"); } catch (err) {}
      t.remove();
    }
    word.textContent = ok ? "Link copied" : "Couldn\u2019t copy";
    said.textContent = ok ? "Link copied" : "Couldn't copy the link";
    b.classList.toggle("is-done", ok);
    clearTimeout(b._t);
    b._t = setTimeout(() => { word.textContent = label; said.textContent = ""; b.classList.remove("is-done"); }, 2200);
  });
  return b;
}

/* ---------- Reader polls: vote once, then see the results; 24 hours, then results only ---------- */
const POLL_API = "api/vote.php";
function closesIn(t) {
  const m = Math.max(1, Math.round((t * 1000 - Date.now()) / 60000));
  return m < 60 ? `Closes in ${m} min` : `Closes in ${Math.round(m / 60)}h`;
}

function pollCard(p) {
  const card = el("div", "poll");
  const n = p.options.length;
  const call = body => fetch(body ? POLL_API : `${POLL_API}?poll=${encodeURIComponent(p.id)}&n=${n}`, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ poll: p.id, n, ...body }), credentials: "same-origin" }
    : { credentials: "same-origin", cache: "no-store" }).then(r => r.json());
  const form = el("form", "poll-form");
  const fs = el("fieldset");
  fs.append(el("legend", "poll-q", p.question));
  p.options.forEach((o, i) => {
    const lab = el("label", "poll-opt");
    const r = el("input");
    r.type = "radio"; r.name = `poll-${p.id}`; r.value = String(i);
    lab.append(r, el("span", null, o));
    fs.append(lab);
  });
  const vote = el("button", "poll-vote", "Vote");
  vote.type = "submit"; vote.disabled = true;
  const note = el("p", "poll-note");
  note.setAttribute("aria-live", "polite");
  fs.addEventListener("change", () => { vote.disabled = false; });
  form.append(fs, vote, note);
  card.append(form);
  const show = st => {
    if (st && st.counts) { card.replaceChildren(pollResults(p, st)); return true; }
    return false;
  };
  call().then(st => {
    if (show(st)) return;
    if (!st || st.error) { note.textContent = "Voting isn\u2019t open for this question."; fs.disabled = true; vote.hidden = true; return; }
    note.textContent = `${closesIn(st.closes)}. Vote to see the results.`;
  }).catch(() => { note.textContent = "Voting isn\u2019t available right now."; fs.disabled = true; vote.hidden = true; });
  form.addEventListener("submit", e => {
    e.preventDefault();
    const pick = form.querySelector("input:checked");
    if (!pick) return;
    vote.disabled = true; vote.textContent = "Voting\u2026";
    call({ choice: +pick.value }).then(st => {
      if (show(st)) { card.querySelector(".poll-results").focus(); return; }
      vote.disabled = false; vote.textContent = "Vote";
      note.textContent = st && st.error === "too many votes from this network" ? "This network has already sent the most votes we take for this question."
        : st && st.error === "closed" ? "Voting has closed." : "Your vote didn\u2019t go through. Try again.";
    }).catch(() => { vote.disabled = false; vote.textContent = "Vote"; note.textContent = "Your vote didn\u2019t go through. Try again."; });
  });
  return card;
}

function pollResults(p, st) {
  const box = el("div", "poll-results");
  box.tabIndex = -1;
  box.append(el("p", "poll-q", p.question));
  const total = st.total || 0;
  const ul = el("ul", "poll-bars");
  p.options.forEach((o, i) => {
    const pct = total ? Math.round((st.counts[i] / total) * 100) : 0;
    const li = el("li", st.mine === i ? "poll-bar is-mine" : "poll-bar");
    const head = el("div", "poll-bar-head");
    const label = el("span", "poll-bar-label", o);
    if (st.mine === i) label.append(el("span", "poll-mine", " \u00b7 Your vote"));
    head.append(label, el("span", "poll-bar-pct", `${pct}%`));
    const track = el("div", "poll-track");
    track.setAttribute("aria-hidden", "true");
    const fill = el("div", "poll-fill");
    fill.style.width = `${pct}%`;
    track.append(fill);
    li.append(head, track);
    ul.append(li);
  });
  box.append(ul, el("p", "poll-meta", `${total} ${total === 1 ? "vote" : "votes"} \u00b7 ${st.open ? closesIn(st.closes) : "Voting closed"} \u00b7 Reader votes, one per device. Not a scientific poll.`));
  return box;
}

// Back to where the reader came from: the story's section on Today (or the archive). Coming from Today,
// it is the browser's back, so the reader lands where they were in the list.
function backLink(story, data) {
  const a = el("a", "back-link");
  a.append(el("span", "back-arrow", "\u2190"), document.createTextNode(data.archiveDay ? " Archive" : " Today"));
  a.querySelector(".back-arrow").setAttribute("aria-hidden", "true");
  a.href = data.archiveDay ? "archive.html" : `./#${story.topic}`;
  a.addEventListener("click", e => {
    let from = null;
    try { from = document.referrer && new URL(document.referrer); } catch (err) {}
    const today = from && from.origin === location.origin && /\/(index\.html)?$/.test(from.pathname);
    if (today && !data.archiveDay && history.length > 1) { e.preventDefault(); history.back(); }
  });
  return a;
}

// Three more stories: the rest of this section first, then the lead of each other section the reader follows.
function moreStories(story, data) {
  const pool = data.stories.filter(s => s.sid !== story.sid && s.related_to === null && s.brief
    && (data.archiveDay || s.on_today) && (s.brief.agreed || []).some(acrossSides));
  const byTopic = k => pool.filter(s => s.topic === k);
  const picks = byTopic(story.topic).sort((a, b) => brokeAt(b) - brokeAt(a)).slice(0, 2);
  for (const k of followedTopics()) {
    if (picks.length >= 3) break;
    if (k === story.topic) continue;
    const top = byTopic(k)[0];
    if (top) picks.push(top);
  }
  for (const s of pool) { if (picks.length >= 3) break; if (!picks.includes(s)) picks.push(s); }
  if (!picks.length) return null;
  const sec = el("section", "block more");
  sec.setAttribute("aria-labelledby", "more-title");
  const h = el("h2", "block-title", "More stories");
  h.id = "more-title";
  const ul = el("ul", "more-list");
  for (const s of picks.slice(0, 3)) {
    const li = el("li");
    const a = el("a", "more-tile");
    a.href = storyHref(s, data.archiveDay);
    const when = data.archiveDay ? null : brokeAgo(s);
    a.append(el("p", "more-kicker", [topicName(s.topic), when].filter(Boolean).join(" \u00b7 ")), el("p", "more-title", s.working_title), metricRow(s, "metrics"));
    li.append(a);
    ul.append(li);
  }
  sec.append(h, ul);
  return sec;
}

function fail() {
  const box = el("div", "error");
  box.append(el("p", null, "We couldn't load the latest scan. Reload the page in a minute. If it keeps happening, the scan itself may have failed; the last good one stays up when that happens."));
  ($("sections") || $("story-body") || $("archive-days") || $("common") || $("main")).after(box);
}

const getJSON = (url, optional) => fetch(url, { cache: "no-cache" })
  .then(r => { if (!r.ok) { if (optional) return null; throw new Error(r.status); } return r.json(); })
  .catch(e => { if (optional) return null; throw e; });

// An archived day, shaped like a scan so the story page can render it.
const fromArchive = (arch, day) => ({ stories: Object.values(arch.stories || {}), feeds: arch.feeds, scanned_at: arch.updated_at, archiveDay: day });

async function load() {
  const page = document.body.dataset.page;
  // ?state=tx turns on that state's local section for this visit (never saved); &key=... is the investors'
  // key to the Texas time capsule. Both last for the visit, so links inside the site keep them.
  const q = new URLSearchParams(location.search);
  if (/^[a-z]{2}$/i.test(q.get("state") || "") && STATES[q.get("state").toUpperCase()]) sset("fx-state", q.get("state").toUpperCase(), sessionStorage);
  if (/^[A-Za-z0-9_-]{16,64}$/.test(q.get("key") || "")) sset("fx-capsule", q.get("key"), sessionStorage);
  initSettings();
  initHeader();
  initToTop();
  // Share sits top right on every page: a story shares itself (renderStory adds that one); any other
  // page shares its own address, without query or fragment.
  if (page !== "story") {
    const b = makeShare(() => document.title, () => location.origin + location.pathname.replace(/index\.html$/, ""), "Share");
    b.classList.add("share-top");
    b.setAttribute("aria-label", "Share this page");
    const right = document.querySelector(".mast-right");
    if (right) right.insertBefore(b, right.querySelector(".settings"));
  }
  if (page === "archive") return renderArchive(await getJSON("data/archive/index.json", true));
  if (page === "common") return renderCommon(await getJSON("common-ground.json"));
  if (page === "how") return renderHow(await getJSON("data/stories.json", true));
  const params = new URLSearchParams(location.search);
  // The time capsule: after the Texas edition's cutoff, the investors' key opens Today as it stood then.
  const key = sget("fx-capsule", sessionStorage);
  if (key) {
    const cap = await getJSON(`data/capsule/${key}/tx.json`, true);
    if (cap && Date.now() >= Date.parse(cap.frozen_at) && (page !== "story" || cap.stories.some(s => s.sid === params.get("s")))) {
      CAPSULE = cap;
      LOCAL_ON = true;
      if (!localState()) sset("fx-state", "TX", sessionStorage);
      document.dispatchEvent(new CustomEvent("fx-local"));
      capsuleBar(cap);
      const data = { stories: cap.stories, feeds: cap.feeds, scanned_at: cap.scanned_at, regions: cap.regions, library: cap.library };
      return (page === "story" ? renderStory : renderToday)(data);
    }
  }
  const library = getJSON("data/library.json", true);
  let data;
  // A link with a day (from the archive or a shared link) shows the live story while it is still on
  // Today, and that day's archived copy once it has left.
  const live = page === "story" && params.get("d") ? await getJSON("data/stories.json", true) : null;
  if (page === "story" && params.get("d") && !(live && live.stories.some(s => s.sid === params.get("s") && s.on_today))) {
    data = fromArchive(await getJSON(`data/archive/${params.get("d")}.json`), params.get("d"));
  } else {
    data = live || await getJSON("data/stories.json");
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
  const tx = data.regions && data.regions.tx;
  LOCAL_ON = !!tx && Date.now() < Date.parse(tx.until) && !data.archiveDay;
  document.dispatchEvent(new CustomEvent("fx-local"));
  (page === "story" ? renderStory : renderToday)(data);
}

// The time capsule says what it is, under the header, on every page it shows.
function capsuleBar(cap) {
  const when = new Date(cap.frozen_at).toLocaleString("en-US", { timeZone: "America/New_York", month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  const bar = el("div", "capsule-bar");
  bar.setAttribute("role", "note");
  bar.append(el("strong", null, "Time capsule"), document.createTextNode(` \u00b7 fACTUAL\u2019s Texas Election edition as it stood on ${when} Eastern. Stories, checks and poll results are frozen.`));
  document.querySelector(".masthead").after(bar);
  const robots = document.createElement("meta");  // never indexed
  robots.name = "robots"; robots.content = "noindex, nofollow";
  document.head.append(robots);
}

load().catch(fail);
