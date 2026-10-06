// Scroll motion with GSAP and ScrollTrigger (vendored in /static/vendor/gsap, loaded before this module; nothing is fetched).
//
// Two paradigms, both scrubbed by the scroll position:
//   image scale and fade   an image starts at 80% size, grows to full size as it enters, then darkens and fades to 20% as it leaves;
//   card stacking          each principle card sits (CSS sticky) while the next one slides over it, and shrinks and dims underneath.
// The hero art also settles from 80% to full size once on load. Reveal-on-enter stays an IntersectionObserver (CSS does the easing).
//
// Everything is created inside gsap.matchMedia(): visitors who prefer reduced motion get a static page, and an animation is reverted
// automatically if that preference changes while the page is open. If the vendored files are missing the page still works, unanimated.

const gsap = window.gsap;
const ScrollTrigger = window.ScrollTrigger;
const available = Boolean(gsap && ScrollTrigger);
let revealObserver = null;
let refreshTimer = null;

export const motionOn = () => available && document.documentElement.dataset.motion !== "off";

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

/** Positions depend on layout (results appear, views switch, fonts load): ask ScrollTrigger to measure again, once per burst. */
export function requestFrame() {
  if (!available) return;
  window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => ScrollTrigger.refresh(), 120);
}

function heroArt() {
  const art = document.querySelector(".hero-art");
  if (!art) return;
  gsap.fromTo(art, { scale: 0.8, opacity: 0.35 }, { scale: 1, opacity: 1, duration: 1.3, ease: "power3.out" });
  gsap.fromTo(art, { filter: "brightness(1)" }, {
    filter: "brightness(0.35)", ease: "none", immediateRender: false,
    scrollTrigger: { trigger: ".hero", start: "bottom 75%", end: "bottom top", scrub: true },
  });
}

function scaleAndFade() {
  gsap.utils.toArray(".stack-art[data-scalefade]").forEach((el) => {
    const tl = gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger: el, start: "top bottom", end: "bottom top", scrub: true } });
    tl.fromTo(el, { scale: 0.8 }, { scale: 1, duration: 0.4 })
      .to(el, { scale: 1, duration: 0.2 })
      .to(el, { opacity: 0.2, filter: "brightness(0.35)", duration: 0.4 });
  });
}

function stackCards() {
  const cards = gsap.utils.toArray("[data-stack]");
  cards.forEach((card, i) => {
    card.style.setProperty("--i", String(i));
    const next = cards[i + 1];
    if (!next) return;
    // from the moment the next card's top reaches this card's bottom edge until it has covered it
    const stuck = () => parseFloat(getComputedStyle(card).top) || 0;
    gsap.to(card, {
      scale: 0.95, filter: "brightness(0.58)", ease: "none",
      scrollTrigger: {
        trigger: next, scrub: true, invalidateOnRefresh: true,
        start: () => `top ${stuck() + card.offsetHeight}px`,
        end: () => `top ${stuck() + 18}px`,
      },
    });
  });
}

export function initMotion() {
  const root = document.documentElement;
  if (!available) {
    root.dataset.motion = "off";
    console.warn("GSAP is not loaded: /static/vendor/gsap is missing, so the page is shown without scroll motion.");
    observeReveals();
    return;
  }
  gsap.registerPlugin(ScrollTrigger);
  ScrollTrigger.create({ start: 24, end: "max", toggleClass: { targets: "#nav-wrap", className: "is-scrolled" } });

  const mm = gsap.matchMedia();
  mm.add("(prefers-reduced-motion: no-preference)", () => {
    root.dataset.motion = "on";
    heroArt();
    scaleAndFade();
    const wide = gsap.matchMedia();
    wide.add("(min-width: 901px)", () => { stackCards(); });
    observeReveals();
    return () => { wide.revert(); };
  });
  mm.add("(prefers-reduced-motion: reduce)", () => {
    root.dataset.motion = "off";
    observeReveals();
  });

  const settle = () => ScrollTrigger.refresh();
  window.addEventListener("load", settle);
  window.addEventListener("lexshift:layout", requestFrame);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(settle);
}
