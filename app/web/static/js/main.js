// Entry point: theme, the router between the views (one per module, plus search and judging), and wiring the pages together.
import { $, $$, show, store } from "./dom.js";
import { scrollToTarget, setNavActive, swapView } from "./motion.js";
import { applyParams, focusQuery, initSearch, paramsDiffer, renderFormula } from "./search.js";
import { initStatus } from "./status.js";
import { renderEvaluation } from "./evaluation.js";
import { renderJudging } from "./judging.js";
import { renderIndexPage } from "./m1.js";
import { renderStatutesPage } from "./statutes.js";
import { renderTreatmentPage } from "./treatment.js";
import { initTooltips } from "./ui.js";

const THEME_KEY = "lexshift.theme";
const ROUTES = { "/": "search", "/index": "index", "/statutes": "statutes", "/treatment": "treatment", "/ranking": "ranking", "/evaluation": "ranking", "/judging": "judging" };
const TITLES = { index: "Index (M1)", statutes: "Statutes (M2)", treatment: "Treatment (M3)", ranking: "Ranking (M4)", judging: "Judging" };
const RENDER = { index: renderIndexPage, statutes: renderStatutesPage, treatment: renderTreatmentPage, ranking: renderEvaluation, judging: renderJudging };
let current = null;
let searchBooted = false;

function initTheme() {
  const saved = store.get(THEME_KEY);
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  $("#theme-btn").addEventListener("click", () => {
    const root = document.documentElement;
    const active = root.dataset.theme || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = active === "light" ? "dark" : "light";
    root.dataset.theme = next;
    store.set(THEME_KEY, next);
  });
}

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { path: path || "/", params: new URLSearchParams(query) };
}

async function route() {
  const { path, params } = parseHash();
  const view = ROUTES[path] || "search";
  const changed = view !== current;
  if (changed) {
    const from = current ? $(`[data-view="${current}"]`) : null;
    const to = $(`[data-view="${view}"]`);
    current = view;
    document.title = view === "search" ? "LexShift" : `${TITLES[view]} | LexShift`;
    setNavActive(view === "judging" ? "ranking" : view);
    if (!from) $$("[data-view]").forEach((el) => show(el, el === to));
    else swapView(from, to);
  }
  if (view !== "search") {
    // the module pages pick up the latest search query each time they are opened; the Ranking and Judging pages reload on entry
    if (changed || view === "statutes" || view === "treatment") await RENDER[view]();
    return;
  }
  if (!searchBooted) { searchBooted = true; applyParams(params, { scroll: true }); } // a shared link opens on its results, past the intro
  else if (paramsDiffer(params)) applyParams(params, { scroll: true });
}

// A link to the hash we are already on fires no hashchange, so it would do nothing at all: scroll to the top of that view instead.
function wireNavLinks() {
  $$("a.brand, .nav-links a[data-route]").forEach((a) => {
    a.addEventListener("click", (e) => {
      const href = a.getAttribute("href");
      if (href !== (window.location.hash || "#/")) return; // a different hash: the router handles it
      e.preventDefault();
      if (current === "search") scrollToTarget("#top", { offset: 0 });
      else scrollToTarget($(`[data-view="${current}"]`), { offset: 0 });
    });
  });
}

async function boot() {
  initTheme();
  initTooltips();
  initSearch();
  wireNavLinks();
  // the intro screen's two links scroll down to the search instead of changing the route
  ["#intro-start", "#scroll-cue"].forEach((sel) => $(sel).addEventListener("click", (e) => { e.preventDefault(); focusQuery(); }));
  window.addEventListener("hashchange", route);
  const status = await initStatus();
  renderFormula(status);
  await route();
}

boot();
