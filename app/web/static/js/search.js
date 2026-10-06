// The search workspace: the query form and suggestions, ranked results with their score arithmetic and evidence, and the side-by-side
// comparison with plain BM25.
//
// One request (`/api/compare`) returns B0, B1 and the full ranking over the same signals, so the ranking ladder switches instantly and
// the movement is shown, not just the end state: the results are re-ordered with Flip. Keyboard: j and k move between results, Enter
// reads the judgment, e opens the details, c copies the id, 1 to 3 pick the signals, m toggles compare, f flags only treatment-lowered
// results, / focuses the search box and ? lists the shortcuts.
import { api } from "./api.js";
import { $, $$, clear, f2, f3, formatDate, h, plural, SHORT_CONFIG, SIGNALS, SIGNAL_LABEL, show, store } from "./dom.js";
import { animateIn, crossfade, flipSwap, motionOn, requestFrame, scrollToTarget } from "./motion.js";
import { openReader } from "./reader.js";
import { openPanel, reveal, toast } from "./ui.js";

const gsap = window.gsap;
const HISTORY_KEY = "lexshift.history";
const TYPE_LABEL = {
  A: "A: a BNS section that needs an IPC-era precedent",
  B: "B: provisions that changed, were omitted or are new",
  C: "C: doctrines with overruled cases",
  D: "D: the same number in the IPC and the BNS",
};
const NEGATIVE = ["overruled", "doubted", "criticised", "criticized"];
const SHORTCUTS = [
  ["j / k", "Next and previous result"], ["Enter", "Read the focused judgment"], ["e", "Open or close the focused result's details"],
  ["c", "Copy the focused result's id"], ["1 2 3", "Relevance, + continuity, + treatment and authority"], ["m", "Switch between ranked and compare"],
  ["f", "Show only results with a treatment signal"], ["/", "Focus the search box"], ["?", "This list"], ["Esc", "Close a panel"],
];

export const state = { data: null, mode: "ranked", config: "full", k: 10, query: "", date: "", seq: 0, examples: null, onlyLowered: false };
const els = {};

// ------------------------------------------------------------------------------------------------------------- helpers
const rightConfig = () => (state.config === "b0" ? "full" : state.config);
const weightsText = (w) => SIGNALS.filter((s) => (w[s.key] || 0) > 0).map((s) => `${s.short} ${f2(w[s.key])}`).join("  ·  ");
const lowered = (r) => r.health < 0.999;

function scoreRing(value) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return h("div", { class: "score", dataset: { tip: `Final score ${f3(value)}` } }, [
    h("svg:svg", { viewBox: "0 0 52 52", "aria-hidden": "true" }, [
      h("svg:circle", { cx: 26, cy: 26, r, class: "track" }),
      h("svg:circle", { cx: 26, cy: 26, r, class: "value", "stroke-dasharray": c.toFixed(2), "stroke-dashoffset": (c * (1 - v)).toFixed(2), dataset: { c: c.toFixed(2) } }),
    ]),
    h("b", { dataset: { v: value } }, f2(value)),
  ]);
}

function moveBadge(r, name) {
  if (name === "b0" || !r.ranks || r.ranks.b0 == null) return null;
  const d = r.ranks.b0 - r.rank;
  const tip = `BM25 alone ranks it ${r.ranks.b0}`;
  if (d > 0) return h("span", { class: "move up", dataset: { tip } }, `up ${d} vs BM25`);
  if (d < 0) return h("span", { class: "move down", dataset: { tip } }, `down ${-d} vs BM25`);
  return h("span", { class: "move", dataset: { tip: "Same position as BM25 alone" } }, "same as BM25");
}

function treatment(r, block) {
  const ev = r.evidence || [];
  const negative = ev.find((e) => NEGATIVE.includes(String(e.label).toLowerCase()));
  const stub = block.stubbed.includes("health");
  const usedHealth = block.signals_used.includes("health");
  const isLow = lowered(r);
  const label = isLow ? (negative ? String(negative.label).toLowerCase() : "lowered") : "clear";
  const text = isLow ? `Treatment signal: ${label} (health ${f2(r.health)})` : "No valid negative treatment found";
  const chip = h("span", { class: `chip st-${label}${stub ? " is-stub" : ""}`, dataset: stub ? { tip: "This value is a fixed-value stand-in" } : {} }, stub ? `Stub value. ${text}` : text);
  const parts = [chip];
  if (isLow && negative) parts.push(h("span", { class: "why" }, ["per ", h("span", { class: "mono" }, negative.citing_doc)]));
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
  return h("details", { class: "fold", dataset: { fold: "breakdown" } }, [
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
  return h("details", { class: "fold", dataset: { fold: "evidence" }, open: ev.some((e) => NEGATIVE.includes(String(e.label).toLowerCase())) && !stub ? "" : null }, [
    h("summary", {}, `Treatment evidence (${ev.length})`),
    ...ev.map((e) => {
      const label = String(e.label || "neutral").toLowerCase();
      const conf = typeof e.confidence === "number" ? e.confidence : null;
      return h("div", { class: "evidence-item" }, [
        h("div", { class: "evidence-head" }, [
          h("span", { class: `chip st-${label}${stub ? " is-stub" : ""}` }, label),
          h("span", {}, ["in ", h("button", { class: "linklike mono", type: "button", onclick: () => openReader(e.citing_doc, "", state.query, { passage: e.sentence }) }, e.citing_doc)]),
          e.citing_bench ? h("span", { class: "tag" }, `${e.citing_bench}-judge bench`) : null,
          conf !== null ? h("span", { class: "conf" }, ["confidence ", f2(conf), h("span", { class: "conf-bar" }, h("i", { vars: { "--w": `${Math.round(conf * 100)}%` } }))]) : null,
          stub ? h("span", { class: "tag is-stub" }, "stub") : null,
        ]),
        h("blockquote", { vars: { "--st": `var(--st-${label === "overruled" ? "over" : label === "doubted" || label === "criticised" ? "doubt" : label === "followed" ? "follow" : "neutral"})` } }, e.sentence),
      ]);
    }),
  ]);
}

function copyId(id) {
  const done = () => toast(`Copied ${id}`);
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(id).then(done, () => toast("Copy is not allowed in this browser window", "warn"));
  else toast("Copy is not available in this browser", "warn");
}

function resultCard(r, name, block, list) {
  const used = SIGNALS.filter((s) => block.signals_used.includes(s.key));
  const bar = h("div", { class: "contrib-bar", role: "img", "aria-label": `final ${f2(r.final)} made of ${used.map((s) => `${SIGNAL_LABEL[s.key]} ${f3(r.contributions[s.key])}`).join(", ")}` },
    used.filter((s) => r.contributions[s.key] > 0).map((s) => h("span", { class: `seg sig-${s.key}${block.stubbed.includes(s.key) ? " is-stub" : ""}`, dataset: { tip: `${SIGNAL_LABEL[s.key]} contributes ${f3(r.contributions[s.key])}${block.stubbed.includes(s.key) ? " (stub value)" : ""}` }, vars: { "--w": `${(r.contributions[s.key] * 100).toFixed(2)}%` } })));
  const legend = h("ul", { class: "legend" }, used.map((s) => h("li", { class: `sig-${s.key}` }, [
    h("span", { class: `legend-dot${block.stubbed.includes(s.key) ? " is-stub" : ""}` }),
    `${SIGNAL_LABEL[s.key]} ${f3(r.contributions[s.key])}`,
    block.stubbed.includes(s.key) ? h("span", { class: "tag is-stub" }, "stub") : null,
  ])));
  const read = () => openReader(r.doc_id, r.title || "", state.query, { list });
  return h("li", { class: "result", tabindex: "0", dataset: { doc: r.doc_id, flipId: r.doc_id } }, [
    h("div", { class: "result-head" }, [
      h("div", { class: "rank", "aria-label": `Rank ${r.rank}` }, String(r.rank)),
      h("div", {}, [
        h("h3", { class: "result-title" }, h("button", { class: "linklike", type: "button", onclick: read }, r.title || r.doc_id)),
        h("p", { class: "result-meta" }, [
          h("span", { class: "mono" }, r.doc_id),
          r.date ? h("span", {}, formatDate(r.date)) : null,
          r.bench_size ? h("span", {}, `${r.bench_size}-judge bench`) : null,
          moveBadge(r, name),
          h("button", { class: "mini-btn", type: "button", onclick: () => copyId(r.doc_id), "aria-label": `Copy id ${r.doc_id}` }, "Copy id"),
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
function slopeRow(r, side, other, k, list) {
  const otherRank = r.ranks[other];
  const inOther = otherRank != null && otherRank <= k;
  const delta = side === "right" && r.ranks.b0 != null ? r.ranks.b0 - r.rank : 0;
  return h("button", { class: "slope-row", type: "button", dataset: { doc: r.doc_id }, "aria-label": `${r.title || r.doc_id}, rank ${r.rank}`, onclick: () => openReader(r.doc_id, r.title || "", state.query, { list }) }, [
    h("span", { class: "n" }, String(r.rank)),
    h("span", { class: "t" }, r.title || r.doc_id),
    h("span", { class: "f" }, [
      h("span", {}, f2(r.final)),
      lowered(r) ? h("span", { class: "hdot", dataset: { tip: "Treatment signal: health below 1" } }) : null,
      !inOther ? h("span", { class: "out" }, side === "left" ? `#${otherRank} in ${SHORT_CONFIG[other]}` : `from #${otherRank} in BM25`) : (side === "right" && delta !== 0 ? h("span", { class: "out" }, delta > 0 ? `up ${delta}` : `down ${-delta}`) : null),
    ]),
  ]);
}

function drawSlopes(root, animate) {
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
  if (animate && motionOn()) {
    paths.filter((p) => !p.classList.contains("gone")).forEach((p) => {
      const len = p.getTotalLength ? p.getTotalLength() : 0;
      if (len) gsap.fromTo(p, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.1, ease: "power2.inOut", delay: 0.25, clearProps: "strokeDasharray,strokeDashoffset" });
    });
  }
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
  const list = R.results.map((r) => ({ doc_id: r.doc_id, title: r.title }));
  const dropped = L.results.filter((r) => lowered(r) && r.ranks[rname] > r.rank);
  const stubHealth = R.stubbed.includes("health");
  const summary = h("p", { class: "ws-sub" }, dropped.length
    ? `${plural(dropped.length, "judgment")} in the BM25 top ${k} ${dropped.length === 1 ? "is" : "are"} ranked lower once treatment signals count${stubHealth ? " (stub values, not a result)" : ""}.`
    : `No judgment in the BM25 top ${k} is ranked lower by a treatment signal for this query.`);
  const column = (cls, title, sub, rows) => h("div", { class: `compare-col ${cls}` }, [h("h3", {}, title), h("p", { class: "sub" }, sub), ...rows]);
  const root = h("div", { class: "compare" }, [
    column("left", "BM25 only", "Ranked by text relevance alone", L.results.map((r) => slopeRow(r, "left", rname, k, list))),
    h("div", { class: "compare-gutter", "aria-hidden": "true" }, h("svg:svg", { class: "slope-svg", preserveAspectRatio: "none" })),
    column("right", SHORT_CONFIG[rname], weightsText(R.weights), R.results.map((r) => slopeRow(r, "right", "b0", k, list))),
  ]);
  els.main.replaceChildren(summary, root);
  root.addEventListener("pointerover", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, true); });
  root.addEventListener("pointerout", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, false); });
  root.addEventListener("focusin", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, true); });
  root.addEventListener("focusout", (e) => { const row = e.target.closest(".slope-row"); if (row) hot(root, row.dataset.doc, false); });
  let first = true;
  const redraw = () => { drawSlopes(root, first); first = false; };
  window.requestAnimationFrame(() => window.requestAnimationFrame(redraw));
  if ("ResizeObserver" in window) new ResizeObserver(() => drawSlopes(root, false)).observe(root);
  animateIn($$(".slope-row", root), { y: 14, stagger: 0.03, duration: 0.6 });
}

// ------------------------------------------------------------------------------------------------------------- ranked list
function emptyState(data, filtered) {
  return h("div", { class: "empty" }, filtered
    ? [h("strong", {}, "No result in this list has a treatment signal"), "Turn off the filter to see all of them. With the search real and treatment data built, a lowered result carries its evidence."]
    : [h("strong", {}, "No judgment matched this query"), `The search returned ${plural(data.candidates, "candidate")}. Try fewer words, a section such as BNS 103, or a Boolean query such as murder AND intention.`]);
}

function visible(block) {
  return state.onlyLowered ? block.results.filter(lowered) : block.results;
}

function buildList(block, name) {
  const items = visible(block);
  const list = items.map((r) => ({ doc_id: r.doc_id, title: r.title }));
  return items.map((r) => resultCard(r, name, block, list));
}

function openFolds() {
  return new Map($$(".result", els.main).map((li) => [li.dataset.doc, $$("details.fold[open]", li).map((d) => d.dataset.fold)]));
}

function restoreFolds(saved) {
  $$(".result", els.main).forEach((li) => {
    const was = saved.get(li.dataset.doc);
    if (!was) return;
    $$("details.fold", li).forEach((d) => { d.open = was.includes(d.dataset.fold); });
  });
}

function settleCards(cards) {
  if (!gsap || !motionOn()) return;
  const segs = cards.flatMap((li) => $$(".seg", li));
  gsap.fromTo(segs, { scaleX: 0 }, { scaleX: 1, duration: 1, stagger: 0.02, delay: 0.25, ease: "power3.out", transformOrigin: "left center", clearProps: "transform" });
  cards.forEach((li) => {
    const circle = $(".score .value", li);
    const num = $(".score b", li);
    if (circle) gsap.fromTo(circle, { strokeDashoffset: Number(circle.dataset.c) }, { strokeDashoffset: Number(circle.getAttribute("stroke-dashoffset")), duration: 1.2, delay: 0.2, ease: "power3.out" });
    if (num) {
      const target = Number(num.dataset.v);
      const o = { v: 0 };
      gsap.to(o, { v: target, duration: 1.2, delay: 0.2, ease: "power3.out", onUpdate: () => { num.textContent = o.v.toFixed(2); }, onComplete: () => { num.textContent = target.toFixed(2); } });
    }
  });
}

function renderRanked(block, name, { flip, first }) {
  const data = state.data;
  let list = $("ol.results", els.main);
  const items = visible(block);
  if (!data.candidates || !items.length) {
    els.main.replaceChildren(emptyState(data, data.candidates > 0));
    animateIn(els.main.children, { y: 16 });
    return;
  }
  const saved = list ? openFolds() : new Map();
  const make = () => {
    const cards = buildList(block, name);
    if (!list) { list = h("ol", { class: "results" }); els.main.replaceChildren(list); }
    list.replaceChildren(...cards);
    restoreFolds(saved);
    return cards;
  };
  if (flip && list) {
    // results that leave the list fade first, then the rest move to their new places
    const keep = new Set(items.map((r) => r.doc_id));
    const leaving = $$(".result", list).filter((li) => !keep.has(li.dataset.doc));
    const go = () => flipSwap(list, () => { settleCards(make()); });
    if (leaving.length && motionOn()) gsap.to(leaving, { opacity: 0, y: -10, duration: 0.25, ease: "power2.in", onComplete: go });
    else go();
  } else {
    const cards = make();
    if (first) animateIn(cards, { y: 34, stagger: 0.07, duration: 0.85 });
    settleCards(cards);
  }
}

// ------------------------------------------------------------------------------------------------------------- render
function moveThumb(animate = true) {
  const thumb = $("#ladder-thumb");
  const on = $("#ladder button[aria-checked='true']");
  if (!thumb || !on) return;
  const x = on.offsetLeft;
  const w = on.offsetWidth;
  if (!gsap || !animate || !motionOn()) { thumb.style.transform = `translate3d(${x}px, 0, 0)`; thumb.style.width = `${w}px`; return; }
  gsap.to(thumb, { x, width: w, duration: 0.65, ease: "power3.inOut", overwrite: "auto" });
}

function syncControls(animate = true) {
  $$("#ladder button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.config === state.config)));
  $$("#mode .seg-btn").forEach((b) => { const on = b.dataset.mode === state.mode; b.classList.toggle("is-on", on); b.setAttribute("aria-pressed", String(on)); });
  els.onlyLowered.setAttribute("aria-pressed", String(state.onlyLowered));
  els.onlyLowered.hidden = state.mode === "compare";
  els.expandAll.hidden = state.mode === "compare";
  moveThumb(animate);
}

function header() {
  const data = state.data;
  const rname = state.mode === "compare" ? rightConfig() : state.config;
  const shown = data.configs[rname];
  els.title.textContent = data.query;
  els.sub.textContent = `${plural(visible(shown).length, "result")} of ${plural(data.candidates, "candidate")}  ·  ${SHORT_CONFIG[rname]}  ·  ${data.elapsed_ms} ms  ·  weights ${weightsText(shown.weights)} (${shown.source})` + (data.offence_date ? `  ·  offence date ${data.offence_date}` : "");
  const stubs = state.mode === "compare" ? Array.from(new Set([...data.configs.b0.stubbed, ...shown.stubbed])) : data.configs[state.config].stubbed;
  show(els.stub, stubs.length > 0);
  if (stubs.length) els.stub.textContent = `Stub mode: ${stubs.map((s) => SIGNAL_LABEL[s]).join(", ")} come from fixed-value stand-ins, not from real data. What is shown here is not a result.`;
  show(els.error, false);
}

function renderResults({ flip = false, first = false, animateThumb = true } = {}) {
  const data = state.data;
  if (!data) return;
  syncControls(animateThumb);
  header();
  renderStatutes(data.statutes, data.offence_date);
  const block = data.configs[state.config];
  if (state.mode === "compare") { renderCompare(data); }
  else renderRanked(block, state.config, { flip, first });
  requestFrame();
}

function notify() {
  window.dispatchEvent(new CustomEvent("lexshift:results", { detail: { data: state.data, config: state.config } }));
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

function busy(on) { $("#busy").classList.toggle("is-on", on); }

export async function run({ scroll = true } = {}) {
  const q = els.q.value.trim();
  if (!q) { els.q.focus(); showError("Enter a query: free text, a section such as BNS 103, or a Boolean query."); return; }
  state.query = q;
  state.date = els.date.value || "";
  state.k = Number(els.k.value) || 10;
  const firstShow = els.workspace.hidden;
  show(els.workspace, true);
  show(els.error, false);
  els.sub.textContent = "Searching";
  if (firstShow && gsap && motionOn()) gsap.fromTo(els.workspace, { opacity: 0, y: 36 }, { opacity: 1, y: 0, duration: 0.9, ease: "power3.out", clearProps: "opacity,transform" });
  els.main.replaceChildren(...[0, 1, 2].map(() => h("div", { class: "skeleton" })));
  [els.btnSearch, els.btnCompare].forEach((b) => { b.disabled = true; });
  els.workspace.setAttribute("aria-busy", "true");
  busy(true);
  const seq = ++state.seq;
  requestFrame();
  if (scroll) window.setTimeout(() => scrollToTarget(els.workspace, { offset: 70 }), firstShow ? 120 : 0);
  try {
    const data = await api.compare(state.query, state.date, state.k);
    if (seq !== state.seq) return;
    state.data = data;
    renderResults({ first: true, animateThumb: !firstShow });
    remember();
    writeHash();
    notify();
  } catch (err) {
    if (seq !== state.seq) return;
    state.data = null;
    showError(err.message);
    toast(err.message, "error", 5000);
  } finally {
    if (seq === state.seq) {
      [els.btnSearch, els.btnCompare].forEach((b) => { b.disabled = false; });
      els.workspace.removeAttribute("aria-busy");
      busy(false);
    }
  }
}

// ------------------------------------------------------------------------------------------------------------- controls
function setConfig(name) {
  if (!state.data || state.config === name) { state.config = name; syncControls(); return; }
  state.config = name;
  renderResults({ flip: state.mode === "ranked" });
  writeHash();
  notify();
}

async function setMode(mode) {
  if (state.mode === mode) return;
  state.mode = mode;
  if (!state.data) { syncControls(); return; }
  syncControls();
  await crossfade(els.main, () => renderResults({ animateThumb: false }));
  writeHash();
}

function toggleOnlyLowered() {
  state.onlyLowered = !state.onlyLowered;
  els.onlyLowered.setAttribute("aria-pressed", String(state.onlyLowered));
  if (state.data && state.mode === "ranked") { header(); renderRanked(state.data.configs[state.config], state.config, { flip: true }); }
}

function toggleExpandAll() {
  const on = els.expandAll.getAttribute("aria-pressed") !== "true";
  els.expandAll.setAttribute("aria-pressed", String(on));
  els.expandAll.textContent = on ? "Collapse all" : "Expand all";
  $$("details.fold", els.main).forEach((d) => { d.open = on; });
}

function showShortcuts() {
  const body = $("#keys-body");
  clear(body);
  body.appendChild(h("div", { class: "keys-grid" }, SHORTCUTS.map(([k, d]) => h("div", { class: "keys-row" }, [h("span", {}, d), h("kbd", {}, k)]))));
  openPanel($("#keys-panel"), $("#keys-close"));
}

function focusResult(step) {
  const cards = $$(".result", els.main);
  if (!cards.length) return;
  const current = cards.indexOf(document.activeElement.closest ? document.activeElement.closest(".result") : null);
  const next = cards[Math.max(0, Math.min(cards.length - 1, current === -1 ? (step > 0 ? 0 : cards.length - 1) : current + step))];
  next.focus({ preventScroll: true });
  scrollToTarget(next, { offset: 190, duration: 0.7 });
}

function onKey(e) {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = document.activeElement ? document.activeElement.tagName : "";
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
  if (document.querySelector(".drawer.is-open")) return;
  const key = e.key;
  if (key === "/") { e.preventDefault(); focusQuery(); return; }
  if (key === "?") { e.preventDefault(); showShortcuts(); return; }
  if (els.workspace.hidden || !state.data) return;
  const card = document.activeElement.closest ? document.activeElement.closest(".result") : null;
  if (key === "j") { e.preventDefault(); focusResult(1); }
  else if (key === "k") { e.preventDefault(); focusResult(-1); }
  else if (key === "Enter" && card && document.activeElement === card) { e.preventDefault(); $(".result-title .linklike", card).click(); }
  else if (key === "e" && card) { e.preventDefault(); const all = $$("details.fold", card); const open = all.some((d) => d.open); all.forEach((d) => { d.open = !open; }); }
  else if (key === "c" && card) { e.preventDefault(); copyId(card.dataset.doc); }
  else if (key === "1" || key === "2" || key === "3") { e.preventDefault(); setConfig(["b0", "b1", "full"][Number(key) - 1]); }
  else if (key === "m") { e.preventDefault(); setMode(state.mode === "ranked" ? "compare" : "ranked"); }
  else if (key === "f" && state.mode === "ranked") { e.preventDefault(); toggleOnlyLowered(); }
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
  reveal(els.suggest, true);
  els.q.setAttribute("aria-expanded", "true");
}

function closeSuggest() {
  reveal(els.suggest, false);
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
  scrollToTarget("#top", { offset: 0, duration: 0.9 });
  window.setTimeout(() => els.q.focus({ preventScroll: true }), 500);
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
    stub: $("#ws-stub"), error: $("#ws-error"), statutes: $("#statutes"), main: $("#ws-main"), k: $("#kk"),
    onlyLowered: $("#only-lowered"), expandAll: $("#expand-all"),
  });
  els.suggest.classList.add("anim-pop");
  els.form.addEventListener("submit", (e) => { e.preventDefault(); closeSuggest(); state.mode = "ranked"; run(); });
  els.btnCompare.addEventListener("click", () => { closeSuggest(); state.mode = "compare"; run(); });
  $$("#mode .seg-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $$("#ladder button").forEach((b) => b.addEventListener("click", () => setConfig(b.dataset.config)));
  els.onlyLowered.addEventListener("click", toggleOnlyLowered);
  els.expandAll.addEventListener("click", toggleExpandAll);
  $("#shortcuts-btn").addEventListener("click", showShortcuts);
  els.k.addEventListener("change", () => { if (state.query) run({ scroll: false }); });
  window.addEventListener("resize", () => moveThumb(false));
  els.q.addEventListener("focus", () => { if (!state.examples) api.examples().then((x) => { state.examples = x; if (document.activeElement === els.q) renderSuggest(); }).catch(() => { state.examples = { queries: [] }; }); renderSuggest(); });
  els.q.addEventListener("input", renderSuggest);
  els.q.addEventListener("blur", () => window.setTimeout(closeSuggest, 140));
  els.q.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); if (els.suggest.hidden) renderSuggest(); moveActive(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); moveActive(-1); }
    else if (e.key === "Escape") closeSuggest();
    else if (e.key === "Enter" && activeIndex >= 0) { e.preventDefault(); pick(items[activeIndex].row); }
  });
  document.addEventListener("keydown", onKey);
  syncControls(false);
}
