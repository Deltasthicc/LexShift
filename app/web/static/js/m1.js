// The Index page (M1): the pipeline from text to ranked list, one tab per stage, run against the real index on disk.
//
// Every number and row comes from /api/m1/*, which reads M1's index and calls M1's own functions; nothing is a stored example. A piece of
// the owner's list that the pushed code does not contain is marked "not in the pushed code", not described as if it worked. All text from
// the index is inserted as text, never as markup.

import { $, $$, h, clear, show, formatBytes } from "./dom.js";
import { api } from "./api.js";
import { animateIn } from "./motion.js";
import { toast } from "./ui.js";

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

const state = { built: false, overview: null, q: SAMPLES[2].q, tab: "corpus", cache: new Map() };

// ----------------------------------------------------------------------------------------------------------------- the owner's list
// state: live = there is an interactive panel for it on this page; shown = explained with numbers from the index;
//        missing = listed by the owner but not in the pushed code (checked in m1_index/searcher.py and scoring.py).
const STAGES = [
  {
    key: "corpus", name: "Corpus", panel: "#ix-corpus",
    blurb: "Judgments from the official dataset, read into one file with their metadata and four zones.",
    items: [
      { name: "Official data", state: "shown", note: "The Indian Supreme Court Judgments dataset on AWS Open Data, licence CC-BY-4.0." },
      { name: "Judgments", state: "shown", note: (o) => `${num(o.docs)} judgments, decided in ${Object.keys(o.years).join(", ")}.` },
      { name: "Extraction", state: "shown", note: "Text, title, date and judges are read from each judgment into judgments.jsonl." },
      { name: "Metadata", state: "shown", note: (o) => `Year and bench size are kept for filters. Bench size is known for ${num(o.docs - (o.bench.unknown || 0))} of ${num(o.docs)}; the rest are stored as unknown, never as zero.` },
      { name: "Zones", state: "shown", note: "Each judgment is split into headnote, facts, arguments and holding; the zones are indexed and weighted separately." },
    ],
  },
  {
    key: "text", name: "Text processing", panel: "#ix-text",
    blurb: "Legal text is normalised, filtered and stemmed, but sections and citations are protected.",
    items: [
      { name: "Tokenization and normalization", state: "live", note: "Case folding and a citation-aware split: [2025] 1 S.C.R. 1 becomes 2025 1 scr 1." },
      { name: "Stopwords", state: "live", note: (o) => `The NLTK English list of ${num(o.stopwords)} words is removed.` },
      { name: "Stemming", state: "live", note: "Porter stemming: murdered and murders both index as murder." },
      { name: "Legal and citation preservation", state: "live", note: "Numbers, section forms and abbreviations such as IPC, BNS, CrPC, BNSS and INSC are kept as written." },
    ],
  },
  {
    key: "index", name: "Postings", panel: "#ix-index",
    blurb: "For every term: the judgments that contain it, the positions, and the zone of each occurrence.",
    items: [
      { name: "Inverted index", state: "live", note: "term to postings: a document list for every term, so a query never reads the whole corpus." },
      { name: "Positional index", state: "live", note: "Every occurrence keeps its position, which is what lets phrase and proximity queries be answered." },
      { name: "Zone index", state: "live", note: "Each posting also counts the term per zone, so a headnote hit can weigh more than a hit in the arguments." },
    ],
  },
  {
    key: "query", name: "Query", panel: "#ix-query",
    blurb: "A small grammar turns the typed query into a tree that the index answers.",
    items: [
      { name: "Boolean parser", state: "live", note: "AND, OR, NOT and brackets. NOT binds tighter than AND, AND tighter than OR." },
      { name: "Phrase parser", state: "live", note: 'A quoted phrase such as "common intention" must appear as consecutive terms.' },
      { name: "Proximity parser", state: "live", note: "a /10 b means within 10 tokens; /s and /p are accepted and are treated as within 5 tokens in the pushed code." },
      { name: "Execute Boolean queries against index", state: "live", note: "Set operations over the postings of each term." },
      { name: "Execute phrase queries", state: "live", note: "Consecutive positions are checked inside the candidate documents." },
      { name: "Execute proximity queries", state: "live", note: "Positions of the two sides are compared inside the candidate documents." },
      { name: "Query optimization", state: "missing", note: "Not in the pushed code: operands are evaluated in the order they are written, not smallest posting list first (checked in m1_index/searcher.py)." },
    ],
  },
  {
    key: "retrieve", name: "BM25", panel: "#ix-retrieve",
    blurb: "Matches are scored with zone-weighted BM25 and the best k are kept with a heap.",
    items: [
      { name: "BM25", state: "live", note: (o) => `Computed per zone with k1 = ${o.bm25.k1} and b = ${o.bm25.b}, then weighted by zone.` },
      { name: "lnc.ltc", state: "cap:lnc_ltc", note: "The scoring module still holds only the stub for lnc.ltc cosine scoring; the ranking uses BM25." },
      { name: "Heap Top-K", state: "shown", note: "heapq.nlargest picks the k best of the scored candidates without sorting all of them." },
      { name: "Final search() API", state: "live", note: "search(query, k, filters) returns a list of Hit objects: doc id, relevance and the score of each zone." },
      { name: "Benchmark", state: "live", note: "Latency is measured on this machine when you ask. A comparison against a library BM25 does not exist yet." },
    ],
  },
];

// ----------------------------------------------------------------------------------------------------------------- small builders
function tile(key, value, detail) {
  return h("div", { class: "tile" }, h("span", { class: "k" }, key), h("span", { class: "v" }, typeof value === "number" ? num(value) : value), detail ? h("span", { class: "d" }, detail) : null);
}

function stateOf(item, overview) {
  if (item.state.startsWith("cap:")) return overview.capabilities[item.state.slice(4)] === "implemented" ? "shown" : "missing";
  return item.state;
}

const STATE_LABEL = { live: "live on this page", shown: "explained with real numbers", missing: "not in the pushed code" };

function fillChecklist(stage, overview) {
  const box = $(`${stage.panel} .checklist`);
  clear(box);
  stage.items.forEach((item) => {
    const st = stateOf(item, overview);
    const note = typeof item.note === "function" ? item.note(overview) : item.note;
    box.appendChild(h("span", { class: `check s-${st}`, tabindex: "0", dataset: { tip: `${STATE_LABEL[st]}. ${note}` } }, h("i", { "aria-hidden": "true" }), item.name, st === "missing" ? " (not built)" : null));
  });
}

function zoneBar(zones, rel, mini = true) {
  const total = Math.max(rel, 1e-9);
  return h("div", { class: `zonebar${mini ? " zonebar-mini" : ""}`, "aria-hidden": "true" }, ZONES.map((z) => h("div", { class: `zone z-${z}`, vars: { "--w": `${Math.max(0, (zones[z].part / total) * 100).toFixed(2)}%` } })));
}

// ----------------------------------------------------------------------------------------------------------------- tabs
function buildTabs() {
  const bar = $("#ix-tabs");
  clear(bar);
  STAGES.forEach((stage, i) => {
    const tab = h("button", { class: "tab", type: "button", role: "tab", "aria-selected": "false", "aria-controls": stage.panel.slice(1), dataset: { stage: stage.key } }, h("span", { class: "n" }, String(i + 1)), stage.name);
    tab.addEventListener("click", () => selectTab(stage.key));
    bar.appendChild(tab);
    const panel = $(stage.panel);
    if (!$(".panel-blurb", panel)) panel.prepend(h("p", { class: "note panel-blurb" }, stage.blurb));
  });
  bar.addEventListener("keydown", (e) => {
    const i = STAGES.findIndex((s) => s.key === state.tab);
    if (e.key === "ArrowRight") { e.preventDefault(); selectTab(STAGES[(i + 1) % STAGES.length].key, true); }
    if (e.key === "ArrowLeft") { e.preventDefault(); selectTab(STAGES[(i + STAGES.length - 1) % STAGES.length].key, true); }
  });
}

function selectTab(key, focus = false) {
  state.tab = key;
  $$("#ix-tabs .tab").forEach((t) => {
    const on = t.dataset.stage === key;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    if (on && focus) t.focus();
  });
  STAGES.forEach((s) => show($(s.panel), s.key === key));
  animateIn($(STAGES.find((s) => s.key === key).panel), { y: 6 });
}

// ----------------------------------------------------------------------------------------------------------------- corpus
function fillCorpus(o) {
  const total = Math.max(1, ZONES.reduce((a, z) => a + (o.zone_tokens[z] || 0), 0));
  const bar = $("#ix-zonebar");
  const legend = $("#ix-zone-legend");
  clear(bar);
  clear(legend);
  ZONES.forEach((z) => {
    const share = (o.zone_tokens[z] || 0) / total;
    bar.append(h("div", { class: `zone z-${z}`, vars: { "--w": `${(share * 100).toFixed(2)}%` }, dataset: { tip: `${ZONE_NAME[z]}: ${num(o.zone_tokens[z])} tokens` } }));
    legend.append(h("li", {}, h("i", { class: `z-${z}`, "aria-hidden": "true" }), `${ZONE_NAME[z]} ${(share * 100).toFixed(0)}%, weight ${o.zone_weights[z]}`));
  });
  const body = $("#ix-sample tbody");
  clear(body);
  o.sample.forEach((r) => body.append(h("tr", {}, h("td", {}, r.title || "(untitled)"), h("td", {}, r.date || ""), h("td", {}, r.bench_size == null ? "unknown" : String(r.bench_size)))));
}

// ----------------------------------------------------------------------------------------------------------------- text processing
async function runText() {
  const out = $("#ix-tokens");
  try {
    const a = await api.m1Analyze($("#ix-text-in").value);
    clear(out);
    a.steps.forEach((s) => {
      const cls = s.fate === "stopword" ? "k-stop" : s.fate === "stemmed" ? "k-stem" : "k-kept";
      out.append(h("span", { class: `tok ${cls}`, dataset: { tip: s.why } }, h("span", {}, s.raw), s.fate === "stemmed" ? h("span", { class: "out" }, s.out) : null));
    });
    $("#ix-text-note").textContent = a.consistent
      ? `Index terms, exactly as M1's tokenize() gives them: ${a.tokens.join(" ")}`
      : "Warning: this walk-through differs from M1's tokenize() for this text, so trust tokenize().";
    animateIn(out.children, { y: 4, stagger: 0.012 });
  } catch (err) {
    clear(out);
    $("#ix-text-note").textContent = err.message;
  }
}

// ----------------------------------------------------------------------------------------------------------------- postings
function fillTopTerms(o) {
  const chips = $("#ix-topterms");
  clear(chips);
  o.top_terms.slice(0, 10).forEach((t) => chips.append(h("button", { class: "chip-btn", type: "button", dataset: { tip: `in ${t.df} judgments` }, onclick: () => { $("#ix-term-in").value = t.term; runTerm(); } }, t.term)));
}

async function runTerm() {
  const out = $("#ix-term-out");
  try {
    const t = await api.m1Term($("#ix-term-in").value);
    clear(out);
    out.append(
      h("p", { class: "note" }, [`Index term `, h("b", { class: "mono" }, t.term), `: in ${num(t.df)} of ${num(t.docs)} judgments, idf ${t.idf}.`]),
      t.df === 0 ? null : h("div", { class: "table-wrap" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, "Judgment"), h("th", {}, "tf"), h("th", {}, "By zone"), h("th", {}, "Positions"))),
        h("tbody", {}, t.postings.slice(0, 8).map((p) => h("tr", {},
          h("td", {}, p.title || p.doc_id),
          h("td", { class: "num" }, String(p.tf)),
          h("td", {}, ZONES.filter((z) => p.zones[z]).map((z) => `${ZONE_NAME[z]} ${p.zones[z]}`).join(", ")),
          h("td", { class: "mono" }, p.positions.slice(0, 6).join(", ") + (p.n_positions > Math.min(6, p.positions.length) ? " ..." : ""))))))));
  } catch (err) {
    clear(out);
    out.append(h("p", { class: "note" }, err.message));
  }
}

// ----------------------------------------------------------------------------------------------------------------- query and BM25
function treeNode(n) {
  if (n.type === "term") return h("span", { class: "t-leaf" }, n.term);
  if (n.type === "phrase") return h("span", { class: "t-leaf" }, `“${n.terms.join(" ")}”`);
  if (n.type === "not") return h("div", { class: "t-node" }, h("span", { class: "t-op" }, "NOT"), h("div", { class: "t-kids" }, treeNode(n.child)));
  const label = n.type === "proximity" ? `WITHIN ${/^\/\d+$/.test(n.op) ? `${n.op.slice(1)} TOKENS` : "5 TOKENS"}` : n.type.toUpperCase();
  return h("div", { class: "t-node" }, h("span", { class: "t-op" }, label), h("div", { class: "t-kids" }, treeNode(n.left), treeNode(n.right)));
}

async function loadQuery(query, k = 5) {
  const key = `${k}|${query}`;
  if (!state.cache.has(key)) state.cache.set(key, await api.m1Query(query, k));
  return state.cache.get(key);
}

async function runQuery(query) {
  state.q = query;
  $("#ix-q-in").value = query;
  $$("#ix-samples .chip-btn").forEach((b) => b.classList.toggle("is-on", b.dataset.q === query));
  clear($("#ix-verify-out"));
  let q;
  try { q = await loadQuery(query, 5); } catch (err) { $("#ix-hits").replaceChildren(h("p", { class: "note" }, err.message)); clear($("#ix-tree")); return; }
  if (state.q !== query) return;
  const tree = $("#ix-tree");
  clear(tree);
  tree.append(h("p", { class: "note" }, q.tree ? "Parsed as" : "Plain text: any word counts"),
    q.tree ? treeNode(q.tree) : h("div", { class: "t-node" }, h("span", { class: "t-op" }, "OR"), h("div", { class: "t-kids" }, q.terms.map((t) => h("span", { class: "t-leaf" }, t)))));
  const hits = $("#ix-hits");
  clear(hits);
  hits.append(h("p", { class: "note" }, `${num(q.candidates)} of ${num(q.docs)} judgments match  ·  ${q.ms} ms`));
  if (!q.hits.length) hits.append(h("p", { class: "note" }, "No judgment matches this query."));
  q.hits.forEach((hit, i) => hits.append(h("div", { class: "hit", dataset: { tip: ZONES.filter((z) => hit.zones[z].part > 0).map((z) => `${ZONE_NAME[z]} ${hit.zones[z].part.toFixed(2)}`).join(", ") } },
    h("span", { class: "rk" }, String(i + 1)),
    h("div", {}, h("div", { class: "t" }, hit.title || hit.doc_id), zoneBar(hit.zones, hit.rel)),
    h("span", { class: "rel" }, hit.rel.toFixed(2)))));
  animateIn(hits.children, { y: 6, stagger: 0.03 });
  renderBm25(q);
}

function renderBm25(q) {
  $("#ix-ret-query").textContent = `For the query: ${q.query}`;
  const w = q.worked;
  const worked = $("#ix-worked");
  clear(worked);
  worked.append(h("h3", {}, "One BM25 term, worked out"));
  if (!w) {
    worked.append(h("p", { class: "note" }, "Nothing to work out: the query has no scored result."));
  } else {
    const norm = 1 - w.b + (w.b * w.dl) / w.avgdl;
    worked.append(
      h("p", { class: "note" }, `Top result, term "${w.term}", ${ZONE_NAME[w.zone]} zone.`),
      h("div", { class: "pre" }, `bm25 = idf × tf(k1+1) / (tf + k1(1 − b + b·dl/avgdl))\n     = ${w.idf} × ${w.tf}×${(w.k1 + 1).toFixed(1)} / (${w.tf} + ${w.k1}×${norm.toFixed(3)})\n     = ${w.bm25}\n× zone weight ${w.weight} = ${(w.bm25 * w.weight).toFixed(4)}`),
      h("p", { class: "note" }, `idf ${w.idf}, tf ${w.tf}, dl ${w.dl}, avgdl ${w.avgdl}, k1 ${w.k1}, b ${w.b}`));
  }
  const out = $("#ix-api");
  clear(out);
  out.append(h("h3", {}, "What search() returns"), h("div", { class: "pre" }, "search(query, k=100, filters=None) -> list[Hit]"));
  if (q.hits[0]) {
    const top = q.hits[0];
    out.append(h("div", { class: "pre" }, JSON.stringify({ doc_id: top.doc_id, rel: top.rel, zone_scores: Object.fromEntries(ZONES.map((z) => [z, top.zones[z].score])) }, null, 2)));
  }
}

async function runVerify() {
  const out = $("#ix-verify-out");
  const btn = $("#ix-verify");
  btn.disabled = true;
  out.replaceChildren(h("p", { class: "note" }, "Reading every token of every zone, without the index..."));
  try {
    const v = await api.m1Verify(state.q);
    if (!v.checked) out.replaceChildren(h("p", { class: "note" }, `Not checked: ${v.reason}.`));
    else if (v.agree) out.replaceChildren(h("p", { class: "verdict is-ok" }, `The index and a plain scan agree: both find the same ${num(v.engine)} judgments.`));
    else out.replaceChildren(h("p", { class: "verdict is-bad" }, `They disagree: the index finds ${num(v.engine)}, the scan finds ${num(v.scan)}.`));
  } catch (err) {
    out.replaceChildren(h("p", { class: "note" }, err.message));
  } finally {
    btn.disabled = false;
  }
}

async function runBench() {
  const out = $("#ix-bench-out");
  const btn = $("#ix-bench");
  btn.disabled = true;
  out.replaceChildren(h("p", { class: "note" }, "Running each query repeatedly..."));
  try {
    const b = await api.m1Bench();
    out.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Kind"), h("th", {}, "Query"), h("th", {}, "Results"), h("th", {}, "Median"), h("th", {}, "p95"))),
      h("tbody", {}, b.rows.map((r) => h("tr", {}, h("td", {}, r.label), h("td", { class: "mono" }, r.query), h("td", { class: "num" }, String(r.hits)), h("td", { class: "num" }, `${r.median_ms} ms`), h("td", { class: "num" }, `${r.p95_ms} ms`)))))),
      h("p", { class: "note" }, `${b.runs} runs each, top 100, on this machine just now. Index load: ${num(b.load_ms)} ms.`));
  } catch (err) {
    out.replaceChildren(h("p", { class: "note" }, err.message));
  } finally {
    btn.disabled = false;
  }
}

// ----------------------------------------------------------------------------------------------------------------- entry
export async function renderIndexPage() {
  if (state.built) return;
  show($("#ix-error"), false);
  let o;
  try {
    o = await api.m1Overview();
  } catch (err) {
    const box = $("#ix-error");
    box.replaceChildren(h("strong", {}, "The Index page cannot read M1's index. "), err.message, err.kind === "index_missing" ? h("div", { class: "pre" }, "python -m m1_index.index build") : null);
    show(box, true);
    return;
  }
  state.overview = o;
  state.built = true;
  const tiles = $("#ix-tiles");
  clear(tiles);
  tiles.append(
    tile("Judgments", o.docs, `${Object.keys(o.years).join(", ")}`),
    tile("Distinct terms", o.terms, "inverted index keys"),
    tile("Postings", o.postings, `${num(o.positions)} positions`),
    tile("Index on disk", o.index_bytes == null ? "n/a" : formatBytes(o.index_bytes), o.load_ms == null ? "" : `loads in ${num(o.load_ms)} ms`));
  buildTabs();
  STAGES.forEach((s) => fillChecklist(s, o));
  fillCorpus(o);
  fillTopTerms(o);
  const samples = $("#ix-samples");
  clear(samples);
  SAMPLES.forEach((s) => samples.append(h("button", { class: "chip-btn", type: "button", dataset: { q: s.q }, onclick: () => runQuery(s.q) }, [s.kind, h("small", {}, s.q)])));
  $("#ix-text-form").addEventListener("submit", (e) => { e.preventDefault(); runText(); });
  $("#ix-term-form").addEventListener("submit", (e) => { e.preventDefault(); runTerm(); });
  $("#ix-q-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#ix-q-in").value.trim();
    if (!q) { toast("Type a query first.", "error", 2500); return; }
    runQuery(q);
  });
  $("#ix-verify").addEventListener("click", runVerify);
  $("#ix-bench").addEventListener("click", runBench);
  selectTab("corpus");
  await Promise.all([runText(), runTerm(), runQuery(state.q)]);
}
