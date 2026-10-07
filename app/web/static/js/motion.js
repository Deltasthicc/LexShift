// Motion, kept deliberately small: a view fades in, new content rises a few pixels, and when the ranking changes the results move to
// their new places with Flip so the re-ordering can be seen. Only transform and opacity are animated. With reduced motion, or without
// the vendored GSAP files, nothing moves and everything still works.

const gsap = window.gsap;
const Flip = window.Flip;
const root = document.documentElement;
const reduced = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

if (gsap && Flip) gsap.registerPlugin(Flip);

function syncPreference() {
  root.dataset.motion = !gsap || (reduced && reduced.matches) ? "off" : "on";
}
syncPreference();
if (reduced && reduced.addEventListener) reduced.addEventListener("change", syncPreference);

export const motionOn = () => Boolean(gsap) && root.dataset.motion !== "off";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/** Fade targets in from a few pixels below. */
export function animateIn(targets, { y = 10, stagger = 0.04, duration = 0.45, delay = 0 } = {}) {
  const list = gsap && targets ? gsap.utils.toArray(targets) : [];
  if (!motionOn() || !list.length) return Promise.resolve();
  return new Promise((resolve) => gsap.fromTo(list, { y, opacity: 0 }, { y: 0, opacity: 1, duration, stagger, delay, ease: "power2.out", clearProps: "transform,opacity", onComplete: resolve }));
}

/** Reorder the children of `container` with Flip: `mutate` replaces them with elements carrying the same data-flip-id values. */
export function flipSwap(container, mutate) {
  if (!motionOn() || !Flip) { mutate(); return Promise.resolve(); }
  const state = Flip.getState($$("[data-flip-id]", container));
  mutate();
  return new Promise((resolve) => {
    Flip.from(state, {
      duration: 0.7, ease: "power2.inOut", absolute: false, scale: false, onComplete: resolve,
      onEnter: (els) => gsap.fromTo(els, { opacity: 0 }, { opacity: 1, duration: 0.4, clearProps: "opacity" }),
    });
  });
}

/** Scroll so that the element sits `offset` pixels below the top of the window. */
export function scrollToTarget(target, { offset = 80 } = {}) {
  const el = typeof target === "string" ? $(target) : target;
  if (!el) return;
  const top = el.getBoundingClientRect().top + window.scrollY - offset;
  window.scrollTo({ top: Math.max(0, top), behavior: motionOn() ? "smooth" : "auto" });
}

/** Hide one view and fade the next one in. */
export function swapView(from, to) {
  if (!to) return;
  if (from && from !== to) from.hidden = true;
  to.hidden = false;
  window.scrollTo(0, 0);
  if (motionOn() && from && from !== to) gsap.fromTo(to, { opacity: 0 }, { opacity: 1, duration: 0.3, ease: "power1.out", clearProps: "opacity" });
}

/** Mark the navigation link of the current route. */
export function setNavActive(route) {
  $$(".nav-links a[data-route]").forEach((a) => {
    if (a.dataset.route === route) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}
