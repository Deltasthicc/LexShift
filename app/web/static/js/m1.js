// The Index page: M1's pipeline, explained with the real index on disk.
//
// Every number and every row on this page comes from /api/m1/*, which reads M1's index and calls M1's own functions. Nothing here is a
// stored example. A piece of the owner's list that the pushed code does not contain is marked "not in the pushed code", not described
// as if it worked. All text from the index is inserted as text, never as markup.

import { $, $$, h, clear, show, formatBytes } from "./dom.js";
import { api } from "./api.js";
import { animateIn, countUp, motionOn, requestFrame, scrollToTarget } from "./motion.js";
import { toast } from "./ui.js";

const gsap = window.gsap;
const ScrollTrigger = window.ScrollTrigger;

const num = (n) => (typeof n === "number" && Number.isFinite(n) ? n.toLocaleString("en-US") : "n/a");
const ZONES = ["headnote", "facts", "arguments", "holding"];
const ZONE_NAME = { headnote: "Headnote", facts: "Facts", arguments: "Arguments", holding: "Holding" };

const SAMPLES = [
  { kind: "One term", q: "murder" },
  { kind: "Plain text", q: "punishment for murder under section 103 BNS" },
  { kind: "Boolean", q: "murder AND intention" },
  { kind: "Phrase", q: '"common intention"' },
  { kind: "Proximity", q: "murder /10 intention" },
];

const state = { built: false, overview: null, q: SAMPLES[2].q, slide: 0, cache: new Map(), seq: 0, motion: null };

// ----------------------------------------------------------------------------------------------------------------- the owner's list
// state: live = there is an interactive panel for it on this page; shown = explained with numbers from the index;
//        missing = listed by the owner but not in the pushed code (checked in m1_index/searcher.py and scoring.py).
const STAGES = [
  {
    key: "corpus", name: "Corpus", target: "#ix-corpus",
    blurb: "Judgments from the official dataset, read into one file with their metadata and zones.",
    stat: (o) => ({ v: num(o.docs), k: "judgments in the index" }),
    items: [
      { name: "Official data", state: "shown", note: "The Indian Supreme Court Judgments dataset on AWS Open Data, licence CC-BY-4.0." },
      { name: "Judgments", state: "shown", note: (o) => `${num(o.docs)} judgments, all decided in ${Object.keys(o.years).join(", ")}. A larger and older corpus is what the evaluation still needs.` },
      { name: "Extraction", state: "shown", note: "Text, title, date and judges are read from each judgment into judgments.jsonl." },
      { name: "Metadata", state: "shown", note: (o) => `Year and bench size are kept for filters. Bench size is known for ${num(o.docs - (o.bench.unknown || 0))} of ${num(o.docs)}; the rest are stored as unknown, never as zero.` },
      { name: "Zones", state: "shown", note: "Each judgment is split into headnote, facts, arguments and holding; the zones are indexed and weighted separately." },
    ],
  },
  {
    key: "text", name: "Text processing", target: "#ix-text",
    blurb: "Legal text is normalised, filtered and stemmed, but sections and citations are protected.",
    stat: (o) => ({ v: num(o.stopwords), k: "stop words removed" }),
    items: [
      { name: "Tokenization and normalization", state: "live", note: "Case folding and a citation-aware split: [2025] 1 S.C.R. 1 becomes 2025 1 scr 1." },
      { name: "Stopwords", state: "live", note: (o) => `The NLTK English list of ${num(o.stopwords)} words is removed.` },
      { name: "Stemming", state: "live", note: "Porter stemming: murdered and murders both index as murder." },
      { name: "Legal and citation preservation", state: "live", note: "Numbers, section forms and abbreviations such as IPC, BNS, CrPC, BNSS and INSC are kept as written." },
    ],
  },
  {
    key: "index", name: "Indexing", target: "#ix-index",
    blurb: "For every term, the judgments that contain it, the positions, and the zone each occurrence is in.",
    stat: (o) => ({ v: num(o.terms), k: "distinct terms" }),
    items: [
      { name: "Inverted index", state: "live", note: "term to postings: a document list for every term, so a query never reads the whole corpus." },
      { name: "Positional index", state: "live", note: "Every occurrence keeps its position, which is what lets phrase and proximity queries be answered. Positions are numbered from 0 inside each zone." },
      { name: "Zone index", state: "live", note: "Each posting also counts the term per zone, so a headnote hit can weigh more than a hit in the arguments." },
    ],
  },
  {
    key: "query", name: "Querying", target: "#ix-query",
    blurb: "A small grammar turns a typed query into a tree that the index can answer.",
    stat: () => ({ v: "3", k: "query forms parsed" }),
    items: [
      { name: "Boolean parser", state: "live", note: "AND, OR, NOT and brackets. NOT binds tighter than AND, AND tighter than OR." },
      { name: "Phrase parser", state: "live", note: 'A quoted phrase such as "common intention" must appear as consecutive terms.' },
      { name: "Proximity parser", state: "live", note: "a /10 b means within 10 tokens; /s and /p are accepted and are treated as within 5 tokens in the pushed code." },
    ],
  },
  {
    key: "retrieve", name: "Retrieval", target: "#ix-retrieve",
    blurb: "The tree is run against the index and the matches are scored with zone-weighted BM25.",
    stat: () => ({ v: "BM25", k: "zone-weighted ranking" }),
    items: [
      { name: "Execute Boolean queries against index", state: "live", note: "Set operations over the postings of each term." },
      { name: "Execute phrase queries", state: "live", note: "Consecutive positions are checked inside the candidate documents." },
      { name: "Execute proximity queries", state: "live", note: "Positions of the two sides are compared inside the candidate documents." },
      { name: "Query optimization", state: "missing", note: "Not in the pushed code: operands are evaluated in the order they are written, not smallest posting list first (checked in m1_index/searcher.py)." },
      { name: "BM25", state: "live", note: (o) => `Computed per zone with k1 = ${o.bm25.k1} and b = ${o.bm25.b}, then weighted by zone. One calculation is worked out below.` },
      { name: "lnc.ltc", state: "cap:lnc_ltc", note: "The scoring module still holds only the stub for lnc.ltc cosine scoring; the ranking uses BM25." },
      { name: "Heap Top-K", state: "shown", note: "heapq.nlargest picks the k best of the scored candidates without sorting all of them." },
      { name: "Final search() API", state: "live", note: "search(query, k, filters) returns a list of Hit objects: doc id, relevance and the score of each zone." },
      { name: "Benchmark", state: "live", note: "Latency is measured on this machine when you ask. A comparison against a library BM25 does not exist yet (the library is not installed)." },
    ],
  },
];

// ----------------------------------------------------------------------------------------------------------------- small builders
function tile(key, value, detail) {
  const v = h("div", { class: "v" });
  if (typeof value === "number") v.textContent = num(value); else v.textContent = value;
  return h("div", { class: "ix-tile" }, h("div", { class: "k" }, key), v, detail ? h("div", { class: "d" }, detail) : null);
}

function stateOf(item, overview) {
  if (item.state.startsWith("cap:")) {
    const cap = overview.capabilities[item.state.slice(4)];
    return cap === "implemented" ? "shown" : "missing";
  }
  return item.state;
}

function itemNote(item, overview) {
  return typeof item.note === "function" ? item.note(overview) : item.note;
}

const STATE_LABEL = { live: "live on this page", shown: "explained with real numbers", missing: "not in the pushed code" };

function itemList(stage, overview) {
  return h("ul", { class: "ix-itemlist" }, stage.items.map((item) => {
    const st = stateOf(item, overview);
    return h("li", { class: `ix-item s-${st}` },
      h("span", { class: "ix-item-name" }, h("i", { class: "ix-dot", "aria-hidden": "true" }), item.name, h("span", { class: "sr-only" }, ` (${STATE_LABEL[st]})`)),
      h("span", { class: "ix-item-note" }, itemNote(item, overview)));
  }));
}

function errorBox(err) {
  const box = $("#ix-error");
  clear(box);
  box.append(h("p", { class: "ix-error-title" }, "The Index page cannot read M1's index."), h("p", {}, err.message));
  if (err.kind === "index_missing") box.append(h("pre", { class: "ix-cmd" }, "python -m m1_index.index build"));
  show(box, true);
}

// ----------------------------------------------------------------------------------------------------------------- the stage accordion
function buildAccordion(overview) {
  const acc = $("#ix-acc");
  clear(acc);
  const slices = STAGES.map((stage, i) => {
    const s = stage.stat(overview);
    const body = h("div", { class: "ix-slice-body", id: `ix-body-${stage.key}` },
      h("p", { class: "ix-slice-blurb" }, stage.blurb),
      h("div", { class: "ix-slice-stat" }, h("span", { class: "v" }, s.v), h("span", { class: "k" }, s.k)),
      h("ul", { class: "ix-chiplist" }, stage.items.map((it) => h("li", { class: `ix-chip s-${stateOf(it, overview)}` }, h("i", { class: "ix-dot", "aria-hidden": "true" }), it.name))),
      h("a", { class: "ix-slice-link", href: stage.target, dataset: { ixJump: stage.target } }, "Open this stage"));
    const btn = h("button", { class: "ix-slice-tab", type: "button", "aria-expanded": "false", "aria-controls": `ix-body-${stage.key}`, dataset: { i } },
      h("span", { class: "ix-slice-name" }, stage.name), h("span", { class: "ix-slice-count", "aria-hidden": "true" }));
    return h("div", { class: "ix-slice", role: "listitem", dataset: { stage: stage.key } }, btn, body);
  });
  acc.append(...slices);

  let open = -1;
  const set = (i) => {
    if (i === open) return;
    open = i;
    slices.forEach((el, j) => {
      el.classList.toggle("is-open", j === i);
      $(".ix-slice-tab", el).setAttribute("aria-expanded", String(j === i));
    });
  };
  let intent = 0;
  slices.forEach((el, i) => {
    const tab = $(".ix-slice-tab", el);
    tab.addEventListener("click", () => set(i));
    tab.addEventListener("focus", () => set(i));
    el.addEventListener("pointerenter", () => { window.clearTimeout(intent); intent = window.setTimeout(() => set(i), 90); });
    tab.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); $$(".ix-slice-tab", acc)[(i + 1) % slices.length].focus(); }
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); $$(".ix-slice-tab", acc)[(i + slices.length - 1) % slices.length].focus(); }
    });
  });
  acc.addEventListener("pointerleave", () => window.clearTimeout(intent));
  set(0);
}

// ----------------------------------------------------------------------------------------------------------------- the corpus
function fillCorpus(o) {
  const tiles = $("#ix-corpus-tiles");
  clear(tiles);
  const years = Object.keys(o.years);
  const known = o.docs - (o.bench.unknown || 0);
  tiles.append(
    tile("Judgments", o.docs, "indexed"),
    tile("Years covered", years.length === 1 ? years[0] : `${years[0]} to ${years[years.length - 1]}`, years.length === 1 ? "one year only" : "decision years"),
    tile("Bench size known", `${num(known)} of ${num(o.docs)}`, o.bench.unknown ? `${num(o.bench.unknown)} stored as unknown` : "all recorded"),
    tile("Tokens", o.tokens, "after text processing"));

  const total = Math.max(1, ZONES.reduce((a, z) => a + (o.zone_tokens[z] || 0), 0));
  const bar = $("#ix-zonebar");
  clear(bar);
  const legend = $("#ix-zone-legend");
  clear(legend);
  ZONES.forEach((z) => {
    const share = (o.zone_tokens[z] || 0) / total;
    bar.append(h("div", { class: `ix-zone z-${z}`, vars: { "--w": `${(share * 100).toFixed(2)}%` }, title: `${ZONE_NAME[z]}: ${num(o.zone_tokens[z])} tokens` }));
    legend.append(h("li", {}, h("i", { class: `z-${z}`, "aria-hidden": "true" }), `${ZONE_NAME[z]} ${(share * 100).toFixed(0)}% `, h("span", { class: "dim" }, `(${num(o.zone_tokens[z])} tokens, weight ${o.zone_weights[z]})`)));
  });

  const body = $("#ix-sample tbody");
  clear(body);
  o.sample.forEach((r) => body.append(h("tr", {}, h("td", {}, r.title || "(untitled)"), h("td", {}, r.date || ""), h("td", {}, r.bench_size == null ? "unknown" : String(r.bench_size)), h("td", { class: "mono" }, r.doc_id))));
}

// ----------------------------------------------------------------------------------------------------------------- text processing
async function runText() {
  const out = $("#ix-tokens");
  const text = $("#ix-text-in").value;
  try {
    const a = await api.m1Analyze(text);
    clear(out);
    a.steps.forEach((s, i) => {
      const cls = s.fate === "kept" ? "k-kept" : s.fate === "stopword" ? "k-stop" : s.fate === "stemmed" ? "k-stem" : "k-kept";
      const tok = h("span", { class: `ix-tok ${cls}`, title: s.why, vars: { "--i": String(Math.min(i, 40)) } },
        h("span", { class: "raw" }, s.raw),
        s.fate === "stemmed" ? h("span", { class: "out" }, s.out) : null);
      out.append(tok);
    });
    $("#ix-text-note").textContent = (a.consistent
      ? `This walk-through gives exactly the same ${a.tokens.length} index terms as M1's tokenize(): ${a.tokens.join(" ")}.`
      : "Warning: this walk-through differs from M1's tokenize() for this text, so trust tokenize().")
      + (a.normalised !== a.input ? ` Citations were normalised first: ${a.normalised.replace(/\s+/g, " ").slice(0, 120)}` : "");
    if (motionOn() && gsap) gsap.fromTo($$(".ix-tok", out), { y: 10, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, stagger: 0.018, ease: "power3.out", clearProps: "transform,opacity" });
  } catch (err) {
    clear(out);
    $("#ix-text-note").textContent = err.message;
  }
}

// ----------------------------------------------------------------------------------------------------------------- the index
function fillIndex(o) {
  const tiles = $("#ix-index-tiles");
  clear(tiles);
  tiles.append(
    tile("Distinct terms", o.terms, "keys of the inverted index"),
    tile("Postings", o.postings, "term and document pairs"),
    tile("Positions", o.positions, "one per token occurrence"),
    tile("Index file", o.index_bytes == null ? "n/a" : formatBytes(o.index_bytes), o.load_ms == null ? "compressed on disk" : `loaded in ${num(o.load_ms)} ms`));
  const chips = $("#ix-topterms");
  clear(chips);
  chips.append(h("span", { class: "ix-chips-label" }, "Most common:"));
  o.top_terms.forEach((t) => chips.append(h("button", { class: "chip-btn", type: "button", title: `in ${t.df} judgments`, onclick: () => { $("#ix-term-in").value = t.term; runTerm(); } }, t.term)));
}

async function runTerm() {
  const out = $("#ix-term-out");
  try {
    const t = await api.m1Term($("#ix-term-in").value);
    clear(out);
    const maxTf = Math.max(1, ...t.postings.map((p) => p.tf));
    out.append(
      h("p", { class: "ix-term-line" }, `"${t.word}" is looked up as the index term `, h("b", { class: "mono" }, t.term), `. It occurs in ${num(t.df)} of ${num(t.docs)} judgments, so its idf is ${t.idf}.`),
      t.df === 0 ? h("p", { class: "ix-note" }, "No judgment contains this term.") : h("div", { class: "ix-scroll" }, h("table", { class: "ix-table ix-postings" },
        h("thead", {}, h("tr", {}, h("th", {}, "Judgment"), h("th", {}, "Count"), h("th", {}, "By zone"), h("th", {}, "Positions"))),
        h("tbody", {}, t.postings.map((p) => h("tr", {},
          h("td", {}, h("div", {}, p.title || "(untitled)"), h("div", { class: "mono dim" }, p.doc_id)),
          h("td", {}, h("div", { class: "ix-tfbar", vars: { "--w": `${(p.tf / maxTf) * 100}%` } }, h("span", {}, String(p.tf)))),
          h("td", {}, h("div", { class: "ix-zonechips" }, ZONES.filter((z) => p.zones[z]).map((z) => h("span", { class: `ix-zc z-${z}` }, `${ZONE_NAME[z]} ${p.zones[z]}`)))),
          h("td", { class: "mono" }, p.positions.join(", ") + (p.n_positions > p.positions.length ? ` ... (${p.n_positions})` : ""))))))),
      t.df > t.postings.length ? h("p", { class: "ix-note" }, `Showing the ${t.postings.length} judgments where it occurs most often.`) : null);
  } catch (err) {
    clear(out);
    out.append(h("p", { class: "ix-note" }, err.message));
  }
}

// ----------------------------------------------------------------------------------------------------------------- query trees
function treeNode(n) {
  if (n.type === "term") return h("span", { class: "t-leaf t-term" }, n.term);
  if (n.type === "phrase") return h("span", { class: "t-leaf t-phrase" }, `“${n.terms.join(" ")}”`);
  if (n.type === "not") return h("div", { class: "t-node t-not" }, h("span", { class: "t-op" }, "NOT"), h("div", { class: "t-kids" }, treeNode(n.child)));
  const label = n.type === "proximity" ? `within ${n.op.slice(1).match(/^\d+$/) ? n.op.slice(1) + " tokens" : n.op === "/s" ? "a sentence (5 tokens)" : "a paragraph (5 tokens)"}` : n.type.toUpperCase();
  return h("div", { class: `t-node t-${n.type}` }, h("span", { class: "t-op" }, label), h("div", { class: "t-kids" }, treeNode(n.left), treeNode(n.right)));
}

function renderTree(into, q) {
  clear(into);
  if (q.tree) {
    into.append(h("p", { class: "ix-tree-title" }, "Parsed as a Boolean tree"), h("div", { class: "t-root" }, treeNode(q.tree)));
  } else {
    into.append(h("p", { class: "ix-tree-title" }, "Plain text: any word counts"), h("div", { class: "t-root" }, h("div", { class: "t-node t-or" }, h("span", { class: "t-op" }, "OR of the words"),
      h("div", { class: "t-kids" }, q.terms.map((t) => h("span", { class: "t-leaf t-term" }, t))))));
  }
}

async function loadQuery(query, k = 5) {
  const key = `${k}|${query}`;
  if (state.cache.has(key)) return state.cache.get(key);
  const data = await api.m1Query(query, k);
  state.cache.set(key, data);
  return data;
}

// ----------------------------------------------------------------------------------------------------------------- the carousel
function zoneBar(zones, rel) {
  const total = Math.max(rel, 1e-9);
  return h("div", { class: "ix-zonebar ix-zonebar-mini", "aria-hidden": "true" }, ZONES.map((z) => h("div", { class: `ix-zone z-${z}`, vars: { "--w": `${Math.max(0, (zones[z].part / total) * 100).toFixed(2)}%` } })));
}

function plateFor(hit, i) {
  return h("div", { class: "ix-hitplate", vars: { "--n": String(i) } },
    h("div", { class: "top" }, h("p", { class: "t" }, hit.title || "(untitled)"), h("b", { class: "sc" }, hit.rel.toFixed(2))),
    h("p", { class: "d" }, `${hit.date || ""}${hit.bench_size ? `  ·  bench of ${hit.bench_size}` : ""}`),
    zoneBar(hit.zones, hit.rel));
}

async function showSlide(i, { animate = true } = {}) {
  const n = SAMPLES.length;
  state.slide = (i + n) % n;
  const sample = SAMPLES[state.slide];
  $$("#ix-car-dots button").forEach((b, j) => { b.setAttribute("aria-selected", String(j === state.slide)); b.classList.toggle("is-on", j === state.slide); });
  const stage = $("#ix-car-stage");
  const mine = ++state.seq;
  let data;
  try { data = await loadQuery(sample.q, 3); } catch (err) { toast(err.message, "error", 4000); return; }
  if (mine !== state.seq) return;
  const apply = () => {
    $("#ix-car-kind").textContent = sample.kind;
    $("#ix-quote").textContent = sample.q;
    renderTree($("#ix-car-tree"), data);
    const plates = $("#ix-car-plates");
    clear(plates);
    data.hits.slice(0, 3).forEach((hit, j) => plates.append(plateFor(hit, j)));
    if (!data.hits.length) plates.append(h("p", { class: "ix-note" }, "No judgment matches."));
  };
  if (animate && motionOn() && gsap) {
    await gsap.to(stage, { opacity: 0, y: 10, duration: 0.18, ease: "power2.in" });
    if (mine !== state.seq) { gsap.set(stage, { clearProps: "opacity,transform" }); return; }
    apply();
    gsap.fromTo(stage, { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: 0.45, ease: "power3.out", clearProps: "opacity,transform" });
    gsap.from($$(".ix-hitplate", stage), { x: 40, opacity: 0, duration: 0.6, stagger: 0.08, ease: "power3.out", clearProps: "transform,opacity" });
  } else {
    apply();
  }
  setCurrent(sample.q, { fromSlide: true });
}

function buildCarousel() {
  const dots = $("#ix-car-dots");
  clear(dots);
  SAMPLES.forEach((s, i) => dots.append(h("button", { type: "button", role: "tab", "aria-label": `${s.kind}: ${s.q}`, "aria-selected": "false", onclick: () => showSlide(i) }, h("span", { class: "sr-only" }, s.kind))));
  $("#ix-car-prev").addEventListener("click", () => showSlide(state.slide - 1));
  $("#ix-car-next").addEventListener("click", () => showSlide(state.slide + 1));
  const stage = $("#ix-car");
  stage.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea")) return;
    if (e.key === "ArrowLeft") showSlide(state.slide - 1);
    if (e.key === "ArrowRight") showSlide(state.slide + 1);
  });
  let startX = null;
  stage.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse" || e.button === 0) startX = e.clientX; });
  stage.addEventListener("pointerup", (e) => {
    if (startX == null) return;
    const dx = e.clientX - startX;
    startX = null;
    if (Math.abs(dx) > 60) showSlide(state.slide + (dx < 0 ? 1 : -1));
  });
}

// ----------------------------------------------------------------------------------------------------------------- the custom query and the retrieval panel
async function runCustom() {
  const q = $("#ix-q-in").value.trim();
  if (!q) { toast("Type a query first.", "error", 2500); return; }
  $$("#ix-car-dots button").forEach((b) => { b.setAttribute("aria-selected", "false"); b.classList.remove("is-on"); });
  await setCurrent(q, { fromSlide: false });
  scrollToTarget("#ix-retrieve", { offset: 90 });
}

async function setCurrent(query, { fromSlide }) {
  state.q = query;
  if (fromSlide) $("#ix-q-in").value = query;
  $("#ix-open-search").setAttribute("href", `#/?q=${encodeURIComponent(query)}`);
  clear($("#ix-verify-out"));
  try {
    const q = await loadQuery(query, 5);
    if (state.q !== query) return;
    renderTree($("#ix-tree"), q);
    renderRetrieval(q);
  } catch (err) {
    $("#ix-hits").replaceChildren(h("p", { class: "ix-note" }, err.message));
  }
}

function renderRetrieval(q) {
  const tiles = $("#ix-ret-tiles");
  clear(tiles);
  tiles.append(
    tile("Query", q.query, q.mode === "boolean" ? "Boolean tree" : "plain words"),
    tile("Candidates", q.candidates, `of ${num(q.docs)} judgments`),
    tile("Time", `${q.ms} ms`, "one search() call, k = " + q.k));
  const hits = $("#ix-hits");
  clear(hits);
  if (!q.hits.length) { hits.append(h("p", { class: "ix-note" }, "No judgment matches this query.")); }
  q.hits.forEach((hit, i) => hits.append(h("div", { class: "ix-hit" },
    h("span", { class: "rk" }, String(i + 1)),
    h("div", { class: "who" }, h("div", { class: "t" }, hit.title || "(untitled)"), h("div", { class: "mono dim" }, hit.doc_id)),
    h("div", { class: "bars" }, zoneBar(hit.zones, hit.rel), h("div", { class: "ix-zonetext" }, ZONES.filter((z) => hit.zones[z].part > 0).map((z) => `${ZONE_NAME[z]} ${hit.zones[z].part.toFixed(2)}`).join("  ·  "))),
    h("div", { class: "rel" }, hit.rel.toFixed(2)))));
  const legend = h("ul", { class: "ix-legend" }, ZONES.map((z) => h("li", {}, h("i", { class: `z-${z}`, "aria-hidden": "true" }), `${ZONE_NAME[z]} (weight ${state.overview.zone_weights[z]})`)));
  hits.append(legend);

  const w = q.worked;
  const worked = $("#ix-worked");
  clear(worked);
  worked.append(h("h3", {}, "One BM25 calculation"));
  if (!w) {
    worked.append(h("p", { class: "ix-sub" }, "Nothing to work out: the query has no scored result."));
  } else {
    const norm = 1 - w.b + (w.b * w.dl) / w.avgdl;
    const tfpart = (w.tf * (w.k1 + 1)) / (w.tf + w.k1 * norm);
    worked.append(
      h("p", { class: "ix-sub" }, `Top result, term ${w.term}, ${ZONE_NAME[w.zone]} zone.`),
      h("pre", { class: "ix-formula" }, "bm25 = idf x tf (k1 + 1) / ( tf + k1 (1 - b + b dl / avgdl) )"),
      h("dl", { class: "ix-vars" },
        ...[["idf", w.idf], ["tf", w.tf], ["dl", w.dl], ["avgdl", w.avgdl], ["k1", w.k1], ["b", w.b]].flatMap(([k, v]) => [h("dt", {}, k), h("dd", { class: "mono" }, String(v))])),
      h("pre", { class: "ix-formula" }, `= ${w.idf} x ${w.tf} x ${(w.k1 + 1).toFixed(1)} / ( ${w.tf} + ${w.k1} x ${norm.toFixed(3)} )\n= ${w.bm25}\nx zone weight ${w.weight} = ${(w.bm25 * w.weight).toFixed(4)} added to this result's relevance`),
      h("p", { class: "ix-note" }, `Recomputed here from the displayed numbers: ${(w.idf * tfpart).toFixed(4)}. M1's code returned ${w.bm25}${Math.abs(w.idf * tfpart - w.bm25) < 0.005 ? ", the same within the rounding of the displayed inputs" : ", which differs: trust M1's value"}.`));
  }

  const api_ = $("#ix-api");
  clear(api_);
  api_.append(h("h3", {}, "What search() returns"),
    h("pre", { class: "ix-formula" }, "search(query: str, k: int = 100, filters: dict | None = None) -> list[Hit]"));
  if (q.hits[0]) {
    const top = q.hits[0];
    const zs = Object.fromEntries(ZONES.map((z) => [z, top.zones[z].score]));
    api_.append(h("p", { class: "ix-sub" }, "The first Hit of this query:"), h("pre", { class: "ix-formula" }, JSON.stringify({ doc_id: top.doc_id, rel: top.rel, zone_scores: zs }, null, 2)));
  }
}

async function runVerify() {
  const out = $("#ix-verify-out");
  const btn = $("#ix-verify");
  btn.disabled = true;
  clear(out);
  out.append(h("p", { class: "ix-note" }, "Reading every token of every zone, without the index. The first check takes a few seconds."));
  try {
    const v = await api.m1Verify(state.q);
    clear(out);
    if (!v.checked) out.append(h("p", { class: "ix-note" }, `Not checked: ${v.reason}.`));
    else if (v.agree) out.append(h("p", { class: "ix-verdict is-ok" }, `The index and a plain scan of all the text agree: both find the same ${num(v.engine)} judgments.`));
    else out.append(h("p", { class: "ix-verdict is-bad" }, `They disagree: the index finds ${num(v.engine)}, the scan finds ${num(v.scan)}. Only in the index: ${v.only_engine.join(", ") || "none"}. Only in the scan: ${v.only_scan.join(", ") || "none"}.`));
  } catch (err) {
    clear(out);
    out.append(h("p", { class: "ix-note" }, err.message));
  } finally {
    btn.disabled = false;
  }
}

async function runBench() {
  const out = $("#ix-bench-out");
  const btn = $("#ix-bench");
  btn.disabled = true;
  clear(out);
  out.append(h("p", { class: "ix-note" }, "Running each query repeatedly..."));
  try {
    const b = await api.m1Bench();
    clear(out);
    out.append(h("div", { class: "ix-scroll" }, h("table", { class: "ix-table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Kind"), h("th", {}, "Query"), h("th", {}, "Results"), h("th", {}, "Median"), h("th", {}, "95th percentile"))),
      h("tbody", {}, b.rows.map((r) => h("tr", {}, h("td", {}, r.label), h("td", { class: "mono" }, r.query), h("td", {}, String(r.hits)), h("td", {}, `${r.median_ms} ms`), h("td", {}, `${r.p95_ms} ms`)))))),
      h("p", { class: "ix-note" }, `Each query ran ${b.runs} times for the 100 best results, on this machine, just now. Loading the index took ${num(b.load_ms)} ms once. These are latencies, not a quality comparison.`));
  } catch (err) {
    clear(out);
    out.append(h("p", { class: "ix-note" }, err.message));
  } finally {
    btn.disabled = false;
  }
}

// ----------------------------------------------------------------------------------------------------------------- motion
function initMotion() {
  if (!gsap || !ScrollTrigger || !motionOn()) return;
  if (state.motion) state.motion.revert();
  state.motion = gsap.matchMedia();
  state.motion.add("(prefers-reduced-motion: no-preference)", () => {
    // images and panels grow into place as they arrive and ease back as they leave; opacity only, never a darkening filter
    gsap.utils.toArray(".ix-plate").forEach((plate) => {
      gsap.fromTo(plate, { scale: 0.93, opacity: 0.5 }, { scale: 1, opacity: 1, ease: "none", transformOrigin: "50% 0%",
        scrollTrigger: { trigger: plate, start: "top 96%", end: "top 55%", scrub: 0.8 } });
      gsap.to(plate, { opacity: 0.6, scale: 0.985, ease: "none", transformOrigin: "50% 100%", immediateRender: false,
        scrollTrigger: { trigger: plate, start: "bottom 38%", end: "bottom 4%", scrub: 0.8 } });
    });
    gsap.utils.toArray(".ix-art-plate").forEach((p, i) => {
      gsap.to(p, { yPercent: i % 2 ? -14 : 12, ease: "none", scrollTrigger: { trigger: ".ix-hero", start: "top top", end: "bottom top", scrub: 1.1 } });
    });
  });
  requestFrame();
}

// ----------------------------------------------------------------------------------------------------------------- entry
function wireJumps() {
  $$("[data-ix-jump]").forEach((a) => {
    if (a.dataset.wired) return;
    a.dataset.wired = "1";
    a.addEventListener("click", (e) => { e.preventDefault(); scrollToTarget(a.dataset.ixJump, { offset: 90 }); });
  });
}

export async function renderIndexPage() {
  if (state.built) { requestFrame(); return; }
  show($("#ix-error"), false);
  let o;
  try {
    o = await api.m1Overview();
  } catch (err) {
    errorBox(err);
    return;
  }
  state.overview = o;
  state.built = true;
  buildAccordion(o);
  fillCorpus(o);
  fillIndex(o);
  Object.entries({ corpus: "#ix-items-corpus", text: "#ix-items-text", index: "#ix-items-index", query: "#ix-items-query", retrieve: "#ix-items-retrieve" }).forEach(([key, sel]) => {
    const stage = STAGES.find((s) => s.key === key);
    const box = $(sel);
    clear(box);
    box.append(h("h3", {}, "What the list covers"), itemList(stage, o));
  });
  buildCarousel();
  $("#ix-text-form").addEventListener("submit", (e) => { e.preventDefault(); runText(); });
  $("#ix-term-form").addEventListener("submit", (e) => { e.preventDefault(); runTerm(); });
  $("#ix-q-form").addEventListener("submit", (e) => { e.preventDefault(); runCustom(); });
  $("#ix-verify").addEventListener("click", runVerify);
  $("#ix-bench").addEventListener("click", runBench);
  wireJumps();
  initMotion();
  await Promise.all([runText(), runTerm(), showSlide(2, { animate: false })]);
  requestFrame();
}
