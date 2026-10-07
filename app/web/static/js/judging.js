// The judging workbench. Two judges grade the same blind sheet independently; each click is saved to that judge's own file
// (eval/judging/<round>/judge1.csv or judge2.csv), which `python -m eval.make_qrels` then reads. The page never shows scores, ranks,
// system names or the other judge's grades, and it never suggests a grade.
//
// Flow: press 0, 1 or 2 on a focused document (or click), and with "move on after grading" the next ungraded document takes focus and
// scrolls into view. j and k move between documents, n jumps to the next ungraded one.
import { api } from "./api.js";
import { $, $$, clear, debounce, formatDate, h, plural, store } from "./dom.js";
import { animateIn, scrollToTarget } from "./motion.js";
import { openReader } from "./reader.js";
import { toast } from "./ui.js";

const GRADE_TEXT = {
  2: "Relevant and good law for this query and date.",
  1: "Relevant, but the law materially changed, or the precedent was criticised or doubted.",
  0: "Irrelevant, or overruled on the queried point.",
};
const KEY = "lexshift.judge";
const ADVANCE_KEY = "lexshift.judge.advance";

const st = { rounds: [], round: null, judge: "judge1", sheet: null, q: 0, advance: true };
let body;
let keysBound = false;

function emptyRounds(info) {
  return h("div", { class: "empty" }, [
    h("strong", {}, "No judging round yet"),
    "A round is built from the top 20 of every system, shuffled and stripped of scores: ",
    h("span", { class: "code" }, "python -m eval.pool --split all --round round1"),
    ". It needs the hand-made queries in ", h("span", { class: "code" }, "eval/queries.jsonl"),
    " and the real modules switched on; the tool refuses stand-ins on purpose. Rounds are read from ",
    h("span", { class: "code" }, (info && info.judging_dir) || "eval/judging"), ".",
  ]);
}

function progressNode() {
  return h("div", { class: "progress-line" }, [
    h("span", { id: "judge-progress-text" }, "Loading"),
    h("div", { class: "meter", id: "judge-progress-meter" }, h("i")),
  ]);
}

function setProgress(p) {
  st.sheet.progress = p;
  const text = $("#judge-progress-text");
  const meter = $("#judge-progress-meter");
  if (text) text.textContent = `${p.graded} of ${plural(p.total, "document")} graded`;
  if (meter) {
    meter.classList.toggle("is-done", p.graded === p.total && p.total > 0);
    meter.firstChild.style.setProperty("--w", String(p.total ? p.graded / p.total : 0));
  }
}

const cards = () => $$(".jdoc", $("#judge-docs") || document);

function focusCard(card) {
  if (!card) return;
  card.focus({ preventScroll: true });
  scrollToTarget(card, { offset: 230, duration: 0.8 });
}

function nextUngraded(fromCard) {
  const list = cards();
  const start = fromCard ? list.indexOf(fromCard) + 1 : 0;
  return list.slice(start).find((c) => !c.classList.contains("is-graded")) || list.find((c) => !c.classList.contains("is-graded") && c !== fromCard) || null;
}

async function save(doc, query, card, state, grade, note) {
  state.className = "save-state";
  state.textContent = "Saving";
  try {
    const res = await api.judgeGrade({ round: st.round, judge: st.judge, qid: query.qid, doc_id: doc.doc_id, grade, note });
    doc.grade = res.grade;
    doc.note = note;
    card.classList.toggle("is-graded", res.grade !== null);
    state.className = "save-state is-ok";
    state.textContent = "Saved";
    setProgress(res.progress);
    renderQueryList();
    return true;
  } catch (err) {
    state.className = "save-state is-error";
    state.textContent = `Not saved: ${err.message}`;
    toast(`Grade not saved: ${err.message}`, "error", 6000);
    return false;
  }
}

function docCard(doc, query) {
  const state = h("span", { class: "save-state", "aria-live": "polite" });
  const note = h("textarea", { class: "note-input", rows: 2, maxlength: 1000, placeholder: "Why this grade? For an overruled case, name the overruling judgment.", "aria-label": `Note for ${doc.title || doc.doc_id}` });
  note.value = doc.note || "";
  const buttons = [0, 1, 2].map((g) => h("button", { class: `grade-btn${doc.grade === g ? " is-on" : ""}`, type: "button", "aria-pressed": String(doc.grade === g), dataset: { tip: GRADE_TEXT[g] } }, String(g)));
  const card = h("article", { class: `jdoc${doc.grade !== null ? " is-graded" : ""}`, tabindex: "0", dataset: { doc: doc.doc_id } }, [
    h("div", {}, [
      h("h3", {}, doc.title || doc.doc_id),
      h("p", { class: "result-meta" }, [h("span", { class: "mono" }, doc.doc_id), doc.date ? h("span", {}, formatDate(doc.date)) : null, doc.bench_size ? h("span", {}, `${doc.bench_size}-judge bench`) : null]),
    ]),
    h("p", { class: "excerpt" }, doc.excerpt || "No excerpt in the sheet."),
    h("div", { class: "grade-row", role: "group", "aria-label": "Grade" }, [
      ...buttons,
      h("span", { class: "grade-hint" }, ["or press ", h("span", { class: "kbd" }, "0"), " ", h("span", { class: "kbd" }, "1"), " ", h("span", { class: "kbd" }, "2")]),
      h("button", { class: "btn btn-secondary btn-small", type: "button", onclick: () => openReader(doc.doc_id, doc.title || "", query.query) }, "Read judgment"),
    ]),
    note,
    state,
  ]);
  const setGrade = async (g) => {
    const next = doc.grade === g ? null : g;
    buttons.forEach((b, i) => { b.classList.toggle("is-on", i === next); b.setAttribute("aria-pressed", String(i === next)); });
    const ok = await save(doc, query, card, state, next, note.value);
    if (ok && next !== null && st.advance) {
      const target = nextUngraded(card);
      if (target) focusCard(target);
      else toast("Every document in this query is graded", "ok");
    }
  };
  buttons.forEach((b, i) => b.addEventListener("click", () => setGrade(i)));
  card.addEventListener("keydown", (e) => {
    if (e.target === note || e.metaKey || e.ctrlKey || e.altKey) return;
    if (["0", "1", "2"].includes(e.key)) { e.preventDefault(); setGrade(Number(e.key)); }
  });
  const saveNote = debounce(() => save(doc, query, card, state, doc.grade, note.value), 700);
  note.addEventListener("input", saveNote);
  card.addEventListener("focusin", () => card.classList.add("is-focus"));
  card.addEventListener("focusout", () => card.classList.remove("is-focus"));
  return card;
}

function renderQueryList() {
  const list = $("#q-list");
  if (!list) return;
  clear(list);
  st.sheet.queries.forEach((q, i) => {
    const done = q.docs.filter((d) => d.grade !== null).length;
    list.appendChild(h("button", { class: `q-item${i === st.q ? " is-on" : ""}`, type: "button", onclick: () => { st.q = i; renderQueryList(); renderDocs(true); } }, [
      h("span", { class: "q-top" }, [h("span", {}, `${q.qid}  ·  type ${q.type || "?"}`), h("span", {}, `${done}/${q.docs.length}`)]),
      h("span", { class: "q-text" }, q.query),
    ]));
  });
}

function renderDocs(animate = false) {
  const box = $("#judge-docs");
  clear(box);
  const q = st.sheet.queries[st.q];
  if (!q) { box.appendChild(h("div", { class: "empty" }, "This sheet has no queries.")); return; }
  box.appendChild(h("div", { class: "judge-q" }, [
    h("h2", {}, q.query),
    h("p", {}, [q.offence_date ? `Offence date ${q.offence_date}. ` : "No offence date. ", `Grade each document for this query${q.offence_date ? " and this date" : ""}, by reading the judgment.`]),
  ]));
  q.docs.forEach((d) => box.appendChild(docCard(d, q)));
  const nextIndex = st.sheet.queries.findIndex((x, i) => i !== st.q && x.docs.some((d) => d.grade === null));
  box.appendChild(h("button", { class: "btn btn-secondary", type: "button", disabled: nextIndex === -1 ? "" : null, onclick: () => { st.q = nextIndex; renderQueryList(); renderDocs(true); scrollToTarget("#judge-area", { offset: 200 }); } }, nextIndex === -1 ? "Every other query is fully graded" : "Next query with ungraded documents"));
  if (animate) animateIn(Array.from(box.children), { y: 22, stagger: 0.05, duration: 0.6 });
}

async function loadSheet() {
  const area = $("#judge-area");
  clear(area);
  area.appendChild(h("div", { class: "skeleton" }));
  try {
    st.sheet = await api.judgeSheet(st.round, st.judge);
  } catch (err) {
    clear(area);
    area.appendChild(h("div", { class: "callout callout-error" }, err.message));
    return;
  }
  st.q = Math.max(0, st.sheet.queries.findIndex((q) => q.docs.some((d) => d.grade === null)));
  store.set(KEY, { round: st.round, judge: st.judge });
  clear(area);
  area.appendChild(h("div", { class: "judge-work" }, [h("nav", { class: "q-list", id: "q-list", "aria-label": "Queries" }), h("div", { class: "judge-docs", id: "judge-docs" })]));
  setProgress(st.sheet.progress);
  renderQueryList();
  renderDocs(true);
}

function onKey(e) {
  if (!$("#view-judging") || $("#view-judging").hidden || e.metaKey || e.ctrlKey || e.altKey) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  const list = cards();
  if (!list.length) return;
  const at = list.indexOf(document.activeElement.closest ? document.activeElement.closest(".jdoc") : null);
  if (e.key === "j") { e.preventDefault(); focusCard(list[Math.min(list.length - 1, at + 1)]); }
  else if (e.key === "k") { e.preventDefault(); focusCard(list[Math.max(0, at === -1 ? 0 : at - 1)]); }
  else if (e.key === "n") { e.preventDefault(); const t = nextUngraded(at === -1 ? null : list[at]); if (t) focusCard(t); else toast("Nothing left to grade in this query", "ok"); }
}

export async function renderJudging() {
  body = $("#judge-body");
  clear(body);
  body.appendChild(h("div", { class: "skeleton" }));
  let info;
  try {
    info = await api.judgeRounds();
  } catch (err) {
    clear(body);
    body.appendChild(h("div", { class: "callout callout-error" }, err.message));
    return;
  }
  st.rounds = info.rounds;
  clear(body);
  if (!st.rounds.length) { body.appendChild(emptyRounds(info)); animateIn(Array.from(body.children)); return; }
  if (!keysBound) { document.addEventListener("keydown", onKey); keysBound = true; }
  const remembered = store.get(KEY, {});
  st.round = st.rounds.find((r) => r.round === remembered.round) ? remembered.round : st.rounds[0].round;
  st.judge = remembered.judge === "judge2" ? "judge2" : "judge1";
  st.advance = store.get(ADVANCE_KEY, true) !== false;

  const roundSelect = h("select", { id: "round-select", "aria-label": "Round" }, st.rounds.map((r) => h("option", { value: r.round }, `${r.round}: ${plural(r.queries, "query", "queries")}, ${plural(r.rows, "document")}`)));
  roundSelect.value = st.round;
  roundSelect.addEventListener("change", () => { st.round = roundSelect.value; loadSheet(); });
  const judgeButtons = ["judge1", "judge2"].map((j) => h("button", { class: `seg-btn${st.judge === j ? " is-on" : ""}`, type: "button", "aria-pressed": String(st.judge === j), dataset: { judge: j } }, j === "judge1" ? "Judge 1" : "Judge 2"));
  judgeButtons.forEach((b) => b.addEventListener("click", () => {
    st.judge = b.dataset.judge;
    judgeButtons.forEach((x) => { const on = x.dataset.judge === st.judge; x.classList.toggle("is-on", on); x.setAttribute("aria-pressed", String(on)); });
    loadSheet();
  }));
  const advance = h("input", { type: "checkbox", id: "advance", checked: st.advance ? "" : null });
  advance.checked = st.advance;
  advance.addEventListener("change", () => { st.advance = advance.checked; store.set(ADVANCE_KEY, st.advance); });

  body.appendChild(h("div", { class: "judge-bar" }, [
    h("label", { class: "select", for: "round-select" }, [h("span", { class: "field-label" }, "Round"), roundSelect]),
    h("div", {}, [h("span", { class: "field-label" }, "You are"), h("div", { class: "segmented", role: "group", "aria-label": "Judge" }, judgeButtons)]),
    h("div", { class: "grow" }, [progressNode(), h("label", { class: "toggle-line", for: "advance" }, [advance, "Move on to the next ungraded document after grading"])]),
  ]));
  body.appendChild(h("div", { class: "scale" }, [2, 1, 0].map((g) => h("div", {}, [h("b", {}, String(g)), GRADE_TEXT[g]]))));
  body.appendChild(h("div", { class: "callout callout-info" }, [
    "Grade independently: do not look at the other judge's sheet or at what the system returns. Every click is saved to ",
    h("span", { class: "code" }, "judge1.csv"), " or ", h("span", { class: "code" }, "judge2.csv"), " in the round's folder. When both are finished, run ",
    h("span", { class: "code" }, "python -m eval.make_qrels --round <name>"), " to see agreement and settle disagreements. Keys: ",
    h("span", { class: "kbd" }, "0"), " ", h("span", { class: "kbd" }, "1"), " ", h("span", { class: "kbd" }, "2"), " grade, ",
    h("span", { class: "kbd" }, "j"), " ", h("span", { class: "kbd" }, "k"), " move, ", h("span", { class: "kbd" }, "n"), " next ungraded.",
  ]));
  body.appendChild(h("div", { id: "judge-area" }));
  animateIn(Array.from(body.children).slice(0, 3), { y: 22, stagger: 0.07 });
  await loadSheet();
}
