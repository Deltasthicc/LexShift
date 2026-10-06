// Scroll motion without a library: reveal-on-enter, image scale-and-fade, stacking cards, and the nav pill state.
//
// One requestAnimationFrame-throttled scroll handler writes CSS custom properties (--s scale, --o opacity, --b brightness) that
// the stylesheet turns into transforms, so layout is never read and written in the same pass more than once per frame.
// Everything is skipped when the visitor prefers reduced motion (html[data-motion="off"]).

const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
const reducedQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

let ticking = false;
let revealObserver = null;

export const motionOn = () => document.documentElement.dataset.motion !== "off";

function applyPreference() {
  document.documentElement.dataset.motion = reducedQuery && reducedQuery.matches ? "off" : "on";
}

export function observeReveals(root = document) {
  const targets = Array.from(root.querySelectorAll(".reveal:not(.is-in)"));
  if (!targets.length) return;
  if (!("IntersectionObserver" in window) || !motionOn()) { targets.forEach((t) => t.classList.add("is-in")); return; }
  if (!revealObserver) {
    revealObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) { entry.target.classList.add("is-in"); revealObserver.unobserve(entry.target); }
      }
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
  }
  targets.forEach((t, i) => {
    if (!t.style.getPropertyValue("--i")) t.style.setProperty("--i", String(i % 5));
    revealObserver.observe(t);
  });
}

function scaleFade(vh) {
  for (const el of document.querySelectorAll("[data-scalefade]")) {
    const r = el.getBoundingClientRect();
    if (r.bottom < -vh || r.top > vh * 2) continue;
    const enter = easeOut(clamp((vh - r.top) / (vh * 0.55)));
    const leave = clamp(1 - (r.bottom - vh * 0.1) / (vh * 0.5));
    el.style.setProperty("--s", (0.8 + 0.2 * enter).toFixed(3));
    el.style.setProperty("--o", (1 - 0.8 * leave).toFixed(3));
    el.style.setProperty("--b", (1 - 0.65 * leave).toFixed(3));
  }
}

function stacking() {
  const cards = Array.from(document.querySelectorAll("[data-stack]"));
  if (!cards.length) return;
  const desktop = window.innerWidth > 900;
  cards.forEach((card, i) => {
    card.style.setProperty("--i", String(i));
    if (!desktop) { card.style.removeProperty("--ss"); card.style.removeProperty("--sb"); return; }
    const next = cards[i + 1];
    let t = 0;
    if (next) {
      const r = card.getBoundingClientRect();
      const stuckAt = parseFloat(getComputedStyle(card).top) || 0;
      const nr = next.getBoundingClientRect();
      t = clamp((stuckAt + r.height - nr.top) / Math.max(1, r.height - 18));
    }
    card.style.setProperty("--ss", (1 - 0.05 * t).toFixed(3));
    card.style.setProperty("--sb", (1 - 0.42 * t).toFixed(3));
  });
}

function frame() {
  ticking = false;
  const wrap = document.getElementById("nav-wrap");
  if (wrap) wrap.classList.toggle("is-scrolled", window.scrollY > 24);
  if (!motionOn()) return;
  const vh = window.innerHeight || 800;
  scaleFade(vh);
  stacking();
}

export function requestFrame() {
  if (!ticking) { ticking = true; window.requestAnimationFrame(frame); }
}

export function initMotion() {
  applyPreference();
  if (reducedQuery && reducedQuery.addEventListener) {
    reducedQuery.addEventListener("change", () => { applyPreference(); requestFrame(); });
  }
  window.addEventListener("scroll", requestFrame, { passive: true });
  window.addEventListener("resize", requestFrame);
  window.addEventListener("lexshift:layout", requestFrame);
  // the hero art starts small and settles to full size once; afterwards it follows the scroll without easing
  const art = document.querySelector(".hero-art");
  if (art && motionOn()) {
    art.style.setProperty("--s", "0.8");
    art.classList.add("is-settling");
    window.setTimeout(() => { art.classList.remove("is-settling"); requestFrame(); }, 1100);
    window.requestAnimationFrame(() => window.requestAnimationFrame(requestFrame));
  } else {
    requestFrame();
  }
  observeReveals();
}
