// The Treatment page (M3): the citation pipeline stage by stage (find, resolve, window, classify, score), each with numbers read from
// M3's files on disk (/api/modules), and, for a query, each result's health, authority and the sentences behind them (/api/search).
//
// A piece of M3's list that is not done yet is marked so, not described as if it worked. Nothing is inserted as markup.
import { api } from "./api.js";
import { $, $$, clear, f2, h, show } from "./dom.js";
import { animateIn } from "./motion.js";
import { currentQuery, evidenceList } from "./search.js";
import { openReader } from "./reader.js";

const NEGATIVE = ["overruled", "doubted"]; // common.schema.NEGATIVE_LABELS
const LABEL_COLOUR = { overruled: "var(--st-over)", doubted: "var(--st-doubt)", followed: "var(--st-follow)" };
const KINDS = {
  full: ["Full citation", "Bachan Singh v. State of Punjab (1980) 2 SCC 684", "var(--c-rel)"],
  cite: ["Reporter citation only", "(2014) 1 SCC 1 : [2013] 17 SCR 116", "var(--c-cont)"],
  name: ["Case name only", "Suresh Kumar Koushal v. Naz Foundation", "var(--c-auth)"],
  supra: ["Back-reference", "Koushal (supra)", "var(--c-health)"],
  alias: ["Later short form", "The decision in Koushal stands overruled.", "var(--st-neutral)"],
};
const METHOD = {
  cite: ["By reporter citation", "var(--c-health)"],
  name: ["By party name and year", "var(--c-cont)"],
  none: ["Not in this corpus", "var(--line)"],
};
const st = { built: false, seenSearch: "", seq: 0, tab: "extract" };
const num = (n) => (typeof n === "number" ? n.toLocaleString("en-IN") : "n/a");

// ----------------------------------------------------------------------------------------------------------------- M3's list
// state: live = shown working on this page; shown = explained with real numbers; built = in the code and tested, no number on
// this page; missing = not done yet (from m3_treatment/README.md).
function stages(m3) {
  const gold = m3.gold || { sheets: [] };
  const sheetRows = gold.sheets.reduce((a, s) => a + s.rows, 0);
  const labelled = gold.sheets.reduce((a, s) => a + s.labelled, 0);
  const shot = gold.gold_rows ? "few-shot" : "zero-shot";
  return [
    { key: "extract", name: "Find", panel: "#tr-extract", blurb: "Every reference to an earlier case is found in the cleaned text, including the short forms judgments use to state treatment.", items: [
      { name: "Case-citation extractor", state: "live", note: "SCR, SCC, SCC OnLine, AIR and neutral (INSC) citations, and \"X v. Y\" case names." },
      { name: "Short forms (supra, alias)", state: "live", note: "\"Koushal (supra)\" and later uses of a name point back to the full mention and inherit its resolution." },
      { name: "Text cleaning", state: "built", note: "Margin letters and running page heads are removed before extraction." },
    ] },
    { key: "resolve", name: "Resolve", panel: "#tr-resolve", blurb: "Each mention is linked to a judgment in the corpus: reporter citation first, then SCR page range, then party-name Jaccard with the year.", items: [
      { name: "Resolver", state: "live", note: "Reporter key, then SCR page range with a name check, then Jaccard on party-name tokens plus year." },
      { name: "Unresolved kept, never dropped", state: "live", note: "A mention that matches no judgment is kept with cited_doc = null and counted." },
    ] },
    { key: "window", name: "Window", panel: "#tr-window", blurb: "The citing sentence and one sentence either side, with the cited case marked, is what gets classified.", items: [
      { name: "Citation windows", state: "live", note: "Sentence +/- 1, at most 1500 characters, target marked [[ ]]." },
      { name: "Appeal-history filter", state: "shown", note: "If the cited case is the judgment under appeal, it is a reversal, not an overruling, and is excluded." },
      { name: "Self-citation filter", state: "shown", note: "A judgment's own reporter line is not a citation of an earlier case." },
    ] },
    { key: "classify", name: "Classify", panel: "#tr-classify", blurb: "Each resolved window is labelled followed, distinguished, doubted, overruled or neutral, offline, and every answer is cached.", items: [
      { name: "LLM classifier (Gemini)", state: "shown", note: `${m3.model || "model not set"}, ${shot}, run offline; answers are cached so the demo never calls a model.` },
      { name: "Baseline: tf-idf + logistic regression", state: "built", note: "The comparison classifier, evaluated on the same gold set." },
      { name: "Gold-set tooling", state: "built", note: "Cue-stratified sampler, labelling sheets, merge, adjudication, Cohen's kappa." },
      { name: "Gold-set sheets for two labellers", state: "shown", note: `${num(sheetRows)} sheet rows; ${num(labelled)} labelled by people so far.` },
      { name: "Classifier evaluation (per-class F1)", state: gold.f1_report ? "shown" : "built", note: "make m3-evaluate scores the LLM and the baseline against the hand-labelled gold set." },
      { name: "Bench check", state: "live", note: "A negative label counts only if the citing bench is at least as large as the cited bench." },
    ] },
    { key: "scores", name: "Score", panel: "#tr-scores", blurb: "Health from the strongest valid negative; authority from PageRank over the citation graph. Both are read by the ranking at query time.", items: [
      { name: "health(d)", state: "live", note: "Strongest valid negative treatment: overruled 0.1, doubted 0.6, otherwise 1.0." },
      { name: "authority(d) by PageRank", state: "live", note: "Own power iteration over followed and neutral edges, times a bench-size weight, normalised." },
      { name: "Point-level health (stretch)", state: "built", note: "A negative lowers health only for queries on the offence the overruling discusses (M2's offence ids)." },
    ] },
  ];
}
const STATE_LABEL = { live: "live on this page", shown: "explained with real numbers", built: "in the code and tested", missing: "not done yet" };

// ----------------------------------------------------------------------------------------------------------------- builders
function tile(k, v, d) {
  return h("div", { class: "tile" }, h("span", { class: "k" }, k), h("span", { class: "v" }, typeof v === "number" ? num(v) : v), d ? h("span", { class: "d" }, d) : null);
}

/** Fill a proportion bar and return its legend. */
function bar(box, parts, total) {
  box.replaceChildren(...parts.filter((p) => p.n > 0).map((p) => h("span", { vars: { "--w": `${((p.n / Math.max(1, total)) * 100).toFixed(2)}%`, "--st": p.colour }, dataset: { tip: `${p.label}: ${num(p.n)}` } })));
  return h("ul", { class: "legend" }, parts.map((p) => h("li", {}, h("i", { class: "legend-dot", vars: { "--sig": p.colour }, "aria-hidden": "true" }), `${p.label} ${num(p.n)}`)));
}

const kv = (rows) => h("div", { class: "kv" }, rows.filter(Boolean).map(([k, v]) => h("div", { class: "kv-row" }, [h("span", {}, k), h("span", {}, v)])));

/** The window text with the [[cited case]] marked. */
function marked(window) {
  return String(window).split(/(\[\[.*?\]\])/).map((piece) => (piece.startsWith("[[") ? h("mark", {}, piece.slice(2, -2)) : piece));
}

// ----------------------------------------------------------------------------------------------------------------- the stages
function renderExtract(m3) {
  const s = m3.stages;
  if (!s) { $("#tr-extract-body").replaceChildren(h("p", { class: "note" }, "m3_mentions.jsonl is missing: run python -m m3_treatment.pipeline extract.")); return; }
  bar($("#tr-kinds"), Object.keys(KINDS).map((k) => ({ label: KINDS[k][0], n: s.kinds[k] || 0, colour: KINDS[k][2] })), s.total);
  $("#tr-extract-body").replaceChildren(
    h("div", { class: "table-wrap" }, h("table", { class: "table" }, [
      h("thead", {}, h("tr", {}, [h("th", {}, "Kind"), h("th", {}, "Looks like"), h("th", { class: "num" }, "Found")])),
      h("tbody", {}, Object.keys(KINDS).map((k) => h("tr", {}, [
        h("td", {}, h("span", { class: "sig-name" }, [h("span", { class: "legend-dot", vars: { "--sig": KINDS[k][2] } }), KINDS[k][0]])),
        h("td", { class: "reason" }, KINDS[k][1]), h("td", { class: "num" }, num(s.kinds[k] || 0)),
      ]))),
    ])),
    kv([
      ["Mentions found", num(s.total)],
      ["References to the judgment itself, dropped", num(s.self)],
      ["Citations kept", `${num(m3.mentions)} in ${num(m3.citing_judgments)} judgments`],
    ]),
  );
}

/** The corpus holds 2024 and 2025 judgments: say how many unresolved citations name an earlier year. */
function unresolvedWhy(y) {
  const dated = (y["before 2024"] || 0) + (y["2024 or later"] || 0);
  if (!dated) return null;
  return ["Why so few", `the corpus holds 2024 and 2025 judgments only; ${Math.round(((y["before 2024"] || 0) / dated) * 100)}% of the unresolved citations that carry a year (${num(y["before 2024"] || 0)} of ${num(dated)}) cite an earlier one`];
}

function renderResolve(m3) {
  const s = m3.stages;
  if (!s) return;
  const legend = bar($("#tr-resolution"), Object.keys(METHOD).map((k) => ({ label: METHOD[k][0], n: s.resolution[k] || 0, colour: METHOD[k][1] })), m3.mentions);
  const checks = Object.entries(s.check || {}).map(([method, c]) => {
    const checked = (c.match || 0) + (c.mismatch || 0);
    if (!checked) return null;
    return h("p", { class: `verdict ${(c.match || 0) / checked >= 0.9 ? "is-ok" : "is-bad"}` },
      `${METHOD[method] ? METHOD[method][0] : method}: ${num(c.match || 0)} of ${num(checked)} checkable links point to the judgment whose SCR citation the text gives.`);
  }).filter(Boolean);
  $("#tr-resolve-body").replaceChildren(
    legend,
    kv([
      ["Resolved", `${num(m3.resolved)} of ${num(m3.mentions)} (${((m3.resolved / Math.max(1, m3.mentions)) * 100).toFixed(1)}%)`],
      unresolvedWhy(m3.unresolved_years || {}),
    ]),
    h("h3", { class: "sub-h" }, "Spot check of the links"),
    ...checks,
    h("p", { class: "note" }, "Checked on this page against the reporter citations M1 extracted. Mentions without an SCR citation in their text cannot be checked this way."),
  );
}

function renderWindow(m3) {
  const ex = m3.example;
  const w = m3.window || {};
  $("#tr-window-body").replaceChildren(
    ex ? h("div", { class: "example" }, [
      h("div", { class: "evidence-head" }, [
        h("span", { class: `chip st-${ex.label}` }, ex.label),
        h("span", {}, `confidence ${f2(ex.confidence)}`),
        ex.citing_bench ? h("span", {}, `${ex.citing_bench}-judge bench cites a ${ex.cited_bench || "?"}-judge bench`) : null,
      ]),
      h("blockquote", { class: "example-window" }, marked(ex.window)),
      h("p", { class: "note" }, [
        h("button", { class: "linklike", type: "button", onclick: () => openReader(ex.citing_doc, ex.citing_title || "", "", { passage: ex.window.replace(/\[\[|\]\]/g, "") }) }, ex.citing_title || ex.citing_doc),
        "  cites  ",
        h("button", { class: "linklike", type: "button", onclick: () => openReader(ex.cited_doc, ex.cited_title || "", "") }, ex.cited_title || ex.cited_doc),
      ]),
    ]) : h("p", { class: "note" }, "No example window: citations.jsonl has no resolved, followed citation."),
    kv([
      ["Window", `the citing sentence, ${w.before ?? 1} before and ${w.after ?? 1} after, at most ${num(w.max_chars || 1500)} characters`],
      ["Appeal history, excluded", `${num(m3.appeal_history)}: a reversal on appeal is not an overruling of a precedent`],
      m3.stages ? ["Citations inside a headnote", num(m3.stages.in_headnote)] : null,
    ]),
  );
}

function renderClassify(m3) {
  const labels = m3.labels || {};
  const legend = bar($("#tr-labels"), Object.entries(labels).map(([label, n]) => ({ label, n, colour: LABEL_COLOUR[label] || "var(--st-neutral)" })), m3.resolved);
  const negative = NEGATIVE.reduce((a, l) => a + (labels[l] || 0), 0);
  const gold = m3.gold || { sheets: [] };
  const conf = Object.entries(m3.confidence || {}).map(([k, n]) => `${k}: ${num(n)}`).join("  ·  ");
  $("#tr-classify-body").replaceChildren(
    legend,
    kv([
      ["Classified", `${num(m3.resolved)} resolved windows (only those can move a score)`],
      ["Labels from", `${m3.label_source === "llm" ? `Gemini (${m3.model}), ${(m3.gold || {}).gold_rows ? "few-shot" : "zero-shot"}` : m3.label_source || "unknown"}, run offline, every answer cached`],
      ["Confidence", conf || "n/a"],
      ["Negative labels", `${num(negative)} (overruled or doubted)`],
      ["Gold set", gold.sheets.length
        ? `${gold.sheets.map((s) => `${s.file}: ${num(s.labelled)} of ${num(s.rows)} labelled`).join(", ")}; ${num(gold.gold_rows)} merged rows`
        : `${num(gold.gold_rows)} merged rows`],
      ["Evaluation", gold.f1_report ? "reports/classifier_f1.md" : "make m3-evaluate scores the classifiers against the labelled gold set"],
    ]),
  );
}

function renderScores(m3) {
  const hv = m3.health_values || {};
  $("#tr-rules").replaceChildren(h("div", { class: "rules" }, [
    h("div", { class: "rule-row" }, [h("span", { class: "num" }, f2(hv.overruled)), h("span", { class: "chip st-overruled" }, "overruled")]),
    h("div", { class: "rule-row" }, [h("span", { class: "num" }, f2(hv.doubted)), h("span", { class: "chip st-doubted" }, "doubted")]),
    h("div", { class: "rule-row" }, [h("span", { class: "num" }, f2(hv.default)), h("span", { class: "chip st-followed" }, "otherwise")]),
    h("p", { class: "note" }, `Health takes the strongest valid negative: from a citing bench at least as large, with confidence at least ${f2(m3.min_confidence)}.`),
    h("p", { class: "note" }, `Authority: PageRank (damping ${f2(m3.damping)}) over followed and neutral citations, times a bench-size weight.`),
    m3.judgments && m3.lowered === 0 ? h("p", { class: "callout callout-info" }, `No valid negative treatment was found in this corpus, so health is 1.00 for all ${num(m3.judgments)} judgments. Authority still separates them.`) : null,
  ]));
  const top = $("#tr-top");
  clear(top);
  m3.top_authority.forEach((r) => top.appendChild(h("li", {}, [
    h("button", { class: "linklike t", type: "button", title: r.title || r.doc_id, onclick: () => openReader(r.doc_id, r.title || "", "") }, r.title || r.doc_id),
    h("span", { class: "bar sig-auth" }, h("i", { vars: { "--w": `${Math.round(r.authority * 100)}%` } })),
    h("span", { class: "num" }, f2(r.authority)),
  ])));
  if (!m3.top_authority.length) top.appendChild(h("li", {}, h("span", { class: "note" }, "doc_health.jsonl is missing.")));
}

function fillChecklist(stage) {
  const box = $(`${stage.panel} .checklist`);
  clear(box);
  stage.items.forEach((item) => box.appendChild(h("span", { class: `check s-${item.state}`, tabindex: "0", dataset: { tip: `${STATE_LABEL[item.state]}. ${item.note}` } },
    h("i", { "aria-hidden": "true" }), item.name, item.state === "missing" ? " (not done yet)" : null)));
}

// ----------------------------------------------------------------------------------------------------------------- tabs
function buildTabs(list) {
  const tabs = $("#tr-tabs");
  clear(tabs);
  list.forEach((stage, i) => {
    const tab = h("button", { class: "tab", type: "button", role: "tab", "aria-selected": "false", "aria-controls": stage.panel.slice(1), dataset: { stage: stage.key } }, h("span", { class: "n" }, String(i + 1)), stage.name);
    tab.addEventListener("click", () => selectTab(list, stage.key));
    tabs.appendChild(tab);
    const panel = $(stage.panel);
    if (!$(".panel-blurb", panel)) panel.prepend(h("p", { class: "note panel-blurb" }, stage.blurb));
    fillChecklist(stage);
  });
  tabs.addEventListener("keydown", (e) => {
    const i = list.findIndex((s) => s.key === st.tab);
    if (e.key === "ArrowRight") { e.preventDefault(); selectTab(list, list[(i + 1) % list.length].key, true); }
    if (e.key === "ArrowLeft") { e.preventDefault(); selectTab(list, list[(i + list.length - 1) % list.length].key, true); }
  });
}

function selectTab(list, key, focus = false) {
  st.tab = key;
  $$("#tr-tabs .tab").forEach((t) => {
    const on = t.dataset.stage === key;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    if (on && focus) t.focus();
  });
  list.forEach((s) => show($(s.panel), s.key === key));
  animateIn($(list.find((s) => s.key === key).panel), { y: 6 });
}

// ----------------------------------------------------------------------------------------------------------------- a query
async function run(q, date) {
  $("#tr-q").value = q;
  $("#tr-date").value = date || "";
  const seq = ++st.seq;
  const out = $("#tr-results");
  out.replaceChildren(h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
  try {
    const data = await api.search(q, date, 8, "full");
    if (seq !== st.seq) return;
    const stubH = data.stubbed.includes("health");
    const stubA = data.stubbed.includes("auth");
    const list = h("div", {}, [
      h("h3", { class: "sub-h" }, `Top results for ${data.query}`),
      stubH || stubA ? h("div", { class: "callout callout-warn" }, "Stub mode: treatment or authority is a fixed-value stand-in, so this is not M3's output.") : null,
      ...data.results.map((r) => h("div", { class: "tr-item" }, [
        h("div", { class: "tr-top" }, [
          h("button", { class: "linklike result-title", type: "button", onclick: () => openReader(r.doc_id, r.title || "", data.query) }, `${r.rank}. ${r.title || r.doc_id}`),
          h("span", { class: "tr-scores" }, [
            h("span", { class: `chip ${r.health < 0.999 ? "st-lowered" : "st-clear"}` }, `health ${f2(r.health)}`),
            h("span", { class: "sig-auth", dataset: { tip: "M3's authority; the ranking rescales it over the candidates" } }, ["authority ", f2(r.raw.auth)]),
            h("span", { class: "bar sig-auth" }, h("i", { vars: { "--w": `${Math.round((r.raw.auth || 0) * 100)}%` } })),
          ]),
        ]),
        (r.evidence || []).length ? evidenceList(r, stubH, data.query) : h("p", { class: "note" }, "No later judgment in the corpus was found treating this one."),
      ])),
    ]);
    out.replaceChildren(list);
    animateIn(list, { y: 6 });
  } catch (err) {
    if (seq !== st.seq) return;
    out.replaceChildren(h("div", { class: "callout callout-error" }, err.message));
  }
}

// ----------------------------------------------------------------------------------------------------------------- entry
export async function renderTreatmentPage() {
  if (!st.built) {
    st.built = true;
    $("#tr-form").addEventListener("submit", (e) => { e.preventDefault(); run($("#tr-q").value.trim(), $("#tr-date").value); });
    try {
      const m3 = (await api.modules()).m3;
      const tiles = $("#tr-tiles");
      clear(tiles);
      if (!m3.citations_available) tiles.appendChild(h("div", { class: "callout callout-warn" }, "citations.jsonl is missing: M3's pipeline has not been run here."));
      tiles.append(
        tile("Citations found", m3.mentions, `in ${num(m3.citing_judgments)} judgments`),
        tile("Resolved", m3.resolved, "linked to a judgment in this corpus"),
        tile("Followed", (m3.labels || {}).followed || 0, `of the ${num(m3.resolved)} classified`),
        tile("Health lowered", `${num(m3.lowered)} / ${num(m3.judgments)}`, `${num(m3.with_evidence)} judgments carry evidence`),
      );
      const list = stages(m3);
      buildTabs(list);
      renderExtract(m3);
      renderResolve(m3);
      renderWindow(m3);
      renderClassify(m3);
      renderScores(m3);
      const asked = new URLSearchParams(window.location.hash.split("?")[1] || "").get("tab"); // e.g. #/treatment?tab=resolve
      selectTab(list, list.some((s) => s.key === asked) ? asked : "extract");
      show($("#tr-error"), false);
    } catch (err) {
      $("#tr-error").textContent = err.message;
      show($("#tr-error"), true);
    }
  }
  const shared = currentQuery();
  const key = shared ? `${shared.q}|${shared.date}` : "";
  if (shared && key !== st.seenSearch) { st.seenSearch = key; await run(shared.q, shared.date); }
  else if (st.seq === 0) await run($("#tr-q").value.trim(), $("#tr-date").value);
}
