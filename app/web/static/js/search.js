// The search workspace: the query form, suggestions, ranked results with their score arithmetic and evidence, and the
// side-by-side comparison with plain BM25.
import { api } from "./api.js";
import { $, $$, clear, f2, f3, formatDate, h, pct, plural, SHORT_CONFIG, SIGNALS, SIGNAL_LABEL, show, store } from "./dom.js";
import { requestFrame } from "./motion.js";
import { openReader } from "./reader.js";

const HISTORY_KEY = "lexshift.history";
const TYPE_LABEL = {
  A: "A: a BNS section that needs an IPC-era precedent",
  B: "B: provisions that changed, were omitted or are new",
  C: "C: doctrines with overruled cases",
  D: "D: the same number in the IPC and the BNS",
};
const NEGATIVE = ["overruled", "doubted", "criticised", "criticized"];

export const state = { data: null, mode: "ranked", config: "full", k: 10, query: "", date: "", seq: 0, examples: null };

const els = {};

// ------------------------------------------------------------------------------------------------------------- helpers
const rightConfig = () => (state.config === "b0" ? "full" : state.config);
const weightsText = (w) => SIGNALS.filter((s) => (w[s.key] || 0) > 0).map((s) => `${s.short} ${f2(w[s.key])}`).join("  ·  ");

function scoreRing(value) {
  const r = 22;
  const c = 2 * Math.PI * r;
  return h("div", { class: "score", title: `final score ${f3(value)}` },
    h("svg:svg", { viewBox: "0 0 52 52", "aria-hidden": "true" }, [
      h("svg:circle", { cx: 26, cy: 26, r, class: "track" }),
      h("svg:circle", { cx: 26, cy: 26, r, class: "value", "stroke-dasharray": `${(c * Math.max(0, Math.min(1, value))).toFixed(1)} ${c.toFixed(1)}` }),
    ]),
    h("b", {}, f2(value)));
}

function moveBadge(r, name) {
  if (name === "b0" || !r.ranks || r.ranks.b0 == null) return null;
  const d = r.ranks.b0 - r.rank;
  if (d > 0) return h("span", { class: "move up", title: `BM25 alone ranks it ${r.ranks.b0}` }, `up ${d} vs BM25`);
  if (d < 0) return h("span", { class: "move down", title: `BM25 alone ranks it ${r.ranks.b0}` }, `down ${-d} vs BM25`);
  return h("span", { class: "move", title: "Same position as BM25 alone" }, "same as BM25");
}

function treatment(r, block) {
  const ev = r.evidence || [];
  const negative = ev.find((e) => NEGATIVE.includes(String(e.label).toLowerCase()));
  const stub = block.stubbed.includes("health");
  const usedHealth = block.signals_used.includes("health");
  const lowered = r.health < 0.999;
  const label = lowered ? (negative ? String(negative.label).toLowerCase() : "lowered") : "clear";
  const text = lowered
    ? `Treatment signal: ${label} (health ${f2(r.health)})`
    : "No valid negative treatment found";
  const chip = h("span", { class: `chip st-${label}${stub ? " is-stub" : ""}`, title: stub ? "This value is a fixed-value stand-in" : "" }, stub ? `Stub value. ${text}` : text);
  const parts = [chip];
  if (lowered && negative) parts.push(h("span", { class: "why" }, ["per ", h("span", { class: "mono" }, negative.citing_doc)]));
  if (!usedHealth) parts.push(h("span", { class: "why" }, "not used by this ranking"));
  return h("div", { class: "status" }, parts);
}

function reasonOf(r, key) {
  const part = (r.parts || []).find((p) => p.startsWith(`${key} `));
  if (!part) return "";
  const open = part.indexOf("(");
  return open === -1 ? "" : part.slice(open + 1).replace(/\)\s*$/, "");
}

function breakdown(r, block) {
  const rows = SIGNALS.filter((s) => block.signals_used.includes(s.key)).map((s) => h("tr", {}, [
    h("td", {}, h("span", { class: `sig-name sig-${s.key}` }, [h("span", { class: "legend-dot" }), SIGNAL_LABEL[s.key], block.stubbed.includes(s.key) ? h("span", { class: "tag is-stub" }, "stub") : null])),
    h("td", { class: "num" }, f2(r.raw[s.key])),
    h("td", { class: "num" }, f2(r.normalised[s.key])),
    h("td", { class: "num" }, f2(block.weights[s.key])),
    h("td", { class: "num" }, f3(r.contributions[s.key])),
    h("td", { class: "reason" }, reasonOf(r, s.key)),
  ]));
  rows.push(h("tr", {}, [h("td", {}, h("b", {}, "Final")), h("td"), h("td"), h("td"), h("td", { class: "num" }, h("b", {}, f3(r.final))), h("td", { class: "reason" }, "the sum of the contributions")]));
  return h("details", { class: "fold" }, [
    h("summary", {}, "Score breakdown"),
    h("div", { class: "table-wrap" }, h("table", { class: "breakdown" }, [
      h("thead", {}, h("tr", {}, ["Signal", "Raw", "Normalised", "Weight", "Contribution", "Reason"].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", {}, rows),
    ])),
  ]);
}

function evidenceFold(r, block) {
  const ev = r.evidence || [];
  if (!ev.length) return null;
  const stub = block.stubbed.includes("health");
  return h("details", { class: "fold", open: ev.some((e) => NEGATIVE.includes(String(e.label).toLowerCase())) && !stub ? "" : null }, [
    h("summary", {}, `Treatment evidence (${ev.length})`),
    ...ev.map((e) => {
      const label = String(e.label || "neutral").toLowerCase();
      const conf = typeof e.confidence === "number" ? e.confidence : null;
      return h("div", { class: "evidence-item" }, [
        h("div", { class: "evidence-head" }, [
          h("span", { class: `chip st-${label}${stub ? " is-stub" : ""}` }, label),
          h("span", {}, ["in ", h("button", { class: "linklike mono", type: "button", onclick: () => openReader(e.citing_doc, "", state.query) }, e.citing_doc)]),
          e.citing_bench ? h("span", { class: "tag" }, `${e.citing_bench}-judge bench`) : null,
          conf !== null ? h("span", { class: "conf" }, ["confidence ", f2(conf), h("span", { class: "conf-bar" }, h("i", { vars: { "--w": pct(conf) } }))]) : null,
          stub ? h("span", { class: "tag is-stub" }, "stub") : null,
        ]),
        h("blockquote", { vars: { "--st": `var(--st-${label === "overruled" ? "over" : label === "doubted" || label === "criticised" ? "doubt" : label === "followed" ? "follow" : "neutral"})` } }, e.sentence),
      ]);
    }),
  ]);
}

function resultCard(r, name, block) {
  const used = SIGNALS.filter((s) => block.signals_used.includes(s.key));
  const bar = h("div", { class: "contrib-bar", role: "img", "aria-label": `final ${f2(r.final)} made of ${used.map((s) => `${SIGNAL_LABEL[s.key]} ${f3(r.contributions[s.key])}`).join(", ")}` },
    used.filter((s) => r.contributions[s.key] > 0).map((s) => h("span", { class: `seg sig-${s.key}${block.stubbed.includes(s.key) ? " is-stub" : ""}`, title: `${SIGNAL_LABEL[s.key]} ${f3(r.contributions[s.key])}`, vars: { "--w": `${(r.contributions[s.key] * 100).toFixed(2)}%` } })));
  const legend = h("ul", { class: "legend" }, used.map((s) => h("li", { class: `sig-${s.key}` }, [
    h("span", { class: `legend-dot${block.stubbed.includes(s.key) ? " is-stub" : ""}` }),
    `${SIGNAL_LABEL[s.key]} ${f3(r.contributions[s.key])}`,
    block.stubbed.includes(s.key) ? h("span", { class: "tag is-stub" }, "stub") : null,
  ])));
  return h("li", { class: "result", dataset: { doc: r.doc_id } }, [
    h("div", { class: "result-head" }, [
      h("div", { class: "rank", "aria-label": `Rank ${r.rank}` }, String(r.rank)),
      h("div", {}, [
        h("h3", { class: "result-title" }, h("button", { class: "linklike", type: "button", onclick: () => openReader(r.doc_id, r.title || "", state.query) }, r.title || r.doc_id)),
        h("p", { class: "result-meta" }, [
          h("span", { class: "mono" }, r.doc_id),
          r.date ? h("span", {}, formatDate(r.date)) : null,
          r.bench_size ? h("span", {}, `${r.bench_size}-judge bench`) : null,
          moveBadge(r, name),
        ]),
      ]),
      scoreRing(r.final),
    ]),
    h("div", { class: "contrib" }, [bar, legend]),
    treatment(r, block),
    breakdown(r, block),
    evidenceFold(r, block),
  ]);
}

// ------------------------------------------------------------------------------------------------------------- statutes
function renderStatutes(st, date) {
  const box = els.statutes;
  clear(box);
  box.appendChild(h("h3", {}, "How the query was read"));
  if (!st || st.used === false) { box.appendChild(h("p", { class: "hint" }, "This ranking does not use statutes.")); return; }
  if (st.error) { box.appendChild(h("p", { class: "hint" }, `The statute module could not read it: ${st.error}`)); return; }
  const dl = h("dl", {});
  dl.appendChild(h("div", {}, [h("dt", {}, "Governing code"), h("dd", {}, st.governing_act ? [h("span", { class: "tag" }, st.governing_act), date ? ` decided by the offence date ${date}` : " named in the query"] : "Not determined: no code named and no offence date")]));
  if (st.refs.length) {
    dl.appendChild(h("div", {}, [h("dt", {}, "Sections found"), h("dd", {}, st.refs.map((ref) => h("div", { class: "ref" }, [h("span", {}, `${ref.act} ${ref.section}`), ref.offence_id ? h("span", { class: "tag" }, ref.offence_id) : null])))]));
  } else {
    dl.appendChild(h("div", {}, [h("dt", {}, "Sections found"), h("dd", {}, "None")]));
  }
  if (st.notes.length) dl.appendChild(h("div", {}, [h("dt", {}, "Notes"), h("dd", {}, st.notes.map((n) => h("p", {}, n)))]));
  box.appendChild(dl);
  if (!st.refs.length) box.appendChild(h("p", { class: "hint" }, "Continuity is informative only when the query names a section, for example BNS 103."));
}

// ------------------------------------------------------------------------------------------------------------- compare
function slopeRow(r, side, other, k) {
  const otherRank = r.ranks[other];
  const inOther = otherRank != null && otherRank <= k;
  const delta = side === "right" && r.ranks.b0 != null ? r.ranks.b0 - r.rank : 0;
  const lowered = r.health < 0.999;
  return h("button", { class: "slope-row", type: "button", dataset: { doc: r.doc_id }, title: r.title || r.doc_id, onclick: () => openReader(r.doc_id, r.title || "", state.query) }, [
    h("span", { class: "n" }, String(r.rank)),
    h("span", { class: "t" }, r.title || r.doc_id),
    h("span", { class: "f" }, [
      h("span", {}, f2(r.final)),
      lowered ? h("span", { class: "hdot", title: "Treatment signal: health below 1" }) : null,
      !inOther ? h("span", { class: "out" }, side === "left" ? `#${otherRank} in ${SHORT_CONFIG[other]}` : `from #${otherRank} in BM25`) : (side === "right" && delta !== 0 ? h("span", { class: "out" }, delta > 0 ? `up ${delta}` : `down ${-delta}`) : null),
    ]),
  ]);
}

function drawSlopes(root) {
  const svg = $(".slope-svg", root);
  if (!svg) return;
  const box = svg.getBoundingClientRect();
  if (!box.height) return;
  svg.setAttribute("viewBox", `0 0 100 ${box.height.toFixed(1)}`);
  clear(svg);
  const center = (row) => { const b = row.getBoundingClientRect(); return b.top + b.height / 2 - box.top; };
  const left = new Map($$(".compare-col.left .slope-row", root).map((row) => [row.dataset.doc, row]));
  const right = new Map($$(".compare-col.right .slope-row", root).map((row) => [row.dataset.doc, row]));
  const paths = [];
  for (const [doc, lrow] of left) {
    const yl = center(lrow);
    const rrow = right.get(doc);
    let d, cls = "";
    if (rrow) {
      const yr = center(rrow);
      d = `M0,${yl.toFixed(1)} C50,${yl.toFixed(1)} 50,${yr.toFixed(1)} 100,${yr.toFixed(1)}`;
      cls = yr < yl - 1 ? "up" : yr > yl + 1 ? "down" : "";
    } else { d = `M0,${yl.toFixed(1)} L38,${(yl + 10).toFixed(1)}`; cls = "gone"; }
    paths.push(h("svg:path", { d, class: cls, dataset: { doc } }));
  }
  for (const [doc, rrow] of right) {
    if (left.has(doc)) continue;
    const yr = center(rrow);
    paths.push(h("svg:path", { d: `M100,${yr.toFixed(1)} L62,${(yr - 10).toFixed(1)}`, class: "gone", dataset: { doc } }));
  }
  paths.forEach((p) => svg.appendChild(p));
}

function hot(root, doc, on) {
  root.classList.toggle("has-hot", on);
  $$(`[data-doc="${CSS.escape(doc)}"]`, root).forEach((el) => el.classList.toggle("is-hot", on));
  $$(".slope-svg path", root).forEach((p) => p.classList.toggle("dim", on && p.dataset.doc !== doc));
}

function renderCompare(data) {
  const rname = rightConfig();
  const L = data.configs.b0;
  const R = data.configs[rname];
  const k = data.k;
  const lowerdAndDropped = L.results.filter((r) => r.health < 0.999 && r.ranks[rname] > r.rank);
  const stubHealth = R.stubbed.includes("health");
  const summary = h("p", { class: "ws-sub", vars: {} }, lowerdAndDropped.length
    ? `${plural(lowerdAndDropped.length, "judgment")} in the BM25 top ${k} ${lowerdAndDropped.length === 1 ? "is" : "are"} ranked lower once treatment signals count${stubHealth ? " (stub values, not a result)" : ""}.`
    : `No judgment in the BM25 top ${k} is ranked lower by a treatment signal for this query.`);
  const column = (cls, title, sub, rows) => h("div", { class: `compare-col ${cls}` }, [h("h3", {}, title), h("p", { class: "sub" }, sub), ...rows]);
  const root = h("div", { class: "compare" }, [
    column("left", "BM25 only", "Ranked by text relevance alone", L.results.map((r) => slopeRow(r, "left", rname, k))),
    h("div", { class: "compare-gutter", "aria-hidden": "true" }, h("svg:svg", { class: "slope-svg", preserveAspectRatio: "none" })),
    column("right", SHORT_CONFIG[rname], weightsText(R.weights), R.results.map((r) => slopeRow(r, "right", "b0", k))),
  ]);
  els.main.replaceChildren(summary, root);
  root.addEventListener("pointerover", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, true); });
  root.addEventListener("pointerout", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, false); });
  root.addEventListener("focusin", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, true); });
  root.addEventListener("focusout", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, false); });
  const redraw = () => drawSlopes(root);
  requestAnimationFrame(redraw);
  if ("ResizeObserver" in window) new ResizeObserver(redraw).observe(root);
}

// ------------------------------------------------------------------------------------------------------------- render
function emptyState(data) {
  return h("div", { class: "empty" }, [
    h("strong", {}, "No judgment matched this query"),
    `The search returned ${plural(data.candidates, "candidate")}. Try fewer words, a section such as BNS 103, or a Boolean query such as murder AND intention.`,
  ]);
}

function renderResults() {
  const data = state.data;
  if (!data) return;
  const name = state.config;
  const block = data.configs[name];
  $$(".seg-btn", els.workspace).forEach((b) => { const on = b.dataset.mode === state.mode; b.classList.toggle("is-on", on); b.setAttribute("aria-pressed", String(on)); });
  els.cfg.value = name;
  els.title.textContent = data.query;
  const rname = state.mode === "compare" ? rightConfig() : name;
  const shown = data.configs[rname];
  els.sub.textContent = `${plural(shown.results.length, "result")} of ${plural(data.candidates, "candidate")}  ·  ${SHORT_CONFIG[rname]}  ·  ${data.elapsed_ms} ms  ·  weights ${weightsText(shown.weights)} (${shown.source})` + (data.offence_date ? `  ·  offence date ${data.offence_date}` : "");
  const stubs = state.mode === "compare" ? Array.from(new Set([...data.configs.b0.stubbed, ...shown.stubbed])) : block.stubbed;
  show(els.stub, stubs.length > 0);
  if (stubs.length) els.stub.textContent = `Stub mode: ${stubs.map((s) => SIGNAL_LABEL[s]).join(", ")} come from fixed-value stand-ins, not from real data. What is shown here is not a result.`;
  show(els.error, false);
  renderStatutes(data.statutes, data.offence_date);
  if (!data.candidates) { els.main.replaceChildren(emptyState(data)); return; }
  if (state.mode === "compare") renderCompare(data);
  else els.main.replaceChildren(h("ol", { class: "results" }, block.results.map((r) => resultCard(r, name, block))));
  window.dispatchEvent(new Event("lexshift:layout"));
  requestFrame();
}

function renderSkeleton() {
  els.main.replaceChildren(...[0, 1, 2].map(() => h("div", { class: "skeleton" })));
}

function showError(message) {
  show(els.workspace, true);
  els.error.textContent = message;
  show(els.error, true);
  show(els.stub, false);
  els.main.replaceChildren();
  clear(els.statutes);
}

// ------------------------------------------------------------------------------------------------------------- running a search
function writeHash() {
  const p = new URLSearchParams();
  p.set("q", state.query);
  if (state.date) p.set("date", state.date);
  if (state.mode !== "ranked") p.set("mode", state.mode);
  if (state.config !== "full") p.set("config", state.config);
  if (state.k !== 10) p.set("k", String(state.k));
  history.replaceState(null, "", `#/?${p.toString()}`);
}

function remember() {
  const list = store.get(HISTORY_KEY, []).filter((x) => !(x.q === state.query && x.date === state.date));
  list.unshift({ q: state.query, date: state.date });
  store.set(HISTORY_KEY, list.slice(0, 8));
}

export async function run({ scroll = true } = {}) {
  const q = els.q.value.trim();
  if (!q) { els.q.focus(); showError("Enter a query: free text, a section such as BNS 103, or a Boolean query."); return; }
  state.query = q;
  state.date = els.date.value || "";
  state.k = Number(els.k.value) || 10;
  show(els.workspace, true);
  show(els.error, false);
  els.sub.textContent = "Searching";
  renderSkeleton();
  [els.btnSearch, els.btnCompare].forEach((b) => { b.disabled = true; });
  els.workspace.setAttribute("aria-busy", "true");
  const seq = ++state.seq;
  if (scroll) els.workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const data = await api.compare(state.query, state.date, state.k);
    if (seq !== state.seq) return;
    state.data = data;
    renderResults();
    remember();
    writeHash();
    window.dispatchEvent(new CustomEvent("lexshift:results", { detail: { data, config: state.config } }));
  } catch (err) {
    if (seq !== state.seq) return;
    state.data = null;
    showError(err.message);
  } finally {
    if (seq === state.seq) {
      [els.btnSearch, els.btnCompare].forEach((b) => { b.disabled = false; });
      els.workspace.removeAttribute("aria-busy");
    }
  }
}

// ------------------------------------------------------------------------------------------------------------- suggestions
let activeIndex = -1;
let items = [];

function suggestionsFor(text) {
  const needle = text.trim().toLowerCase();
  const groups = [];
  const recent = store.get(HISTORY_KEY, []).filter((x) => !needle || x.q.toLowerCase().includes(needle));
  if (recent.length) groups.push({ title: "Recent", rows: recent.slice(0, 5).map((x) => ({ q: x.q, date: x.date })) });
  const examples = (state.examples ? state.examples.queries : []).filter((x) => !needle || x.text.toLowerCase().includes(needle));
  for (const type of ["A", "B", "C", "D"]) {
    const rows = examples.filter((x) => x.type === type).slice(0, needle ? 6 : 4);
    if (rows.length) groups.push({ title: TYPE_LABEL[type], rows: rows.map((x) => ({ q: x.text, date: x.offence_date || "" })) });
  }
  return groups;
}

function renderSuggest() {
  const groups = suggestionsFor(els.q.value);
  clear(els.suggest);
  items = [];
  if (!groups.length) { closeSuggest(); return; }
  els.suggest.style.setProperty("--sg-top", `${els.searchbar.offsetHeight + 8}px`);
  for (const g of groups) {
    els.suggest.appendChild(h("div", { class: "suggest-group" }, g.title));
    for (const row of g.rows) {
      const btn = h("button", { class: "suggest-item", type: "button", role: "option", tabindex: "-1" }, [h("span", { class: "s-text" }, row.q), h("span", { class: "s-date" }, row.date || "no date")]);
      btn.addEventListener("mousedown", (e) => e.preventDefault());
      btn.addEventListener("click", () => pick(row));
      els.suggest.appendChild(btn);
      items.push({ btn, row });
    }
  }
  els.suggest.appendChild(h("div", { class: "suggest-foot" }, "Suggested queries are examples to try, not the judged set. Edit them freely."));
  activeIndex = -1;
  show(els.suggest, true);
  els.q.setAttribute("aria-expanded", "true");
}

function closeSuggest() {
  show(els.suggest, false);
  els.q.setAttribute("aria-expanded", "false");
  activeIndex = -1;
}

function pick(row) {
  els.q.value = row.q;
  els.date.value = row.date || "";
  closeSuggest();
  run();
}

function moveActive(delta) {
  if (!items.length) return;
  activeIndex = (activeIndex + delta + items.length) % items.length;
  items.forEach((it, i) => it.btn.classList.toggle("is-active", i === activeIndex));
  items[activeIndex].btn.scrollIntoView({ block: "nearest" });
}

// ------------------------------------------------------------------------------------------------------------- init
export function focusQuery() {
  els.q.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => els.q.focus({ preventScroll: true }), 350);
}

export function applyParams(params) {
  const q = params.get("q");
  if (!q) return false;
  els.q.value = q;
  els.date.value = params.get("date") || "";
  state.mode = params.get("mode") === "compare" ? "compare" : "ranked";
  state.config = ["b0", "b1", "full"].includes(params.get("config")) ? params.get("config") : "full";
  els.k.value = ["5", "10", "20", "50"].includes(params.get("k")) ? params.get("k") : "10";
  run({ scroll: false });
  return true;
}

export function initSearch() {
  Object.assign(els, {
    form: $("#search-form"), q: $("#q"), date: $("#date"), searchbar: $(".searchbar"), suggest: $("#suggest"),
    btnSearch: $("#btn-search"), btnCompare: $("#btn-compare"), workspace: $("#workspace"), title: $("#ws-title"), sub: $("#ws-sub"),
    stub: $("#ws-stub"), error: $("#ws-error"), statutes: $("#statutes"), main: $("#ws-main"), cfg: $("#cfg"), k: $("#kk"),
  });
  els.form.addEventListener("submit", (e) => { e.preventDefault(); closeSuggest(); state.mode = "ranked"; run(); });
  els.btnCompare.addEventListener("click", () => { closeSuggest(); state.mode = "compare"; run(); });
  $$(".seg-btn", els.workspace).forEach((b) => b.addEventListener("click", () => { state.mode = b.dataset.mode; if (state.data) { renderResults(); writeHash(); } }));
  els.cfg.addEventListener("change", () => { state.config = els.cfg.value; if (state.data) { renderResults(); writeHash(); window.dispatchEvent(new CustomEvent("lexshift:results", { detail: { data: state.data, config: state.config } })); } });
  els.k.addEventListener("change", () => { if (state.query) run({ scroll: false }); });
  els.q.addEventListener("focus", () => { if (!state.examples) api.examples().then((x) => { state.examples = x; if (document.activeElement === els.q) renderSuggest(); }).catch(() => { state.examples = { queries: [] }; }); renderSuggest(); });
  els.q.addEventListener("input", renderSuggest);
  els.q.addEventListener("blur", () => window.setTimeout(closeSuggest, 120));
  els.q.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); if (els.suggest.hidden) renderSuggest(); moveActive(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); moveActive(-1); }
    else if (e.key === "Escape") closeSuggest();
    else if (e.key === "Enter" && activeIndex >= 0) { e.preventDefault(); pick(items[activeIndex].row); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) && !e.metaKey && !e.ctrlKey) { e.preventDefault(); focusQuery(); }
  });
}
