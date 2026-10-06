// DOM helpers shared by every view.
//
// Everything that came from a judgment, a query or a file is inserted as TEXT (createTextNode / textContent), never as markup:
// court text is untrusted data. The Content-Security-Policy also forbids inline styles, so dynamic sizes go through CSS custom
// properties set with the CSSOM (el.style.setProperty), which the policy allows.

const SVG_NS = "http://www.w3.org/2000/svg";

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function append(el, child) {
  if (child == null || child === false) return;
  if (Array.isArray(child)) { child.forEach((c) => append(el, c)); return; }
  el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
}

/** h("div", {class: "x", dataset: {id: 1}, onclick: fn, vars: {"--w": "40%"}}, "text", child, ...) */
export function h(tag, props = {}, ...children) {
  const svg = tag.startsWith("svg:");
  const el = svg ? document.createElementNS(SVG_NS, tag.slice(4)) : document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "vars") for (const [name, v] of Object.entries(value)) el.style.setProperty(name, v);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  children.forEach((c) => append(el, c));
  return el;
}

export const clear = (el) => el.replaceChildren();
export const show = (el, on = true) => { el.hidden = !on; };

export function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/** localStorage that never throws (private windows and blocked storage return the fallback). */
export const store = {
  get(key, fallback = null) {
    try { const v = window.localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable: the page works without it */ }
  },
};

// ------------------------------------------------------------------------------------------------ formatting
export const SIGNALS = [
  { key: "rel", name: "Relevance", short: "rel", group: "search" },
  { key: "cont", name: "Continuity", short: "cont", group: "statute" },
  { key: "health", name: "Treatment", short: "health", group: "health" },
  { key: "auth", name: "Authority", short: "auth", group: "authority" },
];
export const CONFIG_LABELS = {
  b0: "B0: BM25 relevance only",
  b1: "B1: relevance and continuity",
  full: "Full: relevance, continuity, treatment, authority",
};
export const SHORT_CONFIG = { b0: "BM25 only", b1: "BM25 + continuity", full: "Full ranking" };

export const f2 = (x) => (typeof x === "number" && Number.isFinite(x) ? x.toFixed(2) : "n/a");
export const f3 = (x) => (typeof x === "number" && Number.isFinite(x) ? x.toFixed(3) : "n/a");
export const pct = (x) => `${Math.round(Math.max(0, Math.min(1, x)) * 100)}%`;

export function formatBytes(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Dates arrive as ISO ("2025-01-02") or as M1 writes them today ("02 January 2025"); show either as given, ISO preferred. */
export function formatDate(value) {
  if (!value) return "";
  return String(value);
}

export function plural(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

export const SIGNAL_LABEL = Object.fromEntries(SIGNALS.map((s) => [s.key, s.name]));
export const GROUP_LABEL = { search: "Search (M1)", statute: "Statutes (M2)", health: "Treatment (M3)", authority: "Authority (M3)" };

export function signalDot(key, stub = false) {
  return h("span", { class: `legend-dot sig-${key}${stub ? " is-stub" : ""}`, "aria-hidden": "true" });
}

export function el(tag, className, text) {
  return h(tag, { class: className }, text);
}
