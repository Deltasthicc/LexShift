// Entry point: theme, the router between the three views, and wiring the sections together.
import { $, $$, show, store } from "./dom.js";
import { initMotion, scrollToTarget, setNavActive, swapView, watchSections, requestFrame } from "./motion.js";
import { initAccordion, initCarousel } from "./sections.js";
import { applyParams, focusQuery, initSearch, paramsDiffer } from "./search.js";
import { initStatus } from "./status.js";
import { renderEvaluation } from "./evaluation.js";
import { renderJudging } from "./judging.js";
import { initTooltips } from "./ui.js";

const THEME_KEY = "lexshift.theme";
let current = null;
let searchBooted = false;

function initTheme() {
  const saved = store.get(THEME_KEY);
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  $("#theme-btn").addEventListener("click", () => {
    const root = document.documentElement;
    const active = root.dataset.theme || (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = active === "light" ? "dark" : "light";
    root.classList.add("theme-anim"); // colours cross-fade for a moment instead of snapping
    root.dataset.theme = next;
    store.set(THEME_KEY, next);
    window.setTimeout(() => root.classList.remove("theme-anim"), 700);
  });
}

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { path: path || "/", params: new URLSearchParams(query) };
}

async function doRoute() {
  const { path, params } = parseHash();
  const view = path === "/evaluation" ? "evaluation" : path === "/judging" ? "judging" : "search";
  const changed = view !== current;
  if (changed) {
    const from = current ? $(`[data-view="${current}"]`) : null;
    const to = $(`[data-view="${view}"]`);
    current = view;
    document.title = view === "search" ? "LexShift" : `${view === "evaluation" ? "Evaluation" : "Judging"} | LexShift`;
    setNavActive(path === "/method" ? "method" : view, Boolean(from));
    if (!from) { $$("[data-view]").forEach((el) => show(el, el === to)); }
    else await swapView(from, to);
    watchSections(view === "search");
  } else {
    setNavActive(path === "/method" ? "method" : view);
  }
  if (view === "evaluation") { if (changed) await renderEvaluation(); }
  else if (view === "judging") { if (changed) await renderJudging(); }
  else {
    if (path === "/method") scrollToTarget("#method", { offset: 70 });
    if (!searchBooted) { searchBooted = true; applyParams(params); }
    else if (paramsDiffer(params)) applyParams(params, { scroll: true });
  }
  requestFrame();
}

// Route changes are serialised: a second click while a view is still fading waits for it, then goes to the latest hash, so two
// transitions can never run over each other.
let routing = false;
let again = false;
async function route() {
  if (routing) { again = true; return; }
  routing = true;
  try {
    do { again = false; await doRoute(); } while (again);
  } finally {
    routing = false;
  }
}

async function boot() {
  initTheme();
  initTooltips();
  initMotion();
  initSearch();
  initAccordion();
  initCarousel();
  $("#cta-btn").addEventListener("click", () => {
    if (current !== "search") window.location.hash = "#/";
    window.setTimeout(focusQuery, current !== "search" ? 700 : 0);
  });
  $("#scroll-cue").addEventListener("click", () => scrollToTarget("#method", { offset: 70 }));
  window.addEventListener("hashchange", route);
  const status = await initStatus();
  await route();
  return status;
}

boot();
