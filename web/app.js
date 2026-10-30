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
  "Missing context": { cls: "ctx", glyph: "◐", label: "Misleading" },   // stored as "Missing context"; readers see Misleading
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
// A decided verdict is shown only with its reason: one whose finding is empty reads as still being checked
// (the scan checks it again). Heston, 2026-10-21: a False showed no why.
const claimOf = (lib, key) => {
  const c = (lib && lib.claims && lib.claims[key]) || null;
  return c && DECIDED.includes(c.verdict) && !(c.finding || "").trim() ? null : c;
};
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


/* ---------- Charts: built only from data the scan has. Ink, gray and the brand purple only: green, amber and
   vermilion are verdict colours, so a chart never borrows them. ---------- */
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
// Frame the face, not a fixed band (Heston, 2026-10-30). The scan stores where the face is (fractions of the
// image); this places the crop for the frame's shape: eyes about a third of the way down, and the chin kept
// before the hair. When the face is taller than the frame, the eyes win. No face found keeps the default.
const FRAME_RATIO = { "lead-photo": 16 / 9, "card-photo": 21 / 9, "story-photo": 16 / 9 };
function facePosition(fc, ratio) {
  const fit = (want, seen, lo, hi) => {  // window start, as a share of the image, then the object-position %
    if (seen >= 0.995) return 50;  // the frame shows (nearly) all of this side
    const t = Math.min(Math.max(want, lo), hi, 1 - seen);
    return Math.round(Math.max(t, 0) / (1 - seen) * 1000) / 10;
  };
  const [x0, y0, x1, y1] = fc.box;
  const v = (fc.w / ratio) / fc.h;   // share of the height the frame shows
  const u = (fc.h * ratio) / fc.w;   // share of the width
  const chin = y1 + 0.06 * (y1 - y0) - v;  // the window starts no higher than this, so the chin shows
  const y = fit(fc.eyes - 0.36 * v, v, chin, fc.eyes - 0.28 * v);
  const x = fit((x0 + x1) / 2 - u / 2, u, -1, 1);
  return `${x}% ${y}%`;
}

function figure(img, cls, href) {
  const f = el("figure", cls);
  const im = el("img");
  im.src = img.src; im.alt = img.alt; im.loading = "lazy"; im.decoding = "async";
  if (img.face && FRAME_RATIO[cls]) im.style.objectPosition = facePosition(img.face, FRAME_RATIO[cls]);
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

// When a story first appeared: its earliest article among the outlets we read. Today is in this order (newest
// first), which stays put as outlets add articles.
const brokeAt = s => Math.min(...s.articles.map(a => Date.parse(a.published) || Infinity));
// What the card shows: when the story was last updated, its newest article (Heston, 2026-10-24: "First reported
// 2 days ago" on every card made live stories look stale).
const updatedAt = s => Math.max(...s.articles.map(a => Date.parse(a.published) || -Infinity));
const updatedAgo = s => agoText(updatedAt(s));
// "Updated 35 min ago", "Updated 3h ago", "Updated yesterday": every card says it the same way (Heston, 2026-10-24).
function agoText(when) {
  const t = Math.min(when, Date.now());
  if (!isFinite(t)) return null;
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 60) return `Updated ${Math.max(m, 1)} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `Updated ${h}h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "Updated yesterday" : `Updated ${d} days ago`;
}

// Photo subjects already on the home page, top to bottom. A repeat uses the story's second picture, or none.
let SHOWN = new Set();
function photoFor(story) {
  const last = n => (n || "").split(" ").pop();
  // A backup never shares the first picture's surname (Melania Trump on a Donald Trump story).
  const alt = story.image_alt && story.image && last(story.image_alt.subject) === last(story.image.subject) ? null : story.image_alt;
  for (const img of [story.image, alt]) if (img && !SHOWN.has(img.subject)) { SHOWN.add(img.subject); return img; }
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
  const when = updatedAgo(story);
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
  // The Texas race numbers come in their own file; their cards join the Texas section when it arrives.
  if (LOCAL_ON) getJSON(txNumbersURL(), true).then(n => { if (n && n.races) { TXNUM = n; const y = window.scrollY; drawToday(); window.scrollTo({ top: y, behavior: "instant" }); } }).catch(() => {});
  // Election night: the count joins the Texas numbers once counting starts, and keeps itself current.
  const results = () => getResults().then(r => { if (r || TXRES) { TXRES = r; const y = window.scrollY; drawToday(); window.scrollTo({ top: y, behavior: "instant" }); } return r; });
  if (LOCAL_ON) results().then(r => { if (r) setInterval(results, 120000); }).catch(() => {});
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
    const numbers = t.key === "texas" && (TXRES || (TXNUM && Object.keys(TXNUM.races || {}).length)) ? numbersCards(TXNUM || { races: {} }) : null;
    // Texas Election (Heston, 2026-10-23): the Capitol as its header, the numbers first, then the stories.
    if (t.key === "texas") sec.append(figure(TX_HEADER, "section-photo"));
    if (numbers) { sec.append(numbers); sec.append(el("h3", "numbers-group-h stories-h", "Stories")); }
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

/* ---------- Corrections (Heston, 2026-10-30): every verdict that changed after it appeared ---------- */
function renderCorrections(lib) {
  const box = $("corrections");
  const since = lib && lib.corrections_since ? new Date(lib.corrections_since).toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" }) : null;
  const log = ((lib && lib.corrections) || []).slice().reverse();  // newest first
  box.append(el("p", "cg-lede", `When a claim is checked again (after a week, when a second AI model weighs in, or when its quotes are read in their source pages) and the verdict changes, the story shows the new verdict and the change is listed here.${since ? ` Kept since ${since}.` : ""}`));
  if (!log.length) {
    box.append(el("p", "fix-none", `No verdict has changed${since ? ` since ${since}` : " yet"}.`));
    return;
  }
  const ul = el("ul", "fix-list");
  for (const x of log) {
    const li = el("li", "fix");
    li.append(el("p", "fix-when", new Date(x.at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })));
    li.append(el("p", "check-claim fix-claim", x.claim));
    const ch = el("p", "fix-change");
    ch.append(el("span", "sr-only", "Changed from "), chip(x.from), el("span", "fix-arrow", " \u2192 "), el("span", "sr-only", " to "), chip(x.to));
    ch.querySelector(".fix-arrow").setAttribute("aria-hidden", "true");
    li.append(ch, el("p", "fix-why", x.why));
    if (x.story) {
      const a = el("a", "fix-story", `${x.story.title} \u2192`);
      a.href = storyHref({ sid: x.story.sid }, x.story.day);
      li.append(a);
    }
    ul.append(li);
  }
  box.append(ul);
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
  // A close button, top right, kept in view while the panel scrolls on a phone.
  const x = el("button", "settings-close");
  x.type = "button";
  x.setAttribute("aria-label", "Close settings");
  x.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
  x.addEventListener("click", () => { const d = form.closest(".settings"); d.open = false; d.querySelector("summary").focus(); });
  form.prepend(x);
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
  // Ticked with no state yet: the box stays ticked and the list waits for a choice; nothing is saved until then.
  let choosing = false;
  const syncLocal = () => { loc.hidden = !LOCAL_ON; const st = localState(); on.checked = !!st || choosing; sel.value = st || ""; sel.disabled = !on.checked; };
  syncLocal();
  document.addEventListener("fx-local", syncLocal);
  document.addEventListener("fx-topics", syncLocal);
  const saveLocal = () => {
    sset("fx-state", null, sessionStorage);  // a choice in Settings replaces a ?state= visit
    sset("fx-local", on.checked && sel.value ? sel.value : null);
    sel.disabled = !on.checked;
    document.dispatchEvent(new CustomEvent("fx-topics"));
  };
  on.addEventListener("change", () => {
    sel.disabled = !on.checked;
    if (on.checked && !sel.value) { choosing = true; sel.focus(); return; }  // wait for the state
    choosing = false;
    saveLocal();
  });
  sel.addEventListener("change", () => { choosing = false; on.checked = !!sel.value; saveLocal(); });
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

// An account with no factual claim to check: a tag like a verdict's, in neutral grey (it isn't a judgment),
// and the same short explanation every time. What differs is already in bold above, and loaded words are
// called out below, so nothing is written about any one outlet's intent.
function framingCheck() {
  const wrap = el("div", "check check-framing");
  const det = el("details", "check-row");
  const sum = el("summary");
  const c = el("span", "chip chip-frame");
  c.append(el("span", "chip-glyph", "\u25C7"), el("span", "chip-word", "Framing"));
  const why = el("span", "check-why", "See why");
  why.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>');
  sum.append(c, why);
  const body = el("div", "check-body");
  const p = el("p", "check-lead");
  p.append(el("strong", null, "Framing, not a factual claim. "), document.createTextNode("This side\u2019s account is a matter of emphasis or interpretation, so there\u2019s nothing to check."));
  body.append(p);
  det.append(sum, body);
  wrap.append(det);
  return wrap;
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

// Every verdict opens with the same two plain answers: which part holds, is false or is missing, and what the
// sources show. Written once per claim by the scan (c.explain); until then, taken from the finding itself.
function verdictLines(c) {
  const x = c.explain || {};
  const split = c.finding ? splitFinding(c.finding) : { truth: "", missing: null };
  const lines = {
    "Holds up": [["What checks out:", x.part || c.finding]],
    "Missing context": [["What\u2019s true:", x.part || split.truth], ["What\u2019s left out:", x.context || c.left_out || split.missing]],
    "Doesn't hold up": x.part ? [["What\u2019s false:", x.part], ["What the sources show:", x.context || c.finding]] : [["What the sources show:", c.finding]],
    "Unproven": x.context ? [["What\u2019s established:", x.part], ["What isn\u2019t:", x.context]] : [["What the sources show:", c.finding]],
  }[c.verdict] || [["What the sources show:", c.finding]];
  return lines.filter(([, t]) => t);
}

// A finding, split where it turns: the sentences before "However/But/While..." are what holds; that sentence
// (and one after it) is what the claim leaves out. Null missing when the finding never turns.
function splitFinding(text) {
  const parts = [];
  let rest = text.trim();
  while (rest) { const one = firstSentence(rest); parts.push(one.trim()); rest = rest.slice(one.length).trim(); }
  const turn = parts.findIndex((p, i) => i > 0 && /^(However|But|While|Although|Yet|Still)\b|\b(leaves? out|omits?|does not mention|did not mention)\b/i.test(p));
  // No turning word: a finding of two or more sentences still turns after its first (what holds, then what else
  // the sources show), so the first is what's true and the rest is what's left out.
  if (turn < 1) return parts.length > 1 ? { truth: parts[0], missing: parts.slice(1, 3).join(" ") } : { truth: text, missing: null };
  return { truth: parts.slice(0, turn).join(" "), missing: parts.slice(turn, turn + 2).join(" ") };
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
  // Opened, a check answers first and supports second: the two plain lines for its verdict, then the quotes.
  const body = el("div", "check-body");
  const labelled = (k, text) => { const p = el("p", "check-lead"); p.append(el("strong", null, `${k} `), document.createTextNode(text)); return p; };
  for (const [k, text] of verdictLines(c)) body.append(labelled(k, text));
  if (c.figures && c.figures.length) body.append(statTiles(c.figures));
  if (c.note) body.append(el("p", "check-note", c.note.charAt(0).toUpperCase() + c.note.slice(1)));
  if (c.evidence && c.evidence.length) {
    body.append(el("p", "check-sub", "From the sources"));
    const ul = el("ul", "evidence");
    const SHOW = 3;
    c.evidence.forEach((e, i) => {
      if (i === SHOW) {
        const more = el("li", "ev-more");
        const b = el("button", "ev-more-btn", `Show ${c.evidence.length - SHOW} more`);
        b.type = "button";
        b.addEventListener("click", () => { ul.querySelectorAll(".ev-hidden").forEach(n => n.classList.remove("ev-hidden")); more.remove(); });
        more.append(b);
        ul.append(more);
      }
      const li = el("li");
      li.append(el("span", "ev-quote", `\u201c${e.quote}\u201d`));
      const src = el("a", "ev-src", `${e.publisher}${e.published ? ", " + e.published : ""} \u2197`);
      src.href = e.url;
      src.rel = "noopener";
      li.append(src);
      if (i >= SHOW) li.classList.add("ev-hidden");
      ul.append(li);
    });
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
    const gap = (c.explain && c.explain.context) || c.left_out || (c.finding && (splitFinding(c.finding) || {}).missing);
    if (gap) {
      const p = el("p", "left-out");
      p.append(el("span", "left-out-k", "True, but left out: "), document.createTextNode(gap));
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
    else if (p.no_claim) col.append(framingCheck());
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

/* ---------- Texas race numbers (data/tx-numbers.json, written by pipeline/tx_numbers.py) ----------
   The Senate and governor race pages carry the race's numbers: the forecast, every poll from the last 30 days
   that we confirmed against its pollster's release, the published averages, which polls each side's outlets
   reported, how far Texas polls have missed before, and the money. No party colours: candidates are told
   apart by name and by side of the tie line (the Democrat's lead to the left, the Republican's to the right,
   as on the outlet spectrum). Every number is text in the page; the tracks only draw it. */
const surname = c => c.name.split(" ").pop();
const pts = x => { const r = Math.round(Math.abs(x) * 10) / 10; return Number.isInteger(r) ? String(r) : r.toFixed(1); };
const pts_ = pts;  // the summaries keep a local list named pts
// shares are [first candidate (Republican, ballot order), second]; a positive gap is the first one ahead.
const gapOf = sh => sh[0] - sh[1];
function gapText(gap, cands) {
  if (Math.abs(gap) < 0.05) return "Tied";
  return `${surname(cands[gap > 0 ? 0 : 1])} +${pts(gap)}`;
}
const usd = v => v == null ? "–" : v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`;
const shortDate = iso => new Date(`${iso}T12:00:00`).toLocaleDateString([], { month: "short", day: "numeric" });
function basedOn(text, link, href) {
  // Heston's basis rule: what a number is based on sits right where it appears, never in a footnote.
  const p = el("p", "num-basis");
  p.append(el("strong", null, "Based on "), document.createTextNode(text));
  if (link) { p.append(document.createTextNode(" ")); const a = el("a", null, `${link} ↗`); a.href = href; a.rel = "noopener"; p.append(a); }
  return p;
}
// A track: the tie line in the middle, a dot at the gap, and (for a poll) a whisker as wide as its margin of
// error on the gap. Positions are percentages, so it needs no redrawing at any width.
function track(gap, moe, max, cls) {
  const t = el("div", `num-track ${cls || ""}`);
  t.setAttribute("aria-hidden", "true");
  const at = v => `${50 + 50 * Math.max(-1, Math.min(1, v / max))}%`;
  t.append(el("i", "num-tie"));
  if (moe) {
    const w = el("i", "num-whisker");
    w.style.left = at(gap - moe);
    w.style.right = `calc(100% - ${at(gap + moe)})`;
    t.append(w);
  }
  const d = el("i", "num-dot");
  d.style.left = at(gap);
  t.append(d);
  return t;
}
function trackAxis(max, cands) {
  const ax = el("div", "num-axis");
  ax.setAttribute("aria-hidden", "true");
  const half = Math.round(max / 2);
  for (const [v, t] of [[-max, String(max)], [-half, String(half)], [0, "Tie"], [half, String(half)], [max, String(max)]]) {
    const s = el("span", null, t);
    s.style.left = `${50 + 50 * v / max}%`;
    ax.append(s);
  }
  const sides = el("div", "num-sides");
  sides.setAttribute("aria-hidden", "true");
  sides.append(el("span", null, `← ${surname(cands[1])} ahead`), el("span", null, `${surname(cands[0])} ahead →`));
  const wrap = el("div", "num-axis-wrap");
  wrap.append(sides, ax);
  return wrap;
}

function forecastBlock(f, cands) {
  const box = el("div", "num-forecast");
  box.append(el("h2", "num-h", "Chance of winning"));
  const row = el("div", "fc-row");
  const order = [0, 1].sort((a, b) => f.chance[b] - f.chance[a]);
  for (const i of order) {
    const c = el("div", "fc-cand");
    c.append(el("span", "fc-pct", `${f.chance[i]}%`), el("span", "fc-name", `${cands[i].name} (${cands[i].party})`));
    row.append(c);
  }
  box.append(row);
  const bar = el("div", "fc-bar");
  bar.setAttribute("aria-hidden", "true");
  for (const i of order) { const s = el("i"); s.style.flexGrow = f.chance[i]; bar.append(s); }
  box.append(bar);
  box.append(basedOn(f.method));
  box.append(el("p", "num-note", "A forecast is arithmetic on the polls, not a fact check."));
  return box;
}

function pollsBlock(r, cands, recentDays) {
  const box = el("div", "num-polls");
  box.append(el("h2", "num-h", `Polls · last ${recentDays} days`));
  const polls = r.polls;
  if (!polls.length) {
    box.append(el("p", "num-note", "No poll from the last 30 days is confirmed against its pollster's release yet. Checking continues every hour."));
  } else {
    const inside = polls.filter(p => p.lead_moe && Math.abs(gapOf(p.shares)) <= p.lead_moe).length;
    const measured = polls.filter(p => p.lead_moe).length;
    box.append(el("p", "num-lede", measured === inside
      ? `In all ${plural(measured, "poll", "polls")} with a stated margin of error, the gap is inside that margin, so no single poll shows a clear leader.`
      : (() => {
        const out = polls.filter(p => p.lead_moe && Math.abs(gapOf(p.shares)) > p.lead_moe);
        const named = out.length <= 3 ? ` (${out.map(p => `${p.pollster}, ${gapText(gapOf(p.shares), cands)}`).join("; ")})` : "";
        return `In ${inside} of ${plural(measured, "poll", "polls")} with a stated margin of error, the gap is inside that margin. In ${out.length}${named}, the lead is bigger than the margin.`;
      })()));
  }
  const all = [...polls.map(p => Math.abs(gapOf(p.shares)) + (p.lead_moe || 0)), ...r.averages.map(a => Math.abs(gapOf(a.shares)))];
  const max = Math.max(10, Math.ceil(Math.max(0, ...all) / 10) * 10);  // ticks at the ends and halfway: whole numbers
  if (polls.length) {
    box.append(trackAxis(max, cands));
    const ul = el("ul", "num-rows");
    for (const p of polls) {
      const li = el("li", `num-row${p.one_side ? " is-side" : ""}`);
      const who = el("div", "num-who");
      const name = p.url ? el("a", "num-name", p.pollster) : el("span", "num-name", p.pollster);
      if (p.url) { name.href = p.url; name.rel = "noopener"; }
      const meta = [p.dates.replace(/, \d{4}$/, ""), p.n ? `${p.n.toLocaleString()} ${p.pop === "RV" ? "registered" : p.pop === "LV" ? "likely" : ""} voters`.replace("  ", " ") : (p.pop === "RV" ? "registered voters" : p.pop === "LV" ? "likely voters" : "")].filter(Boolean);
      if (p.affiliation === "R" || p.affiliation === "D") meta.push(`${p.affiliation === "R" ? "Republican" : "Democratic"}-affiliated pollster`);
      who.append(name, el("span", "num-meta", meta.join(" · ")));
      if (p.client) who.append(el("span", `num-client${p.one_side ? " is-side" : ""}`, p.client));
      const val = el("div", "num-val");
      val.append(el("span", "num-gap", gapText(gapOf(p.shares), cands)),
        el("span", "num-moe", p.lead_moe ? `±${pts(p.lead_moe)} on the gap` : "margin not stated"));
      li.append(who, track(gapOf(p.shares), p.lead_moe, max, p.one_side ? "hollow" : ""), val);
      ul.append(li);
    }
    box.append(ul);
    const key = el("div", "spectrum-legend");
    for (const [cls, t] of [["fill", "Independent poll"], ["hollow", "Paid for by a campaign or a group backing one"], ["bar", "Margin of error on the gap"]]) {
      const k = el("span", "key"); k.append(el("i", cls === "bar" ? "num-key-bar" : `dot ${cls}`), el("span", null, t)); key.append(k);
    }
    box.append(key);
    box.append(basedOn(`polls listed on Wikipedia, each shown only when our own read of the pollster's release finds the same numbers. A poll's stated margin of error applies to each candidate; on the gap between them it is about twice as large, computed from the poll's own numbers.`,
      "Wikipedia's list", r.wiki));
  }
  if (r.unconfirmed.length) {
    const det = el("details", "num-more");
    det.append(el("summary", null, `${plural(r.unconfirmed.length, "more poll", "more polls")} we could not confirm`));
    const ul = el("ul", "num-unconf");
    for (const u of r.unconfirmed) {
      const li = el("li");
      li.append(el("span", "num-name", u.pollster), el("span", "num-meta", `${u.dates} · ${u.why}`));
      ul.append(li);
    }
    det.append(ul);
    box.append(det);
  }
  // The published averages, on the same scale.
  if (r.averages.length) {
    const ab = el("div", "num-avgs");
    ab.append(el("h2", "num-h", "Published averages"));
    const gaps = r.averages.map(a => gapOf(a.shares));
    const lo = Math.min(...gaps), hi = Math.max(...gaps);
    ab.append(el("p", "num-lede", lo * hi > 0
      ? `All ${r.averages.length} put ${surname(cands[hi > 0 ? 0 : 1])} ahead, by ${pts(Math.min(Math.abs(lo), Math.abs(hi)))} to ${pts(Math.max(Math.abs(lo), Math.abs(hi)))} points.`
      : `They disagree on who is ahead: from ${gapText(lo, cands)} to ${gapText(hi, cands)}.`));
    ab.append(trackAxis(max, cands));
    const ul = el("ul", "num-rows");
    for (const a of r.averages) {
      const li = el("li", "num-row");
      const who = el("div", "num-who");
      const name = a.url ? el("a", "num-name", a.source) : el("span", "num-name", a.source);
      if (a.url) { name.href = a.url; name.rel = "noopener"; }
      who.append(name, el("span", "num-meta", `Updated ${a.updated.replace(/, \d{4}$/, "")}`));
      const val = el("div", "num-val");
      val.append(el("span", "num-gap", gapText(gapOf(a.shares), cands)), el("span", "num-moe", `${pts(a.shares[0])} to ${pts(a.shares[1])}`));
      li.append(who, track(gapOf(a.shares), null, max, "avg"), val);
      ul.append(li);
    }
    ab.append(ul);
    ab.append(basedOn("each publisher's own average, as listed on Wikipedia with a link to the publisher. Most of these sites refuse automated readers, so we could not read them ourselves.", "Wikipedia's list", r.wiki));
    box.append(ab);
  }
  return box;
}

function citedBlock(r, cands) {
  const box = el("div", "num-cited");
  box.append(el("h2", "num-h", "Which polls each side reported"));
  const cited = r.cited || [];
  const by = side => cited.filter(c => c.side === side);
  if (!cited.length) {
    box.append(el("p", "num-note", "No article in this race's coverage has named a poll yet."));
    return box;
  }
  const since = cited.map(c => c.day).filter(Boolean).sort()[0];
  const sum = side => {
    // Distinct polls, not articles: two CBS videos naming the same CBS poll are one poll.
    const list = by(side);
    const label = side === "left" ? "Left" : "Right";
    if (!list.length) return `${label}-leaning outlets: no poll named.`;
    const polls = [...new Map(list.map(c => [`${c.pollster}|${c.poll_end}`, c])).values()];
    const lead = i => polls.filter(c => Math.sign(gapOf(c.shares)) === (i === 0 ? 1 : -1)).length;
    const tied = polls.filter(c => Math.abs(gapOf(c.shares)) < 0.05).length;
    return `${label}-leaning outlets named ${plural(polls.length, "poll", "polls")} in ${plural(list.length, "article", "articles")}: ${surname(cands[1])} ahead in ${lead(1)}, ${surname(cands[0])} ahead in ${lead(0)}${tied ? `, tied in ${tied}` : ""}.`;
  };
  box.append(el("p", "num-lede", `${sum("left")} ${sum("right")}`));
  const cols = el("div", "num-cols");
  for (const side of ["left", "right"]) {
    const col = el("div", "num-col");
    col.append(el("p", "num-col-h", side === "left" ? "Left-leaning outlets" : "Right-leaning outlets"));
    const ul = el("ul", "num-cite-list");
    for (const c of by(side)) {
      const li = el("li");
      li.append(el("span", "num-cite-poll", `${c.pollster} · ${gapText(gapOf(c.shares), cands)}`));
      const a = el("a", null, c.title);
      a.href = c.url; a.rel = "noopener";
      const by2 = el("span", "num-cite-by", `${c.outlet}${c.day ? ` · ${shortDate(c.day)}` : ""}: `);
      by2.append(a);
      li.append(by2);
      ul.append(li);
    }
    if (!by(side).length) ul.append(el("li", "num-note", "None yet."));
    col.append(ul);
    cols.append(col);
  }
  box.append(cols);
  const center = cited.filter(c => c.side !== "left" && c.side !== "right").length;
  box.append(basedOn(`headlines and summaries in the coverage we read${since ? ` since ${shortDate(since)}` : ""} that name a pollster, matched in code to that pollster's latest poll at the time.${center ? ` ${plural(center, "article", "articles")} from center or unplaced outlets not shown.` : ""}`));
  return box;
}

// Polls by group: each group a row, each poll a dot at its gap, and every poll's number written under the row.
// No blend of our own: readers see whether the pollsters agree. A group is a small slice of a poll, so its number
// is far less certain than the headline; that is said first, not in a footnote.
const GROUP_CATS = [["gender", "Gender"], ["race", "Race and ethnicity"], ["age", "Age"], ["party", "Party"], ["education", "Education"], ["area", "Where they live"]];
const GROUP_ORDER = { Men: 1, Women: 2, White: 1, Black: 2, Hispanic: 3, Republicans: 1, Democrats: 2, Independents: 3, "No college degree": 1, "College degree": 2, Urban: 1, Suburban: 2, Rural: 3 };
const ageStart = l => /^Under/.test(l) ? 0 : parseInt(l, 10) || 0;
function groupsBlock(r, cands, nums) {
  const box = el("div", "num-groups");
  const g = r.groups || {};
  box.append(el("h2", "num-h", "How each group leans"));
  box.append(el("p", "num-lede", "Each dot is one poll. A group is only a slice of a poll's sample, so its number is much less certain than the poll's headline result: read these for whether the polls agree, not for exact margins."));
  for (const [cat, label] of GROUP_CATS) {
    if (!g[cat]) continue;
    const sub = el("div", "num-group-cat");
    sub.append(el("h3", "num-group-h", label));
    const names = Object.keys(g[cat]).sort((a, b) => cat === "age" ? ageStart(a) - ageStart(b) : (GROUP_ORDER[a] || 9) - (GROUP_ORDER[b] || 9));
    const max = Math.max(10, Math.ceil(Math.max(...names.flatMap(n => g[cat][n].map(p => Math.abs(gapOf(p.shares))))) / 10) * 10);
    sub.append(trackAxis(max, cands));
    const ul = el("ul", "num-rows");
    for (const name of names) {
      const polls = g[cat][name];
      const gaps = polls.map(p => gapOf(p.shares));
      const lead = [0, 1].map(i => gaps.filter(x => (i === 0 ? x > 0.05 : x < -0.05)).length);
      const li = el("li", "num-row");
      const who = el("div", "num-who");
      who.append(el("span", "num-name", name), el("span", "num-meta", polls.map(p => `${p.pollster.split("/")[0]} ${gapText(gapOf(p.shares), cands)}`).join(" \u00b7 ")));
      const t = el("div", "num-track");
      t.setAttribute("aria-hidden", "true");
      t.append(el("i", "num-tie"));
      for (const p of polls) {
        const d = el("i", p.one_side ? "num-dot is-hollow" : "num-dot");
        d.style.left = `${50 + 50 * Math.max(-1, Math.min(1, gapOf(p.shares) / max))}%`;
        t.append(d);
      }
      const val = el("div", "num-val");
      const all = lead[0] === polls.length || lead[1] === polls.length;
      val.append(el("span", "num-gap", polls.length === 1 ? gapText(gaps[0], cands) : all ? `${surname(cands[lead[0] ? 0 : 1])} in all ${polls.length}` : "Polls differ"),
        el("span", "num-moe", polls.length === 1 ? "1 poll" : `${surname(cands[1])} ${lead[1]} \u00b7 ${surname(cands[0])} ${lead[0]}`));
      li.append(who, t, val);
      ul.append(li);
    }
    sub.append(ul);
    box.append(sub);
  }
  box.append(basedOn("the group results in each confirmed poll's own release. Two AI models read each release separately; a number is shown only when they agree, the passage is in the release, and the groups make sense together (men and women bracket the headline result). Groups that mix two traits, like \u201cwhite men without a degree,\u201d are left out."));
  return box;
}

// A progress bar: a share of 100% (turnout rates).
function rateRows(rows) {
  const ul = el("ul", "rate-list");
  for (const [label, value, text] of rows) {
    const li = el("li", "rate-row");
    const bar = el("div", "rate-bar"); bar.setAttribute("aria-hidden", "true");
    const f = el("i"); f.style.width = `${Math.min(100, value)}%`; bar.append(f);
    li.append(el("span", "rate-label", label), el("span", "rate-text", text), bar);
    ul.append(li);
  }
  return ul;
}

// The four kinds of county, most Democratic to most Republican, by the 2024 vote for president. Named by party,
// not candidate (Heston, 2026-10-27: "Harris won" beside Harris County confused). By position, so older data
// with candidate labels reads the same.
const COUNTY_GROUPS = ["Counties Democrats won", "Counties Republicans won by under 20 points", "Counties Republicans won by 20 to 50 points", "Counties Republicans won by 50 points or more"];
const COUNTY_SHORT = ["Counties Democrats won", "Counties Republicans won by under 20 pts", "Counties Republicans won by 20 to 50 pts", "Counties Republicans won by 50+ pts"];
const countyName = (g, x) => (COUNTY_GROUPS[g.indexOf(x)] || x.group).replace(/^Counties/, "counties");

// "What's happening": a plain summary above a number story's numbers (Heston, 2026-10-27). Every point is
// written by code from numbers shown further down the same page, so it can't drift from them.
function summaryBox(points) {
  const box = el("div", "num-summary");
  box.append(el("h2", "num-h", "What\u2019s happening"));
  const ul = el("ul", "num-summary-list");
  points.filter(Boolean).forEach(t => ul.append(el("li", null, t)));
  box.append(ul);
  return box;
}
const summaryBasis = () => basedOn("the figures on this page, each shown below with its own source.");

function pollsSummary(r, c, nums) {
  const pts = [];
  const f = r.forecast;
  if (f) {
    const i = f.chance[0] >= f.chance[1] ? 0 : 1;
    pts.push(`${c[i].name} has a ${f.chance[i]}% chance to win and ${c[1 - i].name} ${f.chance[1 - i]}%, by our arithmetic on the published polling averages and how far Texas polls have missed before.`);
  }
  const gaps = r.averages.map(a => gapOf(a.shares));
  if (gaps.length) {
    const same = gaps.every(x => Math.sign(x) === Math.sign(gaps[0]) && Math.abs(x) >= 0.05);
    const abs = gaps.map(Math.abs);
    pts.push(same ? `${surname(c[gaps[0] > 0 ? 0 : 1])} leads in all ${plural(gaps.length, "published average", "published averages")}, by ${pts_(Math.min(...abs))} to ${pts_(Math.max(...abs))} points.`
      : `The ${gaps.length} published averages disagree on who is ahead.`);
  }
  const polls = r.polls || [];
  if (polls.length) {
    const ahead = i => polls.filter(p => (i === 0 ? 1 : -1) * gapOf(p.shares) >= 0.05).length;
    const tied = polls.length - ahead(0) - ahead(1);
    const order = ahead(0) >= ahead(1) ? [0, 1] : [1, 0];
    const has = (n, i) => `${n} ${n === 1 ? "has" : "have"} ${surname(c[i])} ahead`;
    const measured = polls.filter(p => p.lead_moe), inside = measured.filter(p => Math.abs(gapOf(p.shares)) <= p.lead_moe).length;
    pts.push(`Of the ${plural(polls.length, "poll", "polls")} from the last ${nums.recent_days || 30} days that we confirmed against the pollster\u2019s own release, ${has(ahead(order[0]), order[0])}, ${tied ? "" : "and "}${has(ahead(order[1]), order[1])}${tied ? `, and ${tied} ${tied === 1 ? "is" : "are"} tied` : ""}.`
      + (measured.length ? ` In ${inside} of the ${measured.length} that publish a margin of error, the lead is smaller than that margin, so ${inside === 1 ? "that poll can\u2019t" : "those polls can\u2019t"} say for sure who is ahead.` : ""));
  }
  const h = nums.history, lead = raceLead(r);
  if (h && h.races && lead != null) {
    const races = h.races, last = races[races.length - 1];
    let run = 0;
    for (let i = races.length - 1; i >= 0 && Math.sign(races[i].miss) === Math.sign(last.miss); i--) run++;
    pts.push(`Since 2016, Texas\u2019s final polling averages missed the result by ${pts_(h.typical_miss)} points on average, ${lead < h.typical_miss ? "more than" : "less than"} this race\u2019s ${pts_(lead)}-point lead. `
      + `The Republican did ${last.miss > 0 ? "better" : "worse"} than the polls in the last ${run} of ${races.length} races, every one since ${races[races.length - run].year}.`);
  }
  return pts;
}

function groupsSummary(r, c) {
  const g = r.groups || {};
  const word = (cat, n) => cat === "race" ? `${n} voters` : cat === "area" ? `${n.toLowerCase()} voters` : cat === "party" ? (n === "Independents" ? "independents" : n)
    : cat === "gender" ? n.toLowerCase() : cat === "education" ? (n === "College degree" ? "voters with a college degree" : "voters without a college degree")
    : cat === "age" ? (n.endsWith("+") ? `voters ${n.slice(0, -1)} and over` : /^Under/.test(n) ? `voters ${n.toLowerCase()}` : `voters ${n}`) : n;
  const polls = new Set(Object.values(g).flatMap(x => Object.values(x).flat().map(p => p.pollster + p.end)));
  const agree = [[], []], split = [];
  for (const [cat] of GROUP_CATS) for (const [n, rows] of Object.entries(g[cat] || {})) {
    if (rows.length < 2) continue;
    const gaps = rows.map(p => gapOf(p.shares));
    if (gaps.every(x => x >= 0.05)) agree[0].push(word(cat, n));
    else if (gaps.every(x => x <= -0.05)) agree[1].push(word(cat, n));
    else split.push(word(cat, n));
  }
  const pts = [`${plural(polls.size, "poll", "polls")} so far ${polls.size === 1 ? "reports" : "report"} numbers by group, confirmed against the release.`];
  if (!agree[0].length && !agree[1].length && !split.length) {
    pts.push("No group is in more than one poll yet, so there is nothing to compare across polls. More releases are read every hour.");
    return pts;
  }
  for (const i of [1, 0]) if (agree[i].length) pts.push(`Every poll that reports them has ${surname(c[i])} ahead among ${listNames(agree[i], 8)}.`);
  if (split.length) pts.push(`The polls disagree on who leads among ${listNames(split, 8)}.`);
  pts.push("A group is a small slice of a poll\u2019s sample, so its numbers are far less certain than the headline result. Read them for whether the polls agree, not for exact margins.");
  return pts;
}

function moneySummary(m, c) {
  if (!m || !m.candidates || !m.candidates.length) return [];
  const pts = [];
  const by = name => m.candidates.find(x => x.name === name.name) || {};
  const M = v => `$${(v / 1e6).toFixed(1)} million`;
  if (m.source === "FEC" && m.candidates.every(x => x.raised != null)) {
    const [a, b] = [...m.candidates].sort((x, y) => y.raised - x.raised);
    pts.push(`${surname(a)}\u2019s campaign has raised ${(a.raised / b.raised).toFixed(1)} times as much as ${surname(b)}\u2019s: ${M(a.raised)} to ${M(b.raised)}.`);
    const sides = sideSpending(m);
    if (sides) {
      const [x, y] = [...sides].sort((p, q) => q[1] - p[1]);
      const xc = by(x[0]), yc = by(y[0]);
      pts.push(`Outside groups have put more on ${surname(x[0])}\u2019s side: ${M(x[1])}, against ${M(y[1])} on ${surname(y[0])}\u2019s. Most of it is spending against ${surname(y[0])} (${M(yc.outside_oppose || 0)}).`);
      const both = new Map();
      for (const cand of m.candidates) for (const [list, other] of [[cand.top_support || [], cand], [cand.top_oppose || [], m.candidates.find(o => o !== cand)]])
        for (const gr of list) { const e = both.get(gr.group) || { usd: 0 }; e.usd += gr.usd; both.set(gr.group, e); }
      const top = [...both.entries()].sort((p, q) => q[1].usd - p[1].usd)[0];
      if (top) {
        const parts = m.candidates.flatMap(cand => [...(cand.top_support || []).filter(gr => gr.group === top[0]).map(gr => `${M(gr.usd)} for ${surname(cand)}`), ...(cand.top_oppose || []).filter(gr => gr.group === top[0]).map(gr => `${M(gr.usd)} against ${surname(cand)}`)]);
        pts.push(`The biggest single outside spender is ${top[0]}: ${M(top[1].usd)} in all${parts.length > 1 ? `, ${listNames(parts, 2)}` : ""}.`);
      }
      const totals = m.candidates.map(cand => [cand, cand.raised + (new Map(sides.map(([k, v]) => [k.name, v])).get(cand.name) || 0)]).sort((p, q) => q[1] - p[1]);
      pts.push(`In all, counting the campaigns and outside groups, ${listNames(totals.map(([cand, v]) => `${M(v)} is on ${surname(cand)}\u2019s side`), 2)}.`);
    }
  } else if (m.candidates.every(x => x.cash != null)) {
    const [a, b] = [...m.candidates].sort((x, y) => y.cash - x.cash);
    const thru = m.candidates.map(x => x.through).filter(Boolean).sort().pop();
    const when = thru && thru.length === 8 ? shortDate(`${thru.slice(0, 4)}-${thru.slice(4, 6)}-${thru.slice(6)}`) : null;
    pts.push(`${surname(a)} has ${(a.cash / b.cash).toFixed(1)} times as much cash on hand as ${surname(b)}: ${M(a.cash)} to ${M(b.cash)}${when ? `, in reports through ${when}` : ""}.`);
    pts.push("Texas reports show cash on hand here, not money raised: one campaign moves money between its accounts, so adding up what each account raised would count it twice.");
  }
  return pts;
}

// A plain summary above the numbers (Heston, 2026-10-27: "explaining what's going on"). Written by code from the
// same numbers as the charts below, so it can't drift from them; each point is a fact shown further down.
function earlySummary(ev) {
  const pts = [];
  const day = iso => new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
  const thru = (ev.through || "").replace(/, \d{4}$/, "");
  pts.push(`${fmtN(ev.voted)} Texans have voted early through ${thru}, ${pct(ev.voted, ev.registered).toFixed(1)}% of the ${fmtN(ev.registered)} registered: ${fmtN(ev.in_person)} in person and ${fmtN(ev.mail)} by mail${ev.counties ? ` (${ev.counties[0]} of ${ev.counties[1]} counties reporting)` : ""}.`);
  const g = ev.by_2024 || [];
  if (g.length && g[0].in_person_2024) {
    const all = pct(g.reduce((t, x) => t + x.in_person, 0), g.reduce((t, x) => t + x.in_person_2024, 0));
    const tp = ev.turnout_past;
    pts.push(`In-person early voting is at ${Math.round(all)}% of its level at the same point in 2024, a presidential election.`
      + (tp ? ` For scale: in 2022, the last midterm, ${(tp["2022"] / 1e6).toFixed(1)} million Texans voted in all, ${Math.round(pct(tp["2022"], tp["2024"]))}% as many as the ${(tp["2024"] / 1e6).toFixed(1)} million in 2024.` : ""));
    const pace = x => pct(x.in_person, x.in_person_2024);
    const s = [...g].sort((a, b) => pace(b) - pace(a)), hi = s[0], lo = s[s.length - 1];
    const name = x => countyName(g, x);
    pts.push(`The pace is highest in ${name(hi)} (${Math.round(pace(hi))}% of 2024) and lowest in ${name(lo)} (${Math.round(pace(lo))}%).`);
  }
  const d = ev.daily, p = ev.daily_2024;
  if (d && p && d.votes.length >= 2) {
    const i = d.votes.length - 1, r = Math.round(100 * d.votes[i] / p.votes[i]);
    pts.push(`The latest day, ${d.labels[i]}, drew ${fmtN(d.votes[i])} in-person votes, ${r}% of the same day in 2024.`);
  }
  if (ev.early_ends && ev.election_date) pts.push(`Early voting runs through ${day(ev.early_ends)}. Election Day is ${day(ev.election_date)}. Early votes are not results: none are released until polls close that day, and Election Day voters can differ from early voters.`);
  const box = summaryBox(pts);
  box.append(basedOn(`${ev.source}, as of ${ev.as_of || "the latest update"} (mail ballots are those received so far), and the charts below${ev.turnout_past ? `. 2022 and 2024 turnout: ${ev.turnout_past.source}` : ""}.`, "Secretary of State", ev.url));
  return box;
}

function earlyBlock(ev) {
  const box = el("div", "num-early");
  // The Secretary of State's count gets the summary, which states the count; older data keeps "So far".
  if (ev.mail != null && ev.in_person != null) box.append(earlySummary(ev));
  else {
  const thru = (ev.through || "").replace(/^\w+day, /, "").replace(/, \d{4}$/, "");
  box.append(el("h2", "num-h", "So far"));
  const how = ev.in_person != null && ev.mail != null ? `: ${fmtN(ev.in_person)} in person and ${fmtN(ev.mail)} by mail` : "";
  box.append(el("p", "num-lede", `${fmtN(ev.voted)} Texans have voted, ${pct(ev.voted, ev.registered).toFixed(1)}% of the ${fmtN(ev.registered)} registered, through ${thru}${how}${ev.counties ? ` (${ev.counties[0]} of ${ev.counties[1]} counties reporting)` : ""}.`));
  }
  // Pace: each day as a share of the same day of early voting in 2024, against a marked 100% line.
  const d = ev.daily, p = ev.daily_2024;
  if (d && p && p.votes) {
    const n = Math.min(d.votes.length, p.votes.length);
    const ratios = d.votes.slice(0, n).map((v, i) => v / p.votes[i]);
    const lo = Math.round(100 * Math.min(...ratios)), hi = Math.round(100 * Math.max(...ratios));
    const s2 = el("div", "num-early-part");
    s2.append(el("h2", "num-h", "Pace against 2024"));
    s2.append(el("p", "num-lede", `Each day of early voting has drawn ${lo === hi ? lo : `${lo} to ${hi}`}% as many voters as the same day of early voting in 2024, a presidential election year.`));
    const ul = el("ul", "pace-list");
    for (let i = 0; i < n; i++) {
      const li = el("li", "pace-row");
      const bar = el("div", "pace-bar"); bar.setAttribute("aria-hidden", "true");
      const f = el("i"); f.style.width = `${Math.min(100, 100 * ratios[i] / 1.2)}%`;
      const mark = el("b", "pace-100"); mark.style.left = `${100 / 1.2}%`;
      bar.append(f, mark);
      li.append(el("span", "rate-label", `Day ${i + 1} · ${d.labels[i]}`), el("span", "rate-text", `${fmtN(d.votes[i])} votes · ${Math.round(100 * ratios[i])}% of 2024`), bar);
      ul.append(li);
    }
    s2.append(ul, el("p", "num-note", "The tick on each bar marks 2024’s level for that day. In-person votes only, both years."));
    if (p.source) s2.append(basedOn(`the Secretary of State’s daily counts for 2026. For 2024, ${p.source}: the Secretary of State’s own 2024 daily figures are not open to automated reading. For 2026’s first week the two sources were within 1.6% of each other every day.`, "2024 figures", p.url));
    box.append(s2);
  }
  if (ev.by_2024) box.append(countyBlock(ev));
  // Who has voted, by group: only when Transparency USA's tracker could be read (it refuses GitHub's servers).
  if (!ev.age) return box;
  const gf = ev.groups_from || ev;
  // Who has voted against who is registered: a table, with the difference in points.
  const s3 = el("div", "num-early-part");
  s3.append(el("h2", "num-h", "Who has voted, against who is registered"));
  const ages = Object.entries(ev.age), votedA = ages.reduce((t, [, x]) => t + x[0], 0), regA = ages.reduce((t, [, x]) => t + x[0] + x[1], 0);
  const old = ev.age["65+"], young = ["18-24", "25-34"].map(k => ev.age[k]);
  s3.append(el("p", "num-lede", `People 65 and over cast ${Math.round(pct(old[0], votedA))}% of the votes so far but are ${Math.round(pct(old[0] + old[1], regA))}% of registered voters. Voters under 35 cast ${Math.round(pct(young[0][0] + young[1][0], votedA))}% of the votes and are ${Math.round(pct(young[0][0] + young[0][1] + young[1][0] + young[1][1], regA))}% of the rolls.`));
  const gs = Object.entries(ev.gender), votedG = gs.reduce((t, [, x]) => t + x[0], 0), regG = gs.reduce((t, [, x]) => t + x[0] + x[1], 0);
  const rows = [...ages.map(([l, x]) => [l === "65+" ? "65 and over" : l, pct(x[0], votedA), pct(x[0] + x[1], regA)]),
    ...gs.map(([l, x]) => [l === "Female" ? "Women" : l === "Male" ? "Men" : l, pct(x[0], votedG), pct(x[0] + x[1], regG)])];
  const wrap = el("div", "num-table-wrap");
  const t = el("table", "num-table");
  t.append(el("caption", null, "Share of votes so far and of registered voters"));
  const head = el("tr");
  for (const [txt, cls] of [["Group", "c-group"], ["Votes so far", "c-num"], ["Registered", "c-num"], ["Difference", "c-lead"]]) { const th = el("th", cls, txt); th.scope = "col"; head.append(th); }
  const thead = el("thead"); thead.append(head); t.append(thead);
  const tb = el("tbody");
  for (const [label, v, reg] of rows) {
    const tr = el("tr");
    const th = el("th", "c-group", label); th.scope = "row";
    const diff = Math.round(v) - Math.round(reg);
    tr.append(th, el("td", "c-num", `${Math.round(v)}%`), el("td", "c-num", `${Math.round(reg)}%`),
      el("td", `c-lead${diff ? "" : " is-even"}`, diff > 0 ? `${diff} pts over` : diff < 0 ? `${-diff} pts under` : "Even"));
    tb.append(tr);
  }
  t.append(tb); wrap.append(t); s3.append(wrap);
  box.append(s3);
  // Who hasn't voted yet.
  const s4 = el("div", "num-early-part");
  s4.append(el("h2", "num-h", "Who hasn’t voted yet"));
  const hb = ev.habit, hv = Object.values(hb).reduce((t, x) => t + x[0], 0);
  const notYet = ages.reduce((t, [, x]) => t + x[1], 0), youngNot = young[0][1] + young[1][1];
  s4.append(el("p", "num-lede", `${Math.round(pct(hb["4 of 4"][0], hv))}% of the votes so far came from people who voted in all four of the last four general elections. Of the ${fmtN(notYet)} registered voters who haven’t voted yet, ${Math.round(pct(youngNot, notYet))}% are under 35, against ${Math.round(pct(young[0][0] + young[1][0], votedA))}% of those who have. Election Day voters are likely to look different from the early vote.`));
  box.append(s4);
  // Past primary voting, both parties the same way: turnout as a share of each group.
  const pr = ev.primary, s5 = el("div", "num-early-part");
  s5.append(el("h2", "num-h", "Turnout by past primary voting"));
  const both = ks => pct(ks.reduce((t, k) => t + pr[k][0], 0), ks.reduce((t, k) => t + pr[k][0] + pr[k][1], 0));
  const dRate = both(["DEM Only", "DEM Mixed"]), rRate = both(["GOP Only", "GOP Mixed"]), noP = both(["General Only", "No History"]);
  s5.append(el("p", "num-lede", `${dRate.toFixed(1)}% of Texans who have voted in Democratic primaries have voted so far, and ${rRate.toFixed(1)}% of those who have voted in Republican primaries. Among people who voted in just one of the last four primaries: ${ev.new_primary_rate.D.toFixed(1)}% on the Democratic side, ${ev.new_primary_rate.R.toFixed(1)}% on the Republican side.`));
  s5.append(rateRows([["Democratic primary voters", dRate, `${dRate.toFixed(1)}% have voted`], ["Republican primary voters", rRate, `${rRate.toFixed(1)}% have voted`], ["No primary history", noP, `${noP.toFixed(1)}% have voted`]]));
  if (ev.dem_primaries && ev.gop_primaries) {
    const dn = ev.dem_primaries["1 of 4"], rn = ev.gop_primaries["1 of 4"];
    s5.append(el("p", "num-note", `For context: ${fmtN(dn[0] + dn[1])} registered Texans have voted in just one of the last four Democratic primaries, against ${fmtN(rn[0] + rn[1])} for Republican primaries, so the Democratic group includes more newer primary voters. Past primary voting is not party membership: Texas does not register voters by party.`));
  }
  box.append(s5);
  box.append(basedOn(`${gf.source}, as of ${gf.as_of || "the latest update"}. Ages and genders are as recorded on voter registration. Texas does not record race or party, so neither is shown here.`, "Transparency USA", gf.url));
  return box;
}

// Turnout by how each county voted for president in 2024, and the largest counties (Heston, 2026-10-27). Texas
// has no party registration, so this is as close as official numbers come; the caveat sits beside it.
function numTable(caption, cols, rows) {
  const wrap = el("div", "num-table-wrap");
  const t = el("table", "num-table");
  t.append(el("caption", null, caption));
  const head = el("tr");
  cols.forEach(([txt, cls]) => { const th = el("th", cls, txt); th.scope = "col"; head.append(th); });
  const thead = el("thead"); thead.append(head); t.append(thead);
  const tb = el("tbody");
  for (const r of rows) {
    const tr = el("tr");
    r.forEach((v, i) => { const c = el(i ? "td" : "th", cols[i][1], v); if (!i) c.scope = "row"; tr.append(c); });
    tb.append(tr);
  }
  t.append(tb); wrap.append(t);
  return wrap;
}
function countyBlock(ev) {
  // One chart, one measure (Heston, 2026-10-27: a share-of-vote chart and a turnout chart were "saying the same
  // thing with different numbers"). Pace, like the statewide pace above: each kind of county's in-person early
  // votes so far as a share of its own in 2024 over the same days of early voting. Comparing with 2024's whole
  // vote instead would mix in how much each kind of county votes early.
  const box = el("div", "num-early-part");
  const g = ev.by_2024;
  if (!g[0] || g[0].in_person_2024 == null) return box;
  const pace = x => pct(x.in_person, x.in_person_2024);
  const all = pct(g.reduce((t, x) => t + x.in_person, 0), g.reduce((t, x) => t + x.in_person_2024, 0));
  const days = (ev.early_2024_by_county || {}).days;
  const name = x => countyName(g, x);
  const byPace = [...g].sort((a, b) => pace(b) - pace(a));
  const hi = byPace[0], lo = byPace[byPace.length - 1];
  box.append(el("h2", "num-h", "By how each county voted in 2024"));
  box.append(el("p", "num-lede", `Early voting is closest to its 2024 level in ${name(hi)} (${Math.round(pace(hi))}% of 2024 at this point) and furthest behind in ${name(lo)} (${Math.round(pace(lo))}%). Statewide it is at ${Math.round(all)}%.`));
  box.append(el("h3", "num-h3", `Early votes so far, as a share of 2024 over the same ${days ? `${days} days` : "days"}`));
  const SHORT = COUNTY_SHORT;
  const chart = el("div", "cc"); chart.setAttribute("aria-hidden", "true");
  chart.append(el("span", "cc-ref", "2024 level"));
  const labels = el("div", "cd-labels"); labels.setAttribute("aria-hidden", "true");
  g.forEach((x, i) => {
    const v = pace(x);
    const cell = el("div", "cc-cell");
    const bar = el("i"); bar.style.height = `${Math.min(100, v) / 1.1}%`;
    const t = el("span", "cc-val", `${Math.round(v)}%`); t.style.bottom = `calc(${Math.min(100, v) / 1.1}% + 4px)`;
    cell.append(bar, t); chart.append(cell);
    const l = el("div");
    l.append(el("b", null, `${SHORT[i] || x.group} (${x.counties})`),
      el("span", null, `2026: ${fmtN(x.in_person)}`), el("span", null, `2024: ${fmtN(x.in_person_2024)}`));
    labels.append(l);
  });
  box.append(chart, el("p", "cd-axis", "How each county voted for president in 2024"), labels);
  box.append(el("p", "num-note", "In-person early votes only, both years, counted over the same days of early voting. The line marks 2024\u2019s level; a column at 80% means the counties have cast 80% as many early votes as by this point in 2024. The number after each label is how many counties are in the group."));
  const more = el("details", "num-more");
  more.append(el("summary", null, "Show the numbers"));
  more.append(numTable("In-person early votes so far, by the county\u2019s 2024 result for president",
    [["Counties", "c-group"], ["2026 so far", "c-num"], ["2024, same days", "c-num"], ["Pace", "c-num"]],
    g.map((x, i) => [`${COUNTY_GROUPS[i] || x.group} (${x.counties})`, fmtN(x.in_person), fmtN(x.in_person_2024), `${pace(x).toFixed(1)}%`])));
  box.append(more);
  const harris = (ev.largest || []).find(c => c.county === "Harris");
  box.append(el("p", "num-note", `A county’s 2024 result says nothing certain about who in it is voting now. Texas does not register voters by party, and every county has voters of both parties${harris ? `: Harris County (Houston), which Democrats won, also cast more Republican votes than any other Texas county` : ""}.`));
  if (ev.largest) {
    box.append(el("h3", "num-h3", "The 10 largest counties"));
    box.append(numTable("Early vote so far in the 10 counties with the most registered voters. 2024 margin: how far the Republican (R) or Democrat (D) won the county for president, in points",
      [["County", "c-group"], ["2024 margin", "c-num"], ["Voted so far", "c-num"], ["Turnout", "c-num"]],
      ev.largest.map(c => [c.county, `${c.margin_2024 > 0 ? "R" : "D"} +${Math.round(Math.abs(c.margin_2024))}`, fmtN(c.voted), `${pct(c.voted, c.registered).toFixed(1)}%`])));
  }
  box.append(basedOn(`${ev.source} for 2026. 2024 early votes by county: ${(ev.early_2024_by_county || {}).source || "Transparency USA"} (the Secretary of State\u2019s own 2024 daily figures are not open to automated reading). 2024 results: ${ev.results_2024.source}, summed by county (within 200 votes of the official statewide count for each candidate).`, "2024 results", ev.results_2024.url));
  return box;
}

// The votes already cast, if each group voted the way polls say it is voting: one estimate per lens. Not a
// projection of the result (Election Day voters differ), and not the forecast.
const LENS_NAME = { age: "By age", gender: "By gender", primary: "By past primary voting" };
function asPolledBlock(r, cands, ev) {
  const box = el("div", "num-aspolled");
  box.append(el("h2", "num-h", "The votes already cast, as polled"));
  const ap = r.as_polled;
  const same = ap.every(x => Math.sign(x.margin) === Math.sign(ap[0].margin) && Math.abs(x.margin) >= 0.5);
  box.append(el("p", "num-lede", `If the ${fmtN(ev.voted)} Texans who have voted split the way polls say their groups are splitting, the early vote so far would be about ${ap.map(x => `${gapText(x.margin, cands)} ${LENS_NAME[x.lens].toLowerCase()}`).join(", ")}. `
    + (ap.every(x => Math.abs(x.margin) < 3) ? `Every way of counting comes out close to even.`
      : ap.length > 1 ? (same ? `Each way of counting points the same direction.` : `The ways of counting disagree: too close to read.`) : "")));
  const max = Math.max(10, Math.ceil(Math.max(...ap.map(x => Math.abs(x.margin))) / 10) * 10);
  box.append(trackAxis(max, cands));
  const ul = el("ul", "num-rows");
  for (const x of ap) {
    const li = el("li", "num-row");
    const who = el("div", "num-who");
    who.append(el("span", "num-name", LENS_NAME[x.lens]), el("span", "num-meta", `group numbers from ${plural(x.polls, "poll", "polls")}`));
    const val = el("div", "num-val");
    val.append(el("span", "num-gap", gapText(x.margin, cands)));
    li.append(who, track(x.margin, null, max), val);
    ul.append(li);
  }
  box.append(ul);
  box.append(el("p", "num-note", "This describes ballots already cast, not the result: the people still to vote are younger and vote less often. It is separate from the forecast."));
  box.append(basedOn("who has voted (Transparency USA, from the Texas voter rolls) and each group\u2019s margin as the middle of the confirmed polls that report it. Age bands that differ are matched year by year; voters with no primary history are counted with independents.", "Who has voted", ev.url));
  return box;
}

function historyBlock(h, leads) {
  // leads: [{name, lead}] for each race today (from the forecast's center), so the miss is read against them.
  const box = el("div", "num-history");
  box.append(el("h2", "num-h", "Final polls vs. results, 2016 to 2024"));
  const races = h.races;
  const better = races.filter(r => r.miss > 0).length, worse = races.filter(r => r.miss < 0).length;
  const now = leads.filter(l => l.lead != null);
  const all = now.every(l => l.lead < h.typical_miss) ? "smaller" : now.every(l => l.lead >= h.typical_miss) ? "bigger" : null;
  box.append(el("p", "num-lede", `Since 2016 the final polling average missed by ${pts(h.typical_miss)} points on average, in both directions: the Republican did better than the polls in ${better} of ${races.length} races and worse in ${worse}.`
    + (now.length === 1 ? ` The lead in ${now[0].name}, ${pts(now[0].lead)} points in the middle of the published averages, is ${all} than that.`
      : now.length ? ` Today's leads (${now.map(l => `${l.name} ${pts(l.lead)}`).join(", ")} points) are ${all ? `both ${all} than that` : "on either side of that"}.` : "")));
  const max = Math.max(5, Math.ceil(Math.max(...races.map(r => Math.abs(r.miss))) / 5) * 5);
  const sides = el("div", "num-sides");
  sides.setAttribute("aria-hidden", "true");
  sides.append(el("span", null, "← Democrat beat the polls"), el("span", null, "Republican beat the polls →"));
  box.append(sides);
  const ul = el("ul", "num-rows num-hist");
  for (const r of [...races].reverse()) {
    const li = el("li", "num-row");
    const who = el("div", "num-who");
    who.append(el("span", "num-name", `${r.year} · ${r.office}`), el("span", "num-meta", `${r.r.split(" ").pop()} (R) vs. ${r.d.split(" ").pop()} (D)`));
    const t = el("div", "num-track miss");
    t.setAttribute("aria-hidden", "true");
    t.append(el("i", "num-tie"));
    const b = el("i", "num-bar");
    const w = 50 * Math.min(1, Math.abs(r.miss) / max);
    b.style.left = r.miss >= 0 ? "50%" : `${50 - w}%`;
    b.style.width = `${w}%`;
    t.append(b);
    const val = el("div", "num-val");
    val.append(el("span", "num-gap", `${r.miss > 0 ? "R" : "D"} beat by ${pts(r.miss)}`),
      el("span", "num-moe", `polls R+${pts(r.poll.margin)} · won R+${pts(r.result_margin)}`));
    li.append(who, t, val);
    ul.append(li);
  }
  box.append(ul);
  const src = el("details", "num-more");
  src.append(el("summary", null, "Sources for each race"));
  const sl = el("ul", "num-unconf");
  for (const r of races) {
    const li = el("li");
    li.append(el("span", "num-name", `${r.year} ${r.office}`));
    const a1 = el("a", null, `${r.poll.source} ↗`); a1.href = r.poll.url; a1.rel = "noopener";
    const a2 = el("a", null, `${r.result.source} ↗`); a2.href = r.result.url; a2.rel = "noopener";
    const m = el("span", "num-meta"); m.append(a1, document.createTextNode(" · "), a2);
    li.append(m);
    sl.append(li);
  }
  src.append(sl);
  box.append(src);
  box.append(basedOn("RealClearPolitics' final average for every Texas race for President, U.S. Senate and Governor since 2016, read from archived copies of its pages, against the official count."));
  return box;
}

function moneyBlock(m, cands) {
  const box = el("div", "num-money");
  box.append(el("h2", "num-h", m && m.source === "FEC" ? "The campaigns and outside groups" : "Cash on hand"));
  if (!m || !m.candidates || !m.candidates.length) {
    box.append(el("p", "num-note", "We could not load the campaign finance reports this time. Each scan tries again."));
    return box;
  }
  // Totals first, one per candidate (Heston, 2026-10-27): what the campaign raised plus what outside groups
  // spent on that candidate's side (for them, or against the opponent), with the two parts shown under it.
  const M = v => `$${(v / 1e6).toFixed(1)} million`;
  if (m.source === "FEC" && m.candidates.every(c => c.raised != null)) {
    const sideOf = new Map((sideSpending(m) || []).map(([c, v]) => [c, v]));
    const strip = el("dl", "money-totals");
    for (const c of m.candidates) {
      const out = sideOf.has(c) ? sideOf.get(c) : null;
      const d = el("div", "money-total");
      d.append(el("dt", null, `${c.name}, in all`), el("dd", null, M(c.raised + (out || 0))),
        el("dd", "money-total-parts", out == null ? "Raised by the campaign" : `${M(c.raised)} raised by the campaign + ${M(out)} from outside groups`));
      strip.append(d);
    }
    box.append(strip);
  }
  const sides = sideSpending(m);
  if (sides) box.append(el("p", "num-lede", "Outside money on a candidate\u2019s side is what outside groups spent for that candidate plus what they spent against the opponent, in the general election. The campaign\u2019s money is what it raised over the whole 2026 cycle."));
  const rows = [["Raised by the campaign", "raised"], ["Cash on hand", "cash"]];
  // Outside spending is shown only once the scan marks it checked (m.outside_ok): FEC raw filings can list the same
  // spending twice, in a 24/48-hour notice and again in the regular report (caught 2026-10-20).
  if (m.source === "FEC" && m.outside_ok) rows.push(["Outside groups spent for", "outside_support"], ["Outside groups spent against", "outside_oppose"]);
  const ul = el("ul", "money-list");
  for (const [label, k] of rows.filter(([, k]) => m.candidates.some(c => c[k] != null))) {
    const li = el("li", "money-row");
    li.append(el("p", "money-label", label));
    const top = Math.max(1, ...m.candidates.map(c => c[k] || 0));
    for (const c of m.candidates) {
      const line = el("div", "money-line");
      const bar = el("i", "money-bar");
      bar.setAttribute("aria-hidden", "true");
      bar.style.width = `${Math.max(1, 100 * (c[k] || 0) / top)}%`;
      const barWrap = el("span", "money-track"); barWrap.append(bar);
      line.append(el("span", "money-name", c.name.split(" ").pop()), barWrap, el("span", "money-usd", usd(c[k])));
      li.append(line);
    }
    ul.append(li);
  }
  box.append(ul);
  if (m.source === "FEC" && m.outside_ok) {
    // Largest first, so the biggest spending (often against a candidate) is never hidden in "and N more".
    const groups = m.candidates.flatMap(c => [...(c.top_support || []).map(g => [g.usd, `${g.group} (${usd(g.usd)} for ${surname(c)})`]), ...(c.top_oppose || []).map(g => [g.usd, `${g.group} (${usd(g.usd)} against ${surname(c)})`])])
      .sort((a, b) => b[0] - a[0]).map(([, t]) => t);
    if (groups.length) box.append(el("p", "num-note", `Biggest outside spenders: ${listNames(groups, 6)}.`));
  }
  const through = m.candidates.map(c => c.through).filter(Boolean).sort().pop();
  const when = through ? (through.length === 8 ? `${through.slice(0, 4)}-${through.slice(4, 6)}-${through.slice(6)}` : through) : null;
  box.append(basedOn(`${m.note}${when ? ` Reports through ${shortDate(when)}.` : ""}`, m.source === "FEC" ? "FEC filings" : "Texas Ethics Commission", (m.candidates[0] || {}).url));
  return box;
}

// The race numbers are stories of their own, never inside the coverage (Heston, 2026-10-20). Two per race
// (Heston, 2026-10-23): latest polls (forecast, polls, published averages, past misses, which polls each side
// reported) and campaign funding. They lead the Texas Election section, then come the stories.
const NUMBER_RACES = [{ race: "tx-senate", office: "U.S. Senate", slug: "senate" }, { race: "tx-governor", office: "Governor", slug: "governor" }];
const NUMBER_STORIES = NUMBER_RACES.flatMap(r => {
  const name = `Texas ${r.office === "U.S. Senate" ? "Senate" : r.office} race`;
  return [
    { key: `${r.slug}-polls`, race: r.race, kind: "polls", title: `${name}: latest polls` },
    { key: `${r.slug}-groups`, race: r.race, kind: "groups", title: `${name}: polls by group` },  // Heston, 2026-10-26
    { key: `${r.slug}-funding`, race: r.race, kind: "funding", title: `${name}: campaign funding` },
  ];
});
// The early vote is statewide: the same voters decide both races (Heston, 2026-10-26).
const EARLY_STORY = { key: "early-vote", kind: "early", title: "Texas early vote: who has voted so far" };
// Without the voter groups (age, gender, past voting) the story is the count alone, and says so.
const earlyTitle = ev => ev && ev.age ? EARLY_STORY.title : "Texas early vote: turnout so far";
const numberTitle = (n, nums) => n.kind === "early" ? earlyTitle(nums && nums.early_vote) : n.title;
NUMBER_STORIES.unshift(EARLY_STORY);
// Election night (Heston, 2026-10-30): the Secretary of State's unofficial count, read by our server
// (api/results.php) and shown once counting starts. The count and the share reporting; never a call.
const RESULTS_STORY = { key: "results", kind: "results", title: "Texas results: the count so far" };
NUMBER_STORIES.unshift(RESULTS_STORY);
const RESULTS_API = "api/results.php";
let TXRES = null;  // the count, once api/results.php says counting has started
const getResults = () => CAPSULE ? Promise.resolve(null) : getJSON(RESULTS_API, true).then(r => (r && r.live && r.counted ? r : null));
// A number story is shown when it has something to show: polls by group only once switched on and read.
const numberShown = (n, nums) => n.kind === "results" ? !!TXRES : n.kind === "early" ? !!(nums.early_vote && nums.early_vote.voted)
  : !!nums.races[n.race] && (n.kind !== "groups" || (nums.groups_live && Object.keys(nums.races[n.race].groups || {}).length > 0));

// The feed's names are in capitals: "GREG ABBOTT (I)", "R.F. \"BOB\" ACHGILL", "KEVIN MCCORMICK".
const PARTY = { REP: "Republican", DEM: "Democrat", LIB: "Libertarian", GRE: "Green", IND: "Independent", W: "Write-in" };
const nameCase = s => s.toLowerCase().replace(/(^|[\s\-'".(])(\p{L})/gu, (m, a, b) => a + b.toUpperCase())
  .replace(/\bMc(\p{L})/gu, (m, a) => `Mc${a.toUpperCase()}`).replace(/\b(Ii|Iii|Iv)\b/g, m => m.toUpperCase()).replace(/\bJr\b\.?/g, "Jr.");
const candName = c => nameCase(c.name.replace(/\s*\(I\)\s*$/, "")) + (/\(I\)\s*$/.test(c.name) ? " (incumbent)" : "");
// Office names capitalized alike (Heston, 2026-10-20).
const OFFICE = { "U. S. SENATOR": "U.S. Senate", "COMPTROLLER OF PUBLIC ACCOUNTS": "Comptroller",
  "COMMISSIONER OF THE GENERAL LAND OFFICE": "Land Commissioner", "COMMISSIONER OF AGRICULTURE": "Agriculture Commissioner" };
const officeName = o => OFFICE[o] || nameCase(o).replace(/\bOf\b/g, "of").replace(/\bThe\b/g, "the").replace(/ - Unexpired Term$/, " (unexpired term)");
// "Nov 3, 2026 21:42:07" (the state's own clock, Central) -> "9:42 pm, Nov 3"
const sosTime = t => { const m = /^(\w+) (\d+), \d+ (\d+):(\d+)/.exec(t || ""); if (!m) return t;
  const h = +m[3]; return `${h % 12 || 12}:${m[4]} ${h < 12 ? "am" : "pm"}, ${m[1]} ${m[2]}`; };
const reportingShare = res => pct(res.polling_places[0], res.polling_places[1]);
const shareText = v => v > 0 && v < 1 ? "under 1" : v > 99 && v < 100 ? "over 99" : String(Math.round(v));

function resultsGist(res) {
  const r = res.races[0];
  const top = [...r.candidates].sort((a, b) => b.votes - a.votes).filter(c => c.party !== "W").slice(0, 2);
  const shares = top.map(c => `${nameCase(c.last)} ${fmtN(c.votes)} (${pct(c.votes, r.total).toFixed(1)}%)`);
  return `${officeName(r.office)} so far: ${shares.join(", ")}. Polling places reporting: ${shareText(reportingShare(res))}%. Unofficial; no race is called here.`;
}

function resultsRace(r) {
  const box = el("div", "num-early-part results-race");
  box.append(el("h2", "num-h", officeName(r.office)));
  // Write-in candidates share one row: most are not counted until the official canvass.
  const named = r.candidates.filter(c => c.party !== "W");
  const writeIns = r.candidates.filter(c => c.party === "W");
  const rows = named.map(c => ({ label: `${candName(c)} · ${PARTY[c.party] || c.party}`, votes: c.votes, early: c.early, ballot: c.ballot }));
  if (writeIns.length) rows.push({ label: `Write-in candidates (${writeIns.length})`, votes: writeIns.reduce((t, c) => t + c.votes, 0), ballot: 1e9 });
  // Most votes first once there are votes; before that, ballot order. Order is the count, not a call.
  rows.sort((a, b) => r.total ? b.votes - a.votes : a.ballot - b.ballot);
  const ul = el("ul", "rate-list");
  for (const x of rows) {
    const li = el("li", "rate-row");
    const bar = el("div", "rate-bar"); bar.setAttribute("aria-hidden", "true");
    const f = el("i"); f.style.width = `${pct(x.votes, r.total)}%`; bar.append(f);
    li.append(el("span", "rate-label", x.label), el("span", "rate-text", `${fmtN(x.votes)} · ${pct(x.votes, r.total).toFixed(1)}%`), bar);
    ul.append(li);
  }
  const early = r.candidates.reduce((t, c) => t + c.early, 0);
  box.append(ul, el("p", "num-note", `${fmtN(r.total)} votes counted in this race${r.total ? `, ${fmtN(early)} of them cast early (in person or by mail)` : ""}.`));
  return box;
}

function resultsBlock(res) {
  const box = el("div", "num-early");
  if (!res) {
    box.append(el("h2", "num-h", "No votes counted yet"));
    box.append(el("p", "num-lede", "The count appears here once the counties start reporting, after polls close at 7 pm Central on Tuesday, November 3 (8 pm Central in El Paso and Hudspeth counties, which keep Mountain time)."));
    return box;
  }
  const [pp, ppAll] = res.polling_places, [co, coAll] = res.counties;
  box.append(el("h2", "num-h", "Reporting"));
  box.append(el("p", "num-lede", `Polling places reporting: ${fmtN(pp)} of ${fmtN(ppAll)} (${shareText(reportingShare(res))}%). Counties reporting: ${co} of ${coAll}. These are unofficial results as the counties send them in. We show the count; we never call a race or project a winner.`));
  box.append(basedOn(`the Texas Secretary of State’s unofficial election night results, as last updated by the state at ${sosTime(res.updated)} Central; read by us ${Math.max(1, Math.round((Date.now() - Date.parse(res.checked_at)) / 60000))} min ago. Official results come from the state canvass weeks later.`, "Secretary of State results", res.source));
  const [first, second, ...rest] = res.races;
  for (const r of [first, second].filter(Boolean)) box.append(resultsRace(r));
  if (rest.length) {
    const more = el("details", "results-more");
    more.append(el("summary", null, `Other statewide races (${rest.length})`));
    for (const r of rest) more.append(resultsRace(r));
    box.append(more);
  }
  return box;
}
const pct = (a, b) => b ? 100 * a / b : 0;
const fmtN = n => n.toLocaleString("en-US");
const OLD_NUMBER_KEYS = { senate: "senate-polls", governor: "governor-polls" };  // links shared before the split
let TXNUM = null;  // data/tx-numbers.json, once loaded
// The Texas Election section's header picture: the Capitol, with the Texas flag (Commons, CC BY 3.0, credited).
const TX_HEADER = { src: "img/texas-capitol-v1.jpg", alt: "The Texas State Capitol in Austin, under a blue sky",
  caption: "Texas State Capitol, Austin. Photo: LoneStarMike \u00b7 CC BY 3.0 \u00b7 Wikimedia Commons",
  source: "https://commons.wikimedia.org/wiki/File:TexasStateCapitol-2010-01.JPG" };
const txNumbersURL = () => { const key = CAPSULE ? sget("fx-capsule", sessionStorage) : null; return key ? `data/capsule/${key}/tx-numbers.json` : "data/tx-numbers.json"; };
const raceLead = r => r && r.forecast ? Math.abs(r.forecast.center) : null;

// Outside money on each candidate's side: spent for them plus spent against their opponent.
function sideSpending(m) {
  if (!m || !m.outside_ok || !m.candidates || m.candidates.length !== 2) return null;
  const [a, b] = m.candidates;
  return [[a, (a.outside_support || 0) + (b.outside_oppose || 0)], [b, (b.outside_support || 0) + (a.outside_oppose || 0)]];
}

// One sentence per card, computed from the numbers.
function numbersGist(n, nums) {
  if (n.kind === "early") {
    const ev = nums.early_vote;
    const first = `${fmtN(ev.voted)} Texans have voted, ${pct(ev.voted, ev.registered).toFixed(1)}% of registered voters.`;
    if (!ev.age) return ev.mail != null ? `${first} ${fmtN(ev.mail)} of the votes came by mail.` : first;
    const old = ev.age["65+"][0], all = Object.values(ev.age).reduce((t, x) => t + x[0], 0);
    return `${first} People 65 and over cast ${Math.round(pct(old, all))}% of the votes so far.`;
  }
  const r = nums.races[n.race];
  if (!r) return "";
  const c = r.candidates;
  if (n.kind === "polls") {
    const f = r.forecast;
    const gaps = r.averages.map(a => gapOf(a.shares));
    const same = gaps.length && gaps.every(g => Math.sign(g) === Math.sign(gaps[0]) && g !== 0);
    const abs = gaps.map(Math.abs);
    const avg = !gaps.length ? "" : same
      ? ` ${surname(c[gaps[0] > 0 ? 0 : 1])} ahead by ${pts(Math.min(...abs))} to ${pts(Math.max(...abs))} points in ${plural(gaps.length, "published average", "published averages")}.`
      : ` The ${gaps.length} published averages disagree on who is ahead.`;
    const fc = f ? `${f.chance[0] > f.chance[1] ? c[0].name : c[1].name}, ${Math.max(...f.chance)}% chance to win.` : "";
    return `${fc}${avg}`.trim();
  }
  if (n.kind === "groups") {
    const g = r.groups || {};
    const polls = new Set(Object.values(g).flatMap(x => Object.values(x).flat().map(p => p.pollster + p.end)));
    const cats = GROUP_CATS.filter(([k]) => g[k]).map(([, label]) => label.toLowerCase());
    return `How each group leans, poll by poll: ${listNames(cats, 6)}, from ${plural(polls.size, "poll", "polls")}.`;
  }
  const m = r.money;
  if (!m || !m.candidates || !m.candidates.length) return "Campaign finance reports, as filed.";
  const sides = sideSpending(m);
  if (m.source === "FEC") {
    const raised = m.candidates.filter(x => x.raised != null).sort((x, y) => y.raised - x.raised).map(x => `${surname(x)} ${usd(x.raised)}`).join(", ");
    return `Raised: ${raised}.` + (sides ? ` Outside groups: ${sides.sort((x, y) => y[1] - x[1]).map(([x, v]) => `${usd(v)} on ${surname(x)}\u2019s side`).join(", ")}.` : "");
  }
  return `Cash on hand: ${m.candidates.filter(x => x.cash != null).sort((x, y) => y.cash - x.cash).map(x => `${surname(x)} ${usd(x.cash)}`).join(", ")}.`;
}

function numbersCards(nums) {
  const box = el("div", "numbers-group");
  box.append(el("h3", "numbers-group-h", "By the numbers"));
  if (TXRES) {
    const g = el("div", "numbers-race");
    g.append(el("h4", "numbers-race-h", "Statewide \u00b7 results"));
    const ol = el("ol", "stories numbers-pair");
    ol.setAttribute("aria-label", "Election results");
    const li = el("li", "story story-data");
    const main = el("div", "story-main");
    main.append(el("p", "story-when", agoText(Date.parse(TXRES.checked_at))));
    const h = el("h2", "headline");
    const a = el("a", null, "Results: the count so far");
    a.href = `numbers.html?n=${RESULTS_STORY.key}`;
    h.append(a);
    main.append(h, el("p", "gist", resultsGist(TXRES)));
    li.append(main);
    ol.append(li);
    g.append(ol);
    box.append(g);
  }
  if (numberShown(EARLY_STORY, nums)) {
    const g = el("div", "numbers-race");
    g.append(el("h4", "numbers-race-h", "Statewide \u00b7 early voting"));
    const ol = el("ol", "stories numbers-pair");
    ol.setAttribute("aria-label", "Early voting numbers");
    const li = el("li", "story story-data");
    const main = el("div", "story-main");
    main.append(el("p", "story-when", agoText(Date.parse(nums.updated_at))));
    const h = el("h2", "headline");
    const a = el("a", null, earlyTitle(nums.early_vote).replace(/^Texas e/, "E"));
    a.href = `numbers.html?n=${EARLY_STORY.key}`;
    h.append(a);
    main.append(h, el("p", "gist", numbersGist(EARLY_STORY, nums)));
    li.append(main);
    ol.append(li);
    g.append(ol);
    box.append(g);
  }
  for (const R of NUMBER_RACES) {
    const r = nums.races[R.race];
    if (!r) continue;
    const g = el("div", "numbers-race");
    g.append(el("h4", "numbers-race-h", `${R.office} \u00b7 ${r.candidates.map(x => `${x.name} (${x.party})`).join(" vs. ")}`));
    const ol = el("ol", "stories numbers-pair");
    ol.setAttribute("aria-label", `${R.office} numbers`);
    for (const n of NUMBER_STORIES.filter(n => n.race === R.race && numberShown(n, nums))) {
      const li = el("li", "story story-data");
      const main = el("div", "story-main");
      main.append(el("p", "story-when", agoText(Date.parse(nums.updated_at))));
      const h = el("h2", "headline");
      // Card titles (Heston, 2026-10-24): "Senate race: latest polls"; the section already says Texas.
      const a = el("a", null, n.title.replace(/^Texas /, ""));
      a.href = `numbers.html?n=${n.key}`;
      h.append(a);
      main.append(h, el("p", "gist", numbersGist(n, nums)));
      li.append(main);
      ol.append(li);
    }
    g.append(ol);
    box.append(g);
  }
  return box;
}

function renderNumbers(nums) {
  const q = new URLSearchParams(location.search).get("n");
  const n = NUMBER_STORIES.find(x => x.key === (OLD_NUMBER_KEYS[q] || q)) || EARLY_STORY;
  const body = $("story-body");
  document.title = `${numberTitle(n, nums)} · fACTUAL`;
  $("story-title").textContent = numberTitle(n, nums);
  $("story-meta").textContent = n.kind === "results" ? `Texas Election \u00b7 Results${TXRES ? ` \u00b7 Read ${stamp(TXRES.checked_at)}` : ""}`
    : `Texas Election \u00b7 By the numbers \u00b7 Updated ${stamp(nums.updated_at)}`;
  const tools = el("div", "story-tools");
  const back = el("a", "back-link");
  back.append(el("span", "back-arrow", "\u2190"), document.createTextNode(" Texas Election"));
  back.querySelector(".back-arrow").setAttribute("aria-hidden", "true");
  back.href = "./#texas";
  tools.append(back);
  $("story-meta").before(tools);
  const sec = el("section", "block numbers");
  const r = n.race && nums.races[n.race];
  if (n.kind === "early") sec.append(earlyBlock(nums.early_vote));
  if (n.kind === "results") {
    let block = resultsBlock(TXRES);
    sec.append(block);
    // The count changes through the night: read again every two minutes, in place.
    setInterval(() => getResults().then(r => { if (!r) return; TXRES = r; const b = resultsBlock(r); block.replaceWith(b); block = b;
      $("story-meta").textContent = `Texas Election \u00b7 Results \u00b7 Read ${stamp(r.checked_at)}`; }).catch(() => {}), 120000);
  }
  if (r) {
    const c = r.candidates;
    $("story-sub").append(el("p", "byline", c.map(x => `${x.name} (${x.party})`).join(" vs. ")));
    const sum = n.kind === "polls" ? pollsSummary(r, c, nums) : n.kind === "groups" ? groupsSummary(r, c) : moneySummary(r.money, c);
    if (sum.length) { const b = summaryBox(sum); b.append(summaryBasis()); sec.append(b); }
    if (n.kind === "polls") {
      if (r.forecast) sec.append(forecastBlock(r.forecast, c));
      sec.append(pollsBlock(r, c, nums.recent_days || 30));
      if (nums.history) sec.append(historyBlock(nums.history, [{ name: "this race", lead: raceLead(r) }]));
      sec.append(citedBlock(r, c));
    } else if (n.kind === "groups") {
      if ((r.as_polled || []).length && nums.early_vote) sec.append(asPolledBlock(r, c, nums.early_vote));
      sec.append(groupsBlock(r, c, nums));
    } else {
      sec.append(moneyBlock(r.money, c));
    }
  }
  // The other number stories, so each is one tap away.
  const more = el("ul", "num-next");
  for (const o of NUMBER_STORIES.filter(o => o !== n && numberShown(o, nums))) {
    const li = el("li"); const a = el("a", null, `${numberTitle(o, nums)} \u2192`); a.href = `numbers.html?n=${o.key}`; li.append(a); more.append(li);
  }
  sec.append(more);
  body.append(sec);
  const foot = el("p", "disclosure");
  foot.append(document.createTextNode(n.kind === "results" ? "Read from the Secretary of State by code. No AI, no human review. "
    : "Gathered and checked by code, with AI reading poll releases. No human review. "));
  const m = el("a", null, "Method \u2192");
  m.href = "how.html";
  foot.append(m);
  body.append(foot);
  initSwipeBack();
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
    initSwipeBack();
    return;
  }
  document.title = `${story.working_title} · fACTUAL`;
  $("story-meta").textContent = `${topicName(story.topic) ? topicName(story.topic) + " \u00b7 " : ""}${data.archiveDay ? `From the archive \u00b7 ${dayName(data.archiveDay)}` : `Updated ${clock(data.scanned_at)}`}`;
  $("story-title").textContent = story.working_title;
  const tools = el("div", "story-tools");
  tools.append(backLink(story, data));
  $("story-meta").before(tools);
  initSwipeBack();
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

  // The full story (Heston, 2026-10-24: readers want to read all of it), written by the scan from this page's own
  // material: both sides' facts plainly, one side's facts attributed, each version of a split with its outlets.
  const full = brief && brief.full_story;
  if (full && full.length) {
    const sf = el("section", "block full-story");
    sf.id = "full-story";
    sf.append(el("h2", "block-title", "The full story"));
    // A preview, then the rest on request (Heston, 2026-10-24: don't push the splits and checks down). The first
    // paragraph is always what both sides report.
    sf.append(el("p", "full-p", full[0].map(x => x.text).join(" ")));
    const rest = el("div", "full-rest");
    rest.id = "full-rest";
    for (const para of full.slice(1)) rest.append(el("p", "full-p", para.map(x => x.text).join(" ")));
    const basis = el("p", "num-basis");
    basis.append(el("strong", null, "Based on "), document.createTextNode("only the facts and splits on this page. What both sides report is stated plainly; anything one side reports names its outlets. Written by AI; every name and number checked in code against that material."));
    if (full.length > 1) {
      rest.hidden = true;
      const more = el("button", "full-toggle", "Read the full story");
      more.type = "button";
      more.setAttribute("aria-expanded", "false");
      more.setAttribute("aria-controls", "full-rest");
      more.addEventListener("click", () => {
        const open = rest.hidden;
        rest.hidden = !open;
        more.setAttribute("aria-expanded", String(open));
        more.textContent = open ? "Show less" : "Read the full story";
      });
      sf.append(rest, more);
    } else {
      rest.hidden = false;
      sf.append(rest);
    }
    sf.append(basis);  // the basis rule: what it rests on is always in view, preview or not
    body.append(sf);
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

  // Texas Election: the claims driving the race (ads, attacks, speeches, posts, claims about voting), each checked.
  const ads = (brief && brief.ad_claims) || [];
  if (ads.length) {
    const sa = el("section", "block");
    sa.id = "ads";
    sa.append(el("h2", "block-title", "Claims in the race \u00b7 checked"));
    const ul = el("ul", "ad-list");
    for (const a of ads) {
      const li = el("li", "ad-item");
      li.append(el("p", "ad-who", `${a.speaker}${a.kind === "ad" ? " ad" : ""}${a.target ? ` \u00b7 about ${a.target}` : ""}`));
      const c = claimOf(data.library, a.check);
      li.append(c ? claimDetails(c) : pendingCheck(a.assertion, ""));
      const by = el("p", "ad-by", "Reported by ");
      a.outlets.forEach((o, i) => { if (i) by.append(document.createTextNode(", ")); by.append(ARTICLE[o] ? sourceLink(o, ARTICLE[o]) : document.createTextNode(o)); });
      li.append(by);
      ul.append(li);
    }
    sa.append(ul);
    body.append(sa);
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
  const fx = el("a", null, "Corrections \u2192");
  fx.href = "corrections.html";
  foot.append(m, document.createTextNode(" \u00b7 "), fx);
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
// Swiping back from an article goes to Today (Heston, 2026-10-28).
// - Came from Today in a browser: the browser's own back swipe already gets there. Left alone.
// - Otherwise (the home-screen app, where iOS gives web apps no back swipe; a shared link with nothing behind
//   it; Chrome and Safari skip history entries a page adds without a tap, so seeding history isn't enough): a
//   swipe right, from anywhere on the article, slides it away and goes back the way the back link does. A swipe
//   that starts on something that scrolls sideways (a wide table or chart) is left to scroll.
function initSwipeBack() {
  const link = document.querySelector(".back-link");
  const target = link ? link.href : new URL("./", location.href).href;
  const app = document.documentElement.classList.contains("app");
  let from = null;
  try { from = document.referrer && new URL(document.referrer); } catch (e) {}
  const sameSite = from && from.origin === location.origin;
  // Shared link: also put Today behind the article, for browsers that keep the entry (back button, swipe).
  if (!app && !sameSite && !(history.state && history.state.fxSeeded)) {
    const here = location.href;
    try {
      history.replaceState({ fxHome: target }, "", target);
      history.pushState({ fxSeeded: true }, "", here);
    } catch (e) {}
  }
  // Back to that entry: the address is already Today's, but the page is still the article. Today's address can
  // differ from the article's only after "#", which the browser would treat as a jump within the page, so reload.
  addEventListener("popstate", e => { if (e.state && e.state.fxHome) location.reload(); });
  if (!app && sameSite) return;
  const main = document.getElementById("main");
  if (!main) return;
  const calm = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scrollsSideways = node => {
    for (let n = node; n && n !== document.body; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(n).overflowX)) return true;
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(n.tagName) || n.isContentEditable) return true;
    }
    return false;
  };
  let x0 = null, y0 = 0, t0 = 0, dx = 0, axis = null;
  const reset = () => { x0 = null; main.style.transition = calm ? "none" : "transform 200ms ease-out"; main.style.transform = ""; };
  addEventListener("touchstart", e => {
    if (e.touches.length !== 1 || scrollsSideways(e.target)) return;
    const t = e.touches[0];
    x0 = t.clientX; y0 = t.clientY; t0 = Date.now(); dx = 0; axis = null;
    main.style.transition = "none";
  }, { passive: true });
  addEventListener("touchmove", e => {
    if (x0 == null) return;
    const t = e.touches[0], mx = t.clientX - x0, my = t.clientY - y0;
    if (!axis && (Math.abs(mx) > 10 || Math.abs(my) > 10)) axis = mx > 0 && Math.abs(mx) > 1.5 * Math.abs(my) ? "x" : "y";
    if (axis === "y") { x0 = null; return; }
    if (axis !== "x") return;
    if (e.cancelable) e.preventDefault();
    dx = Math.max(0, mx);
    if (!calm) main.style.transform = `translateX(${dx}px)`;
  }, { passive: false });
  addEventListener("touchend", () => {
    if (x0 == null) return;
    x0 = null;
    if (axis === "x" && (dx > innerWidth / 3 || (dx > 50 && dx / Math.max(1, Date.now() - t0) > 0.5))) {
      if (!calm) { main.style.transition = "transform 180ms ease-out"; main.style.transform = `translateX(${innerWidth}px)`; }
      setTimeout(() => (link ? link.click() : location.assign(target)), calm ? 0 : 170);
    } else reset();
  });
  addEventListener("touchcancel", reset);
  addEventListener("pageshow", () => { main.style.transition = "none"; main.style.transform = ""; });  // back again from the cache
}

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
    const when = data.archiveDay ? null : updatedAgo(s);
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
  // Share sits top right on every page: a story shares itself (renderStory adds that one); a number story
  // shares its preview page (s/n-<key>.html, written by each scan, so messages show its own card); any other
  // page shares its own address, without query or fragment. The capsule key and state never travel.
  if (page !== "story") {
    const shareTo = () => {
      const here = location.origin + location.pathname.replace(/index\.html$/, "");
      if (page !== "numbers") return here;
      const q = new URLSearchParams(location.search).get("n");
      const n = NUMBER_STORIES.find(x => x.key === (OLD_NUMBER_KEYS[q] || q)) || EARLY_STORY;
      return `${new URL("./", location.href).href}s/n-${n.key}.html`;
    };
    const b = makeShare(() => document.title, shareTo, "Share");
    b.classList.add("share-top");
    b.setAttribute("aria-label", "Share this page");
    const right = document.querySelector(".mast-right");
    if (right) right.insertBefore(b, right.querySelector(".settings"));
  }
  if (page === "archive") return renderArchive(await getJSON("data/archive/index.json", true));
  if (page === "common") return renderCommon(await getJSON("common-ground.json"));
  if (page === "how") return renderHow(await getJSON("data/stories.json", true));
  if (page === "corrections") return renderCorrections(await getJSON("data/library.json", true));
  if (page === "numbers") {
    // The investors' key shows the numbers as they stood at the cutoff, like the rest of the edition.
    const k = sget("fx-capsule", sessionStorage);
    const cap = k ? await getJSON(`data/capsule/${k}/tx.json`, true) : null;
    if (cap && Date.now() >= Date.parse(cap.frozen_at)) { CAPSULE = cap; capsuleBar(cap); }
    const [nums, res] = await Promise.all([getJSON(txNumbersURL()), getResults()]);
    TXRES = res;
    return renderNumbers(nums);
  }
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
