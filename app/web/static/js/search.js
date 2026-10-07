// The search page: the query form, the four-signal formula, and the ranked results.
//
// One request (`/api/compare`) returns B0 (BM25 only), B1 (+ continuity) and the full ranking over the same signals, so the switch above
// the results changes instantly and the re-ordering is animated with Flip. A result opens in place to show its score arithmetic and the
// treatment evidence behind it. Everything from a judgment is inserted as text.
import { api } from "./api.js";
import { $, $$, clear, f2, f3, formatDate, h, plural, SHORT_CONFIG, SIGNALS, SIGNAL_LABEL, show } from "./dom.js";
import { animateIn, flipSwap, scrollToTarget } from "./motion.js";
import { openReader } from "./reader.js";
import { toast } from "./ui.js";

const EXAMPLES = [
  { q: "BNS 103", date: "2025-01-10" },
  { q: "IPC 302", date: "2020-01-01" },
  { q: "murder common intention", date: "" },
  { q: "anticipatory bail", date: "" },
];
const OWNER = { rel: "M1", cont: "M2", health: "M3", auth: "M3" };
const NEGATIVE = ["overruled", "doubted", "criticised", "criticized"];

export const state = { data: null, config: "full", k: 10, query: "", date: "", seq: 0, open: new Set() };
const els = {};

// ------------------------------------------------------------------------------------------------------------- the formula
/** final = w_r rel + w_s cont + w_h health + w_a auth, with the live weights and the module that produces each signal. */
export function renderFormula(status) {
  const box = $("#formula");
  clear(box);
  const w = status && status.configs && status.configs.full ? status.configs.full.weights : null;
  const stubbed = status ? status.stubbed || [] : [];
  const group = { rel: "search", cont: "statute", health: "health", auth: "authority" };
  box.appendChild(h("li", { class: "f-op", "aria-hidden": "true" }, "final ="));
  SIGNALS.forEach((s, i) => {
    if (i) box.appendChild(h("li", { class: "f-op", "aria-hidden": "true" }, "+"));
    box.appendChild(h("li", { class: `sig-${s.key}` }, [
      h("span", { class: "f-by" }, `${OWNER[s.key]}${stubbed.includes(group[s.key]) ? " (stub)" : ""}`),
      h("span", { class: "f-name" }, SIGNAL_LABEL[s.key]),
      h("span", { class: "f-w" }, w ? `weight ${f2(w[s.key])}` : "weight unknown"),
    ]));
  });
}

// ------------------------------------------------------------------------------------------------------------- one result
/** The text in brackets of one signal's part of the explanation, e.g. "BNS 103 -> IPC 302 (OFF_MURDER) (equivalent)". */
export function reasonOf(r, key) {
  const part = (r.parts || []).find((p) => p.startsWith(`${key} `));
  if (!part) return "";
  const open = part.indexOf("(");
  return open === -1 ? "" : part.slice(open + 1).replace(/\)\s*$/, "");
}

function moveBadge(r, name) {
  if (name === "b0" || !r.ranks || r.ranks.b0 == null) return null;
  const d = r.ranks.b0 - r.rank;
  if (d > 0) return h("span", { class: "move up", dataset: { tip: `BM25 alone ranks it ${r.ranks.b0}` } }, `↑ ${d} vs BM25`);
  if (d < 0) return h("span", { class: "move down", dataset: { tip: `BM25 alone ranks it ${r.ranks.b0}` } }, `↓ ${-d} vs BM25`);
  return null;
}

function sigBars(r, block) {
  return h("div", { class: "sigbars" }, SIGNALS.map((s) => {
    const used = block.signals_used.includes(s.key);
    const stub = block.stubbed.includes(s.key);
    return h("span", { class: `sigbar sig-${s.key}${used ? "" : " is-off"}${stub ? " is-stub" : ""}`, dataset: { tip: `${SIGNAL_LABEL[s.key]} ${f2(r.normalised[s.key])}${stub ? " (stub value)" : ""}${used ? "" : ", not used here"}` } }, [
      h("span", {}, SIGNAL_LABEL[s.key]),
      h("span", { class: "bar" }, h("i", { vars: { "--w": `${Math.round(Math.max(0, Math.min(1, r.normalised[s.key] || 0)) * 100)}%` } })),
    ]);
  }));
}

function breakdown(r, block) {
  const rows = SIGNALS.filter((s) => block.signals_used.includes(s.key)).map((s) => h("tr", {}, [
    h("td", {}, h("span", { class: `sig-name sig-${s.key}` }, [h("span", { class: "legend-dot" }), SIGNAL_LABEL[s.key], block.stubbed.includes(s.key) ? h("span", { class: "tag is-stub" }, "stub") : null])),
    h("td", { class: "num" }, f2(r.normalised[s.key])),
    h("td", { class: "num" }, `× ${f2(block.weights[s.key])}`),
    h("td", { class: "num" }, `= ${f3(r.contributions[s.key])}`),
    h("td", { class: "reason" }, reasonOf(r, s.key)),
  ]));
  rows.push(h("tr", {}, [h("td", {}, h("b", {}, "Final")), h("td"), h("td"), h("td", { class: "num" }, h("b", {}, f3(r.final))), h("td")]));
  return h("div", { class: "table-wrap" }, h("table", { class: "breakdown" }, [
    h("thead", {}, h("tr", {}, ["Signal", "Score", "Weight", "Adds", "Why"].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", {}, rows),
  ]));
}

export function evidenceList(r, stub, query) {
  const ev = r.evidence || [];
  if (!ev.length) return h("p", { class: "note" }, "No treatment evidence: no later judgment in the corpus was found citing this one.");
  const items = ev.map((e) => {
    const label = String(e.label || "neutral").toLowerCase();
    const st = label === "overruled" ? "over" : label === "doubted" || label.startsWith("critici") ? "doubt" : label === "followed" ? "follow" : "neutral";
    return h("div", { class: "evidence-item" }, [
      h("div", { class: "evidence-head" }, [
        h("span", { class: `chip st-${label}${stub ? " is-stub" : ""}` }, label),
        h("span", {}, ["cited in ", h("button", { class: "linklike mono", type: "button", onclick: () => openReader(e.citing_doc, "", query, { passage: e.sentence }) }, e.citing_doc)]),
        e.citing_bench ? h("span", {}, `${e.citing_bench}-judge bench`) : null,
        typeof e.confidence === "number" ? h("span", {}, `confidence ${f2(e.confidence)}`) : null,
        stub ? h("span", { class: "tag is-stub" }, "stub") : null,
      ]),
      h("blockquote", { class: "is-clamped", title: "Click to show the whole passage", vars: { "--st": `var(--st-${st})` }, onclick: (event) => event.currentTarget.classList.toggle("is-clamped") }, e.sentence),
    ]);
  });
  // two passages are enough to explain a status; the rest stay one click away
  const box = h("div", { class: "evidence" }, items.slice(0, 2));
  if (items.length > 2) {
    const more = h("button", { class: "linklike note", type: "button" }, `Show ${items.length - 2} more`);
    more.addEventListener("click", () => { more.replaceWith(...items.slice(2)); });
    box.appendChild(more);
  }
  return box;
}

function resultItem(r, name, block, list) {
  const open = state.open.has(r.doc_id);
  const negative = (r.evidence || []).find((e) => NEGATIVE.includes(String(e.label).toLowerCase()));
  const detail = h("div", { class: "result-detail", hidden: !open }, open ? detailBody(r, block, list) : null);
  const row = h("button", { class: "result-row", type: "button", "aria-expanded": String(open) }, [
    h("span", { class: "rank" }, String(r.rank)),
    h("span", {}, [
      h("span", { class: "result-title", title: r.title || r.doc_id }, r.title || r.doc_id),
      h("span", { class: "result-meta" }, [
        r.date ? h("span", {}, formatDate(r.date)) : null,
        r.bench_size ? h("span", {}, `${r.bench_size}-judge bench`) : null,
        moveBadge(r, name),
        r.health < 0.999 ? h("span", { class: `chip st-${negative ? String(negative.label).toLowerCase() : "lowered"}` }, negative ? String(negative.label).toLowerCase() : "treatment lowered") : null,
      ]),
    ]),
    sigBars(r, block),
    h("span", { class: "final", dataset: { tip: "Final score" } }, f2(r.final)),
  ]);
  row.addEventListener("click", () => {
    const now = detail.hidden;
    if (now) { state.open.add(r.doc_id); if (!detail.firstChild) detail.append(...detailBody(r, block, list)); }
    else state.open.delete(r.doc_id);
    detail.hidden = !now;
    row.setAttribute("aria-expanded", String(now));
    if (now) animateIn(detail, { y: 6 });
  });
  return h("li", { class: "result", dataset: { doc: r.doc_id, flipId: r.doc_id } }, [row, detail]);
}

function detailBody(r, block, list) {
  return [
    breakdown(r, block),
    block.signals_used.includes("health") || (r.evidence || []).length ? evidenceList(r, block.stubbed.includes("health"), state.query) : null,
    h("div", { class: "detail-actions" }, [
      h("button", { class: "btn btn-small", type: "button", onclick: () => openReader(r.doc_id, r.title || "", state.query, { list }) }, "Read judgment"),
      h("span", { class: "note mono" }, r.doc_id),
    ]),
  ].filter(Boolean);
}

// ------------------------------------------------------------------------------------------------------------- the list
function header() {
  const data = state.data;
  const block = data.configs[state.config];
  els.title.textContent = data.query;
  els.sub.textContent = [`${plural(block.results.length, "result")} of ${plural(data.candidates, "candidate")}`, SHORT_CONFIG[state.config], `${data.elapsed_ms} ms`, data.offence_date ? `offence date ${data.offence_date}` : ""].filter(Boolean).join("  ·  ");
  show(els.stub, block.stubbed.length > 0);
  if (block.stubbed.length) els.stub.textContent = `Stub mode: ${block.stubbed.map((s) => SIGNAL_LABEL[s]).join(", ")} come from fixed-value stand-ins, not from real data. What is shown here is not a result.`;
  show(els.error, false);
}

function renderList({ flip = false } = {}) {
  const data = state.data;
  if (!data) return;
  $$("#ladder button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.config === state.config)));
  header();
  const block = data.configs[state.config];
  if (!block.results.length) {
    els.main.replaceChildren(h("li", { class: "empty" }, [h("strong", {}, "No judgment matched this query"), "Try fewer words, a section such as BNS 103, or a Boolean query such as murder AND intention."]));
    return;
  }
  const list = block.results.map((r) => ({ doc_id: r.doc_id, title: r.title }));
  const build = () => els.main.replaceChildren(...block.results.map((r) => resultItem(r, state.config, block, list)));
  if (flip) flipSwap(els.main, build);
  else { build(); animateIn(els.main.children, { stagger: 0.03 }); }
}

function showError(message) {
  show(els.workspace, true);
  els.error.textContent = message;
  show(els.error, true);
  show(els.stub, false);
  els.main.replaceChildren();
}

// ------------------------------------------------------------------------------------------------------------- running a search
function writeHash() {
  const p = new URLSearchParams();
  p.set("q", state.query);
  if (state.date) p.set("date", state.date);
  if (state.config !== "full") p.set("config", state.config);
  history.replaceState(null, "", `#/?${p.toString()}`);
}

export async function run({ scroll = true } = {}) {
  const q = els.q.value.trim();
  if (!q) { els.q.focus(); return; }
  state.query = q;
  state.date = els.date.value || "";
  state.open.clear();
  show(els.workspace, true);
  show(els.error, false);
  els.title.textContent = q;
  els.sub.textContent = "Searching";
  els.main.replaceChildren(...[0, 1, 2].map(() => h("li", { class: "skeleton" })));
  els.btn.disabled = true;
  $("#busy").classList.add("is-on");
  const seq = ++state.seq;
  if (scroll) window.setTimeout(() => scrollToTarget(els.workspace, { offset: 80 }), 60);
  try {
    const data = await api.compare(state.query, state.date, state.k);
    if (seq !== state.seq) return;
    state.data = data;
    renderList();
    writeHash();
  } catch (err) {
    if (seq !== state.seq) return;
    state.data = null;
    showError(err.message);
    toast(err.message, "error", 5000);
  } finally {
    if (seq === state.seq) { els.btn.disabled = false; $("#busy").classList.remove("is-on"); }
  }
}

function setConfig(name) {
  if (state.config === name) return;
  state.config = name;
  if (!state.data) { $$("#ladder button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.config === name))); return; }
  renderList({ flip: true });
  writeHash();
}

// ------------------------------------------------------------------------------------------------------------- routing helpers
export function focusQuery() {
  scrollToTarget("#top", { offset: 0 });
  window.setTimeout(() => els.q.focus({ preventScroll: true }), 300);
}

/** The query last searched on this page, so the module pages can open on the same query. */
export function currentQuery() {
  return state.query ? { q: state.query, date: state.date } : null;
}

// A link that carries a query (pasted into this tab, or reached with back and forward) differs from what is on screen.
export function paramsDiffer(params) {
  const q = params.get("q");
  if (!q) return false;
  return q !== state.query || (params.get("date") || "") !== state.date;
}

export function applyParams(params, { scroll = false } = {}) {
  const q = params.get("q");
  if (!q) return false;
  els.q.value = q;
  els.date.value = params.get("date") || "";
  state.config = ["b0", "b1", "full"].includes(params.get("config")) ? params.get("config") : "full";
  run({ scroll });
  return true;
}

export function initSearch() {
  Object.assign(els, {
    form: $("#search-form"), q: $("#q"), date: $("#date"), btn: $("#btn-search"), workspace: $("#workspace"),
    title: $("#ws-title"), sub: $("#ws-sub"), stub: $("#ws-stub"), error: $("#ws-error"), main: $("#ws-main"),
  });
  els.form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  $$("#ladder button").forEach((b) => b.addEventListener("click", () => setConfig(b.dataset.config)));
  const chips = $("#examples");
  EXAMPLES.forEach((x) => chips.appendChild(h("button", { class: "chip-btn", type: "button", onclick: () => { els.q.value = x.q; els.date.value = x.date; run(); } }, [x.q, x.date ? h("small", {}, x.date) : null])));
}
