// The motion engine: GSAP, ScrollTrigger, ScrollToPlugin and Flip (vendored in /static/vendor/gsap; nothing is fetched).
//
// What moves, and how it is kept smooth:
//   * Every scroll-linked animation is scrubbed with smoothing (scrub: 0.6 to 1.4), so wheel steps glide instead of stepping.
//   * Only transform and opacity are animated. Nothing is dimmed with a brightness filter (that made black panels), and nothing is clipped
//     by its section: the background is one fixed ambient layer that drifts with the whole page.
//   * Intro: the headline rises word by word out of a mask, the lede, form and art follow.
//   * Statement: the words of one paragraph scrub from 12% to full opacity as it crosses the screen.
//   * Pinned split: the section title stays pinned while the three rules scroll past, and the active one is tracked.
//   * Results: they enter with a stagger, and switching the ranking reorders them with Flip so the movement is visible.
//   * Views fade through one another; anchors scroll with an eased tween instead of jumping.
// Everything is created inside gsap.matchMedia(): with reduced motion nothing is animated and everything is shown, and if the vendored
// files are missing the page still works, unanimated.

const gsap = window.gsap;
const ScrollTrigger = window.ScrollTrigger;
const Flip = window.Flip;
const ScrollToPlugin = window.ScrollToPlugin;
const root = document.documentElement;
const available = Boolean(gsap && ScrollTrigger);
let refreshTimer = null;
const navObserverCleanups = [];

export const motionOn = () => available && root.dataset.motion !== "off";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

// ------------------------------------------------------------------------------------------------------------- helpers
/** Wrap every word of the text inside `el` in a span (nested inline elements are kept). `mask` adds an overflow mask for a rise-in. */
export function splitWords(el, { mask = false } = {}) {
  const words = [];
  const walk = (node) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        const frag = document.createDocumentFragment();
        for (const part of child.textContent.split(/(\s+)/)) {
          if (!part) continue;
          if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(" ")); continue; }
          const word = document.createElement("span");
          if (mask) {
            word.className = "w";
            const inner = document.createElement("span");
            inner.className = "wi";
            inner.textContent = part;
            word.appendChild(inner);
            words.push(inner);
          } else {
            word.className = "sw";
            word.textContent = part;
            words.push(word);
          }
          frag.appendChild(word);
        }
        node.replaceChild(frag, child);
      } else if (child.nodeType === Node.ELEMENT_NODE && !child.matches(".inline-art")) {
        walk(child);
      }
    }
  };
  walk(el);
  return words;
}

/** Run `fn` once, when `el` first comes into view (or at once without motion). */
export function onceVisible(el, fn, start = "top 85%") {
  if (!el) return;
  if (!motionOn()) { fn(); return; }
  ScrollTrigger.create({ trigger: el, start, once: true, onEnter: fn });
}

/** Grow every meter under `scope` that carries data-w (0 to 1) from empty; a CSS transition does the easing. */
export function growMeters(scope = document) {
  const apply = () => $$("[data-w]", scope).forEach((el) => el.style.setProperty("--w", el.dataset.w));
  if (!motionOn()) { apply(); return; }
  window.requestAnimationFrame(() => window.requestAnimationFrame(apply));
}

/** Ease a number up from zero in `el` (a presentation of a value that is already known). */
export function countUp(el, value, decimals = 0, duration = 1.1) {
  if (!motionOn() || !Number.isFinite(value)) { el.textContent = Number(value).toFixed(decimals); return; }
  const o = { v: 0 };
  gsap.to(o, { v: value, duration, ease: "power2.out", onUpdate: () => { el.textContent = o.v.toFixed(decimals); }, onComplete: () => { el.textContent = Number(value).toFixed(decimals); } });
}

/** Stagger elements in from below; transforms are cleared afterwards so sticky and pinned children keep working. */
export function animateIn(targets, { y = 28, stagger = 0.06, duration = 0.75, delay = 0 } = {}) {
  const list = gsap && targets ? gsap.utils.toArray(targets) : [];
  if (!motionOn() || !list.length) return Promise.resolve();
  return new Promise((resolve) => gsap.fromTo(list, { y, opacity: 0 }, { y: 0, opacity: 1, duration, stagger, delay, ease: "power3.out", clearProps: "transform,opacity", onComplete: resolve }));
}

/** Fade a container out, run `mutate`, fade it back in. */
export async function crossfade(el, mutate, { y = 10 } = {}) {
  if (!motionOn()) { mutate(); return; }
  await gsap.to(el, { opacity: 0, y: -y, duration: 0.2, ease: "power2.in" });
  mutate();
  await gsap.fromTo(el, { opacity: 0, y }, { opacity: 1, y: 0, duration: 0.5, ease: "power3.out", clearProps: "transform,opacity" });
}

/** Reorder the children of `container` with Flip: `mutate` replaces them with elements carrying the same data-flip-id values. */
export function flipSwap(container, mutate) {
  if (!motionOn() || !Flip) { mutate(); return Promise.resolve(); }
  const state = Flip.getState($$("[data-flip-id]", container));
  mutate();
  return new Promise((resolve) => {
    Flip.from(state, {
      duration: 0.95, ease: "power3.inOut", stagger: 0.02, absolute: false, scale: false, onComplete: resolve,
      onEnter: (els) => gsap.fromTo(els, { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: 0.7, stagger: 0.05, ease: "power3.out", clearProps: "transform,opacity" }),
    });
  });
}

/** Scroll to an element with an eased tween (native smooth scrolling fights ScrollTrigger). */
export function scrollToTarget(target, { offset = 92, duration = 1.15 } = {}) {
  const el = typeof target === "string" ? $(target) : target;
  if (!el) return;
  if (!motionOn() || !ScrollToPlugin) { el.scrollIntoView({ block: "start" }); return; }
  gsap.to(window, { scrollTo: { y: el, offsetY: offset, autoKill: true }, duration, ease: "power3.inOut" });
}

/** Fade one view out and the next in. Transforms are cleared afterwards: a transformed ancestor would break pinned and sticky children. */
export async function swapView(from, to) {
  if (!to) return;
  if (!motionOn() || !from || from === to) {
    if (from && from !== to) from.hidden = true;
    to.hidden = false;
    window.scrollTo(0, 0);
    requestFrame();
    return;
  }
  await gsap.to(from, { opacity: 0, y: -14, duration: 0.26, ease: "power2.in" });
  from.hidden = true;
  gsap.set(from, { clearProps: "opacity,transform" });
  window.scrollTo(0, 0);
  to.hidden = false;
  requestFrame();
  await gsap.fromTo(to, { opacity: 0, y: 28 }, { opacity: 1, y: 0, duration: 0.75, ease: "power3.out", clearProps: "opacity,transform" });
}

/** Positions depend on layout (results appear, views switch, fonts load): measure again, once per burst. */
export function requestFrame() {
  if (!available) return;
  window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => ScrollTrigger.refresh(), 140);
}

// ------------------------------------------------------------------------------------------------------------- navigation
let navActive = null;

function indicatorTo(link, animate = true) {
  const ind = $("#nav-ind");
  if (!ind) return;
  if (!link) { if (gsap) gsap.to(ind, { opacity: 0, duration: 0.3 }); else ind.style.opacity = "0"; return; }
  const x = link.parentElement.offsetLeft;
  const w = link.parentElement.offsetWidth;
  if (!gsap || !animate || !motionOn()) { ind.style.transform = `translate3d(${x}px, 0, 0)`; ind.style.width = `${w}px`; ind.style.opacity = "1"; return; }
  gsap.to(ind, { x, width: w, opacity: 1, duration: 0.6, ease: "power3.out", overwrite: "auto" });
}

export function setNavActive(route, animate = true) {
  navActive = route;
  $$(".nav-links a").forEach((a) => {
    const on = a.dataset.route === route;
    a.classList.toggle("is-active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  indicatorTo($(`.nav-links a[data-route="${route}"]`), animate);
}

function initNavIndicator() {
  const links = $$(".nav-links a");
  links.forEach((a) => {
    a.addEventListener("pointerenter", () => indicatorTo(a));
    a.addEventListener("focus", () => indicatorTo(a));
  });
  const back = () => indicatorTo($(`.nav-links a[data-route="${navActive}"]`));
  $("#nav-links").addEventListener("pointerleave", back);
  $("#nav-links").addEventListener("focusout", back);
  window.addEventListener("resize", () => indicatorTo($(`.nav-links a[data-route="${navActive}"]`), false));
}

/** On the search view, the nav follows the section in view: Search at the top, Method once the method section is crossed. */
export function watchSections(on) {
  while (navObserverCleanups.length) navObserverCleanups.pop()();
  if (!on || !available) return;
  const method = $("#method");
  if (!method) return;
  const st = ScrollTrigger.create({
    trigger: method, start: "top 55%", end: "bottom 35%",
    onToggle: (self) => { if (navActive === "search" || navActive === "method") setNavActive(self.isActive ? "method" : "search"); },
  });
  navObserverCleanups.push(() => st.kill());
}

// ------------------------------------------------------------------------------------------------------------- scenes
function ambient() {
  const common = { ease: "none", scrollTrigger: { trigger: document.body, start: 0, end: "max", scrub: 1.4 } };
  gsap.to(".blob.b1", { yPercent: 38, xPercent: -20, ...common });
  gsap.to(".blob.b2", { yPercent: -26, xPercent: 26, ...common });
  gsap.to(".blob.b3", { yPercent: -48, xPercent: -30, ...common });
}

function progress() {
  gsap.to("#progress i", { scaleX: 1, ease: "none", scrollTrigger: { start: 0, end: "max", scrub: 0.3 } });
  ScrollTrigger.create({ start: 24, end: "max", toggleClass: { targets: "#nav-wrap", className: "is-scrolled" } });
}

function intro() {
  const title = $(".hero-title");
  if (!title) { root.dataset.intro = "ready"; return; }
  const words = splitWords(title, { mask: true });
  const tl = gsap.timeline({ defaults: { ease: "expo.out" } });
  tl.from("#nav", { y: -34, opacity: 0, duration: 1, ease: "power3.out", clearProps: "transform,opacity" }, 0)
    .from(words, { yPercent: 118, duration: 1.2, stagger: 0.055 }, 0.12)
    .from(".hero-title .inline-art", { scale: 0, opacity: 0, duration: 0.9, stagger: 0.18, ease: "back.out(1.7)" }, 0.6)
    .from('[data-hero="lede"]', { y: 26, opacity: 0, duration: 1.05 }, 0.62)
    .from('[data-hero="form"]', { y: 32, opacity: 0, duration: 1.05 }, 0.74)
    .from(".hero-art .art-plate, .hero-art .art-lens", { y: 90, opacity: 0, scale: 0.94, duration: 1.5, stagger: 0.14, ease: "power3.out" }, 0.45)
    .from(".scroll-cue", { opacity: 0, y: 10, duration: 0.8 }, 1.5);
  tl.eventCallback("onComplete", () => { gsap.set([title, ...words], { clearProps: "transform" }); heroPointer(); });
  root.dataset.intro = "ready"; // the timeline has already put every hero element in its hidden start state, so this cannot flash
  // failsafe: if frames are not being produced (a background tab, a very slow machine) the intro still ends with everything visible
  window.setTimeout(() => { if (tl.progress() < 1) tl.progress(1); }, 6000);

  // the hero eases away as it scrolls off instead of being cut: the art drifts up and softens, the text lifts a little
  gsap.to(".hero-art", { y: -110, opacity: 0.5, ease: "none", scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: 0.9 } });
  gsap.to(".hero-inner", { y: -36, opacity: 0.55, ease: "none", scrollTrigger: { trigger: ".hero", start: "20% top", end: "bottom top", scrub: 0.9 } });
}

/** The art layers follow the pointer at different depths (fine pointers only). */
function heroPointer() {
  if (!window.matchMedia("(pointer: fine)").matches) return;
  const hero = $(".hero");
  if (!hero) return;
  const layers = [[".plate-a", 24], [".plate-b", -16], [".art-lens", 36]].map(([sel, d]) => {
    const el = $(sel);
    return el ? { d, x: gsap.quickTo(el, "x", { duration: 1, ease: "power3.out" }), y: gsap.quickTo(el, "y", { duration: 1, ease: "power3.out" }) } : null;
  }).filter(Boolean);
  hero.addEventListener("pointermove", (e) => {
    const nx = e.clientX / window.innerWidth - 0.5;
    const ny = e.clientY / window.innerHeight - 0.5;
    layers.forEach((l) => { l.x(nx * l.d * 2); l.y(ny * l.d * 2); });
  }, { passive: true });
  hero.addEventListener("pointerleave", () => layers.forEach((l) => { l.x(0); l.y(0); }));
}

function reveals() {
  $$("[data-reveal]").forEach((el) => {
    gsap.from(el, { y: 40, opacity: 0, duration: 1.15, ease: "power3.out", clearProps: "transform,opacity", scrollTrigger: { trigger: el, start: "top 90%", once: true } });
  });
  const slices = $$(".acc-slice");
  if (slices.length) gsap.from(slices, { y: 46, opacity: 0, duration: 1, stagger: 0.1, ease: "power3.out", clearProps: "transform,opacity", scrollTrigger: { trigger: "#acc", start: "top 88%", once: true } });
}

function statement() {
  const p = $("#statement-text");
  if (!p) return;
  const words = splitWords(p);
  gsap.set(words, { opacity: 0.12 });
  gsap.to(words, { opacity: 1, ease: "none", stagger: { each: 0.1 }, scrollTrigger: { trigger: p, start: "top 82%", end: "bottom 46%", scrub: 0.8 } });
}

function pinnedSplit() {
  const split = $("#split");
  const left = $("#split-left");
  const rules = $$(".rule");
  if (!split || !left || !rules.length) return;
  const offset = () => (parseFloat(getComputedStyle(root).getPropertyValue("--notice-h")) || 0) + 112;
  ScrollTrigger.create({
    trigger: split, pin: left, pinSpacing: false, anticipatePin: 1, invalidateOnRefresh: true,
    start: () => `top top+=${offset()}`,
    end: () => `bottom top+=${offset() + left.offsetHeight}`,
  });
  const dots = $$("#split-dots li");
  const now = $("#split-now");
  let active = -1;
  const setActive = (i) => {
    if (i === active) return;
    active = i;
    dots.forEach((d, n) => d.classList.toggle("is-on", n === i));
    gsap.to(now, { opacity: 0, y: 6, duration: 0.18, onComplete: () => { now.textContent = rules[i].dataset.title; gsap.to(now, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out" }); } });
  };
  rules.forEach((rule, i) => {
    ScrollTrigger.create({ trigger: rule, start: "top 58%", end: "bottom 58%", onToggle: (self) => { if (self.isActive) setActive(i); } });
    const tl = gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger: rule, start: "top 92%", end: "bottom 8%", scrub: 0.8 } });
    tl.fromTo(rule, { opacity: 0.3, scale: 0.95 }, { opacity: 1, scale: 1, duration: 0.35 })
      .to(rule, { opacity: 1, scale: 1, duration: 0.3 })
      .to(rule, { opacity: 0.5, scale: 0.98, duration: 0.35 });
    const fill = $(".d-fill", rule);
    if (fill) gsap.fromTo(fill, { scaleX: 0, transformOrigin: "left center", transformBox: "fill-box" }, { scaleX: 1, duration: 1.1, ease: "power3.out", scrollTrigger: { trigger: rule, start: "top 70%", once: true } });
  });
}

function magnetic() {
  if (!window.matchMedia("(pointer: fine)").matches) return;
  $$(".magnetic").forEach((btn) => {
    const x = gsap.quickTo(btn, "x", { duration: 0.5, ease: "power3.out" });
    const y = gsap.quickTo(btn, "y", { duration: 0.5, ease: "power3.out" });
    btn.addEventListener("pointermove", (e) => {
      const r = btn.getBoundingClientRect();
      x((e.clientX - (r.left + r.width / 2)) * 0.22);
      y((e.clientY - (r.top + r.height / 2)) * 0.3);
    });
    btn.addEventListener("pointerleave", () => { x(0); y(0); });
  });
}

// ------------------------------------------------------------------------------------------------------------- entry
export function initMotion() {
  initNavIndicator();
  if (!available) {
    root.dataset.intro = "ready";
    root.dataset.motion = "off";
    console.warn("GSAP is not loaded: /static/vendor/gsap is missing, so the page is shown without scroll motion.");
    return;
  }
  gsap.registerPlugin(ScrollTrigger, ...[ScrollToPlugin, Flip].filter(Boolean));
  gsap.defaults({ ease: "power3.out" });
  ScrollTrigger.config({ ignoreMobileResize: true });

  const mm = gsap.matchMedia();
  mm.add("(prefers-reduced-motion: no-preference)", () => {
    root.dataset.motion = "on";
    progress();
    ambient();
    intro();
    reveals();
    statement();
    magnetic();
    const wide = gsap.matchMedia();
    wide.add("(min-width: 901px)", () => { pinnedSplit(); });
    return () => { wide.revert(); };
  });
  mm.add("(prefers-reduced-motion: reduce)", () => { root.dataset.motion = "off"; root.dataset.intro = "ready"; });

  window.addEventListener("load", () => ScrollTrigger.refresh());
  window.addEventListener("lexshift:layout", requestFrame);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => ScrollTrigger.refresh());
}
