// System status: the nav indicator, the stub-mode notice and the status panel.
import { api } from "./api.js";
import { $, clear, f2, formatBytes, GROUP_LABEL, h, pct, SIGNALS, SIGNAL_LABEL, show } from "./dom.js";
import { openPanel } from "./ui.js";

export const appStatus = { value: null };

const ARTEFACT_LABEL = {
  judgments: "judgments.jsonl (M1)", doc_statutes: "doc_statutes.jsonl (M2)", citations: "citations.jsonl (M3)", doc_health: "doc_health.jsonl (M3)",
  doc_meta: "doc_meta.jsonl (optional titles)", statute_map: "statute_map.csv (M2)", treatment_gold: "treatment_gold.csv (M3)",
  queries: "queries.jsonl (hand-made)", qrels: "qrels.tsv (hand-judged)", gold_overrulings: "gold_overrulings.csv (hand-verified)", index_dir: "search index folder (M1)",
};

function updateNav(status) {
  const dot = $("#status-dot");
  const label = $("#status-label");
  dot.className = "dot";
  if (!status) { dot.classList.add("is-error"); label.textContent = "Server not reachable"; return; }
  if (status.load_error) { dot.classList.add("is-error"); label.textContent = "Module error"; }
  else if (status.stub_mode) { dot.classList.add("is-stub"); label.textContent = `Stub mode: ${status.stubbed.length} of 4`; }
  else { dot.classList.add("is-real"); label.textContent = "All modules real"; }
}

function updateNotice(status, message) {
  const notice = $("#notice");
  const text = $("#notice-text");
  let msg = message || "";
  let error = Boolean(message);
  if (!msg && status && status.load_error) { msg = `A module could not be loaded: ${status.load_error}`; error = true; }
  else if (!msg && status && status.stub_mode) {
    msg = `Stub mode: ${status.stubbed.map((g) => GROUP_LABEL[g] || g).join(", ")} come from fixed-value stand-ins. What this interface shows is not a result.`;
  }
  text.textContent = msg;
  notice.classList.toggle("is-error", error);
  show(notice, Boolean(msg));
  document.body.classList.toggle("has-notice", Boolean(msg));
  measureNotice();
}

/** The notice wraps to several lines on a phone; the fixed navigation sits exactly below it whatever its height. */
function measureNotice() {
  const notice = $("#notice");
  document.documentElement.style.setProperty("--notice-h", notice.hidden ? "0px" : `${notice.offsetHeight}px`);
}
window.addEventListener("resize", measureNotice);

function renderPanel(status) {
  const body = $("#status-body");
  clear(body);
  $("#status-meta").textContent = status.stub_mode ? "Stub mode: not every module is real yet." : "Every module is real.";
  const kv = (rows) => h("div", { class: "kv" }, rows.map(([k, v]) => h("div", { class: "kv-row" }, [h("span", {}, k), h("span", {}, v)])));
  body.appendChild(h("section", { class: "status-section" }, [
    h("h3", {}, "Modules"),
    kv(Object.entries(status.providers).map(([g, v]) => [GROUP_LABEL[g] || g, h("span", { class: `state${v === "stub" ? " is-stub" : ""}` }, v === "stub" ? "stub" : "real")])),
    status.env_override ? h("p", { class: "block-sub" }, ["Overridden for this run by ", h("span", { class: "code" }, `LEXSHIFT_STUBS=${status.env_override}`)]) : null,
    status.load_error ? h("p", { class: "callout callout-error" }, status.load_error) : null,
  ]));
  body.appendChild(h("section", { class: "status-section" }, [
    h("h3", {}, `Ranking configurations (top ${status.candidates} candidates are re-ranked)`),
    ...Object.entries(status.configs).map(([name, c]) => h("div", { class: "status-section" }, [
      h("p", {}, [h("b", {}, name), `  ${c.source}`]),
      h("div", { class: "weights" }, SIGNALS.filter((s) => (c.weights[s.key] || 0) > 0).map((s) => h("div", { class: `weight-row sig-${s.key}` }, [h("span", {}, SIGNAL_LABEL[s.key]), h("span", { class: "bar" }, h("i", { vars: { "--w": pct(c.weights[s.key]) } })), h("b", {}, f2(c.weights[s.key]))]))),
    ])),
  ]));
  body.appendChild(h("section", { class: "status-section" }, [
    h("h3", {}, "Data files"),
    kv(status.artefacts.map((a) => [
      ARTEFACT_LABEL[a.key] || a.key,
      h("span", { class: `state${a.exists ? "" : " is-missing"}` }, a.exists ? [a.rows != null ? `${a.rows.toLocaleString("en-IN")} rows` : "present", a.size ? `  ·  ${formatBytes(a.size)}` : ""].join("") : "missing"),
    ])),
  ]));
  if (status.corpus) {
    const years = Object.entries(status.corpus.years).map(([y, n]) => `${y}: ${n}`).join("  ·  ");
    body.appendChild(h("section", { class: "status-section" }, [
      h("h3", {}, "Corpus"),
      kv([["Judgments", status.corpus.documents.toLocaleString("en-IN")], ["By year", years || "unknown"], ["Read from", status.corpus.from || "n/a"]]),
      status.corpus.documents && Object.keys(status.corpus.years).length === 1 ? h("p", { class: "block-sub" }, "The corpus spans one year, so no precedent in it can have been overruled by a judgment inside it. Older judgments are needed before the treatment signal has anything to find.") : null,
    ]));
  }
  body.appendChild(h("section", { class: "status-section" }, [
    h("h3", {}, "How a module goes live"),
    h("p", { class: "block-sub" }, ["The owner flips that module's switch under ", h("span", { class: "code" }, "stubs:"), " in ", h("span", { class: "code" }, "common/config.yaml"), " in the commit that makes it pass ", h("span", { class: "code" }, "python eval/smoke.py"), ". For one run, ", h("span", { class: "code" }, "LEXSHIFT_STUBS=none python -m app.server"), " starts the interface with every module real."]),
  ]));
}

export function openStatus() {
  if (!appStatus.value) return;
  renderPanel(appStatus.value);
  openPanel($("#status-panel"), $("#status-close"));
}

export async function initStatus() {
  $("#status-btn").addEventListener("click", openStatus);
  $("#notice-details").addEventListener("click", openStatus);
  try {
    appStatus.value = await api.status();
  } catch (err) {
    appStatus.value = null;
    updateNav(null);
    updateNotice(null, err.message);
    return null;
  }
  updateNav(appStatus.value);
  updateNotice(appStatus.value);
  return appStatus.value;
}
