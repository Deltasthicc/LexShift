// The Ranking page (M4): how the four signals are weighted in each configuration, what the evaluation is computed from, the checks on
// the hand-made files, and the results when they exist.
import { api } from "./api.js";
import { $, clear, f2, f3, h, pct, plural, SIGNALS, SIGNAL_LABEL } from "./dom.js";
import { animateIn } from "./motion.js";
import { appStatus } from "./status.js";

const CONFIG_TEXT = { b0: "B0: BM25 only", b1: "B1: + continuity", full: "Full: all four signals" };

const METRICS = ["P@5", "P@10", "R@10", "MAP", "nDCG@10", "harmful@10", "judged@10"];
const METRIC_HELP = {
  "P@5": "precision at 5", "P@10": "precision at 10", "R@10": "recall at 10", MAP: "mean average precision", "nDCG@10": "nDCG at 10",
  "harmful@10": "share of the top 10 that is a known-overruled case (lower is better)", "judged@10": "share of the top 10 that was judged",
};
const SIG_KEYS = [["w_rel", "rel"], ["w_cont", "cont"], ["w_health", "health"], ["w_auth", "auth"]];

function tile(label, value, small, detail, ratio) {
  return h("div", { class: "tile" }, [
    h("span", { class: "k" }, label),
    h("span", { class: "v" }, [String(value), small ? h("small", {}, small) : null]),
    ratio == null ? null : h("div", { class: `meter${ratio >= 1 ? " is-done" : ""}` }, h("i", { vars: { "--w": String(Math.max(0, Math.min(1, ratio))) } })),
    h("span", { class: "d" }, detail),
  ]);
}

function emptyResults() {
  return h("div", { class: "empty" }, [
    h("strong", {}, "No results yet"),
    "The ablation table appears here once the judged queries and their grades exist and the real modules are switched on. It is produced by ",
    h("span", { class: "code" }, "python -m eval.run_ablation --tune"), " (weights tuned on the dev queries only) and then ",
    h("span", { class: "code" }, "python -m eval.run_ablation --split test"), ". See ", h("span", { class: "code" }, "eval/JUDGING_GUIDE.md"), ".",
  ]);
}

function runCard(run) {
  const best = {};
  for (const m of METRICS) {
    const values = run.rows.map((r) => r[m]).filter((v) => typeof v === "number");
    best[m] = values.length ? (m === "harmful@10" ? Math.min(...values) : Math.max(...values)) : null;
  }
  const head = h("tr", {}, [h("th", { scope: "col" }, "Config"), h("th", { scope: "col" }, "Weights"), h("th", { scope: "col" }, "Queries"), ...METRICS.map((m) => h("th", { scope: "col", title: METRIC_HELP[m] }, m))]);
  const body = run.rows.map((row) => h("tr", {}, [
    h("td", {}, h("b", {}, String(row.config).toUpperCase())),
    h("td", {}, SIG_KEYS.filter(([k]) => (row[k] || 0) > 0).map(([k, s]) => `${s} ${(row[k]).toFixed(2)}`).join("  ")),
    h("td", {}, String(row.n_queries ?? "")),
    ...METRICS.map((m) => {
      const v = row[m];
      if (typeof v !== "number") return h("td", {}, "n/a");
      const classes = [v === best[m] ? "best" : "", m === "harmful@10" && v > 0 ? "harm" : ""].filter(Boolean).join(" ");
      return h("td", { class: classes }, h("div", { class: "cell" }, [f3(v), m === "harmful@10" ? null : h("div", { class: "meter" }, h("i", { vars: { "--w": String(Math.max(0, Math.min(1, v))) } }))]));
    }),
  ]));
  const types = Object.entries(run.ndcg_by_type || {});
  const configs = Array.from(new Set(types.flatMap(([, c]) => Object.keys(c))));
  return h("article", { class: "run" }, [
    h("div", { class: "run-head" }, [h("h3", {}, `${run.split} split`), h("span", { class: "tag" + (run.stub ? " is-stub" : "") }, run.stub ? "stub run" : `written ${run.modified}`)]),
    run.stub ? h("div", { class: "callout callout-warn" }, "STUB RUN: at least one signal came from a fixed-value stand-in, so these numbers are not results.") : null,
    h("div", { class: "table-wrap" }, h("table", { class: "metric-table" }, [h("thead", {}, head), h("tbody", {}, body)])),
    types.length ? h("div", { class: "table-wrap" }, h("table", { class: "metric-table" }, [
      h("thead", {}, h("tr", {}, [h("th", { scope: "col" }, "nDCG@10 by query type"), ...configs.map((c) => h("th", { scope: "col" }, c.toUpperCase()))])),
      h("tbody", {}, types.map(([type, vals]) => h("tr", {}, [h("td", {}, `Type ${type}`), ...configs.map((c) => h("td", {}, vals[c] == null ? "n/a" : f3(vals[c])))]))),
    ])) : null,
  ]);
}

function weightsCard() {
  const status = appStatus.value;
  const configs = status && status.configs ? status.configs : {};
  const names = Object.keys(configs);
  if (!names.length) return h("div", { class: "callout callout-error" }, "The weights could not be read.");
  return h("section", { class: "card" }, [
    h("h3", {}, "Weights in each configuration"),
    h("div", { class: "table-wrap" }, h("table", { class: "table weights-table" }, [
      h("thead", {}, h("tr", {}, [h("th", {}, "Configuration"), ...SIGNALS.map((s) => h("th", {}, h("span", { class: `sig-name sig-${s.key}` }, [h("span", { class: "legend-dot" }), SIGNAL_LABEL[s.key]])))])),
      h("tbody", {}, names.map((n) => h("tr", {}, [
        h("td", {}, CONFIG_TEXT[n] || n),
        ...SIGNALS.map((s) => {
          const w = configs[n].weights[s.key] || 0;
          return h("td", { class: `sig-${s.key}` }, w > 0 ? [h("span", { class: "bar" }, h("i", { vars: { "--w": pct(w) } })), f2(w)] : h("span", { class: "dim" }, "0"));
        }),
      ]))),
    ])),
    h("p", { class: "note" }, `Source: ${configs.full ? configs.full.source : configs[names[0]].source}. The top ${status.candidates} BM25 candidates are re-ranked; relevance and authority are min-max scaled over them, continuity and health are already in 0 to 1.`),
  ]);
}

export async function renderEvaluation() {
  const body = $("#eval-body");
  clear(body);
  body.appendChild(h("div", { class: "skeleton" }));
  let data;
  try {
    data = await api.evaluation();
  } catch (err) {
    clear(body);
    body.appendChild(h("div", { class: "callout callout-error" }, err.message));
    return;
  }
  clear(body);
  body.appendChild(weightsCard());
  const d = data.data;
  const planTotal = (d.plan.dev || 0) + (d.plan.test || 0);
  const g = d.qrels.grades;
  body.appendChild(h("section", {}, [
    h("h2", { class: "block-title" }, "Evaluation data"),
    h("div", { class: "tiles" }, [
      tile("Judged queries written", d.queries.total, `/ ${planTotal}`, `dev ${d.queries.dev} of ${d.plan.dev}, test ${d.queries.test} of ${d.plan.test}`, planTotal ? d.queries.total / planTotal : null),
      tile("Grades recorded", d.qrels.rows, "", d.qrels.rows ? `over ${plural(d.qrels.queries, "query", "queries")}: grade 2 ${g["2"]}, grade 1 ${g["1"]}, grade 0 ${g["0"]}` : "none yet: grading needs the pooled sheets from the judging view"),
      tile("Known overrulings", d.gold_overrulings, "", "hand-verified; used only to compute harmful@10"),
      tile("Judging rounds", data.rounds.length, "", data.rounds.length ? data.rounds.join(", ") : "none yet: python -m eval.pool builds one from the real modules"),
    ]),
  ]));
  if (d.errors.length) body.appendChild(h("div", {}, d.errors.map((e) => h("div", { class: "callout callout-error" }, e))));
  if (d.checks) {
    const rows = [
      ...d.checks.errors.map((t) => ["error", "Error", t]),
      ...d.checks.warnings.map((t) => ["warning", "Warning", t]),
      ...d.checks.info.map((t) => ["info", "Info", t]),
    ];
    body.appendChild(h("section", {}, [
      h("details", { class: "fold" }, [
        h("summary", {}, `Checks on the hand-made files: ${plural(d.checks.errors.length, "error")}, ${plural(d.checks.warnings.length, "warning")}`),
        h("p", { class: "block-sub" }, ["The same checks as ", h("span", { class: "code" }, "python -m eval.check_data"), "."]),
        h("div", { class: "findings" }, rows.map(([cls, label, text]) => h("div", { class: `finding ${cls}` }, [h("b", {}, label), h("span", {}, text)]))),
      ]),
    ]));
  }
  body.appendChild(h("section", {}, [
    h("h2", { class: "block-title" }, "Results"),
    data.runs.length ? h("div", { class: "runs" }, data.runs.map(runCard)) : emptyResults(),
  ]));
  body.appendChild(h("p", { class: "actions" }, h("a", { class: "btn", href: "#/judging" }, "Open the judging workbench")));
  animateIn(Array.from(body.children), { stagger: 0.05 });
}
