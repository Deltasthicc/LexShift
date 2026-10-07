// The Statutes page (M2): how a query is read by parse_query(), which code governs on the offence date, how much continuity() gives
// each top result, and the mapping table those numbers come from.
//
// The query runs through /api/compare, so the continuity scores and the rank changes are exactly the ones the ranking uses. The table is
// M2's statute_map.csv as it is on disk (/api/modules). Everything is inserted as text.
import { api } from "./api.js";
import { $, clear, f2, h } from "./dom.js";
import { animateIn } from "./motion.js";
import { currentQuery, reasonOf } from "./search.js";

const PRESETS = [
  { q: "BNS 103", date: "2025-01-10" },
  { q: "IPC 302", date: "2020-01-01" },
  { q: "BNS 318", date: "2025-03-01" },
  { q: "murder", date: "" },
];
const OLD = new Set(["IPC", "CRPC"]);
const NEW = new Set(["BNS", "BNSS"]);
const st = { modules: null, built: false, seenSearch: "", seq: 0, refs: [] };

function timeline(act, date) {
  const box = $("#st-timeline");
  const from = st.modules ? st.modules.m2.commencement : null;
  const code = String(act || "").toUpperCase();
  const old = OLD.has(code) || (!code && date && from && date < from);
  const nu = NEW.has(code) || (!code && date && from && date >= from);
  box.replaceChildren(
    h("div", { class: `tl-side${old ? " is-on" : ""}` }, h("b", {}, "IPC · CrPC"), h("span", {}, "offences before the change")),
    h("span", { class: "tl-mid" }, from ? `in force ${from}` : "changeover"),
    h("div", { class: `tl-side${nu ? " is-on" : ""}` }, h("b", {}, "BNS · BNSS"), h("span", {}, "offences on or after it")),
  );
}

function renderRead(data) {
  const box = $("#st-read");
  clear(box);
  const s = data.statutes;
  const stub = data.configs.b1.stubbed.includes("cont");
  if (stub) box.appendChild(h("div", { class: "callout callout-warn" }, "Stub mode: the statute module is a fixed-value stand-in, so this is not M2's reading."));
  if (!s || s.used === false) { box.appendChild(h("p", { class: "note" }, "This ranking does not use statutes.")); return; }
  if (s.error) { box.appendChild(h("p", { class: "note" }, `The statute module could not read it: ${s.error}`)); return; }
  st.refs = s.refs || [];
  box.appendChild(h("div", { class: "kv" }, [
    h("div", { class: "kv-row" }, [h("span", {}, "Governing code"), h("span", { class: "big" }, s.governing_act || "not determined")]),
    h("div", { class: "kv-row" }, [h("span", {}, "Decided by"), h("span", {}, s.governing_act ? (data.offence_date ? `offence date ${data.offence_date}` : "the code named in the query") : "no code named and no offence date")]),
    h("div", { class: "kv-row" }, [h("span", {}, "Sections found"), s.refs.length
      ? h("span", { class: "refs" }, s.refs.map((r) => h("span", { class: "ref" }, r.section === "PROSE" ? "from the words" : `${r.act} ${r.section}`, r.offence_id ? h("span", { class: "tag" }, r.offence_id) : null)))
      : h("span", {}, "none")]),
    ...(s.notes || []).map((n) => h("div", { class: "kv-row" }, [h("span", {}, "Note"), h("span", {}, n)])),
  ]));
  timeline(s.governing_act, data.offence_date);
}

function renderContinuity(data) {
  const box = $("#st-cont");
  clear(box);
  const block = data.configs.b1;
  if (!block.signals_used.includes("cont")) { box.appendChild(h("p", { class: "note" }, "B1 does not use continuity in the current configuration.")); return; }
  box.appendChild(h("p", { class: "note" }, "Ranked by BM25 + continuity. The arrow is the change against BM25 alone."));
  block.results.slice(0, 6).forEach((r) => {
    const b0 = r.ranks ? r.ranks.b0 : null;
    const moved = b0 != null && b0 !== r.rank ? ` · #${b0} → #${r.rank}` : "";
    box.appendChild(h("div", { class: "cont-row" }, [
      h("span", { class: "t", title: r.title || r.doc_id }, `${r.rank}. ${r.title || r.doc_id}`),
      h("span", { class: "bar", dataset: { tip: `continuity ${f2(r.cont)}` } }, h("i", { vars: { "--w": `${Math.round((r.cont || 0) * 100)}%` } })),
      h("span", { class: "why" }, `continuity ${f2(r.cont)}${moved}  ·  ${reasonOf(r, "cont") || "no reason given"}`),
    ]));
  });
  animateIn(box.children, { y: 6, stagger: 0.03 });
}

function renderMap() {
  const m2 = st.modules ? st.modules.m2 : null;
  const body = $("#st-map tbody");
  const chips = $("#st-weights");
  clear(body);
  clear(chips);
  if (!m2 || !m2.available) { body.appendChild(h("tr", {}, h("td", { colspan: "5" }, "statute_map.csv is missing."))); return; }
  Object.entries(m2.relation_weights).forEach(([rel, w]) => chips.appendChild(h("span", { class: "tag" }, `${rel.replace(/_/g, " ")} ${f2(Number(w))}`)));
  const hit = (act, sec) => st.refs.some((r) => String(r.act).toUpperCase() === act.toUpperCase() && String(r.section).toUpperCase() === sec.toUpperCase());
  const rows = m2.map.map((r) => ({ r, on: hit(r.old_act, r.old_section) || hit(r.new_act, r.new_section) }));
  rows.sort((a, b) => Number(b.on) - Number(a.on));
  rows.forEach(({ r, on }) => body.appendChild(h("tr", { class: on ? "is-hit" : null }, [
    h("td", {}, `${r.old_act} ${r.old_section}`), h("td", {}, `${r.new_act} ${r.new_section}`), h("td", {}, r.relation.replace(/_/g, " ")),
    h("td", { class: "num" }, r.weight), h("td", {}, r.note),
  ])));
}

async function run(q, date) {
  $("#st-q").value = q;
  $("#st-date").value = date || "";
  const seq = ++st.seq;
  $("#st-read").replaceChildren(h("div", { class: "skeleton" }));
  $("#st-cont").replaceChildren(h("div", { class: "skeleton" }));
  try {
    const data = await api.compare(q, date, 8);
    if (seq !== st.seq) return;
    renderRead(data);
    renderContinuity(data);
    renderMap();
  } catch (err) {
    if (seq !== st.seq) return;
    $("#st-read").replaceChildren(h("div", { class: "callout callout-error" }, err.message));
    clear($("#st-cont"));
  }
}

export async function renderStatutesPage() {
  if (!st.built) {
    st.built = true;
    const chips = $("#st-presets");
    PRESETS.forEach((p) => chips.appendChild(h("button", { class: "chip-btn", type: "button", onclick: () => run(p.q, p.date) }, [p.q, p.date ? h("small", {}, p.date) : null])));
    $("#st-form").addEventListener("submit", (e) => { e.preventDefault(); run($("#st-q").value.trim(), $("#st-date").value); });
    try { st.modules = await api.modules(); } catch (err) { st.modules = null; }
    timeline(null, $("#st-date").value);
  }
  const shared = currentQuery();
  const key = shared ? `${shared.q}|${shared.date}` : "";
  if (shared && key !== st.seenSearch) { st.seenSearch = key; await run(shared.q, shared.date); }
  else if (st.seq === 0) await run($("#st-q").value.trim(), $("#st-date").value);
}
