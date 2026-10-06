// Entry point: theme, routing between the three views, and wiring the sections together.
import { $, $$, show, store } from "./dom.js";
import { initMotion, observeReveals, requestFrame } from "./motion.js";
import { initCarousel, initMarquee } from "./sections.js";
import { applyParams, focusQuery, initSearch } from "./search.js";
import { initStatus } from "./status.js";
import { renderEvaluation } from "./evaluation.js";
import { renderJudging } from "./judging.js";

const THEME_KEY = "lexshift.theme";
let current = null;
let searchBooted = false;

function initTheme() {
  const saved = store.get(THEME_KEY);
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  $("#theme-btn").addEventListener("click", () => {
    const active = document.documentElement.dataset.theme
      || (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = active === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    store.set(THEME_KEY, next);
  });
}

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { path: path || "/", params: new URLSearchParams(query) };
}

function setActive(route) {
  $$(".nav-links a").forEach((a) => {
    const on = a.dataset.route === route;
    a.classList.toggle("is-active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

async function route() {
  const { path, params } = parseHash();
  const view = path === "/evaluation" ? "evaluation" : path === "/judging" ? "judging" : "search";
  const changed = view !== current;
  if (changed) {
    $$("[data-view]").forEach((el) => show(el, el.dataset.view === view));
    current = view;
    window.scrollTo({ top: 0, behavior: "auto" });
    document.title = view === "search" ? "LexShift" : `${view === "evaluation" ? "Evaluation" : "Judging"} | LexShift`;
  }
  setActive(path === "/method" ? "method" : view);
  if (view === "evaluation") { if (changed) await renderEvaluation(); }
  else if (view === "judging") { if (changed) await renderJudging(); }
  else {
    if (path === "/method") { const el = $("#method"); if (el) el.scrollIntoView({ behavior: changed ? "auto" : "smooth", block: "start" }); }
    if (!searchBooted) { searchBooted = true; applyParams(params); }
    observeReveals();
  }
  requestFrame();
}

async function boot() {
  initTheme();
  initMotion();
  initSearch();
  initCarousel();
  $("#cta-btn").addEventListener("click", () => {
    if (current !== "search") window.location.hash = "#/";
    focusQuery();
  });
  window.addEventListener("hashchange", route);
  const status = await initStatus();
  route();
  initMarquee(status);
}

boot();
