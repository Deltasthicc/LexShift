// Small interface pieces shared by every view: toasts, tooltips, animated show/hide, and the slide-over panels.
//
// Nothing here snaps: a panel slides and fades in and out, a toast rises and settles, a tooltip fades. Motion is skipped when the visitor
// prefers reduced motion (html[data-motion="off"]); the CSS transitions are then effectively instant.
import { $, h } from "./dom.js";

const gsap = window.gsap;
const calm = () => !gsap || document.documentElement.dataset.motion === "off";

export function toast(message, kind = "ok", ms = 3400) {
  const box = $("#toasts");
  if (!box) return;
  const el = h("div", { class: `toast${kind === "error" ? " is-error" : kind === "warn" ? " is-warn" : ""}`, role: "status" }, message);
  box.appendChild(el);
  if (!calm()) gsap.fromTo(el, { y: 18, opacity: 0, scale: 0.96 }, { y: 0, opacity: 1, scale: 1, duration: 0.55, ease: "power3.out", clearProps: "transform" });
  let gone = false;
  const remove = () => {
    if (gone) return;
    gone = true;
    if (calm()) el.remove();
    else gsap.to(el, { y: 8, opacity: 0, duration: 0.35, ease: "power2.in", onComplete: () => el.remove() });
  };
  const timer = window.setTimeout(remove, ms);
  el.addEventListener("click", () => { window.clearTimeout(timer); remove(); });
}

/** Show or hide an element through its `.anim-pop` CSS transition instead of snapping `hidden`. */
export function reveal(el, on) {
  if (on) {
    el.hidden = false;
    void el.offsetWidth; // start the transition from the hidden state
    el.classList.add("is-in");
    return;
  }
  el.classList.remove("is-in");
  window.setTimeout(() => { if (!el.classList.contains("is-in")) el.hidden = true; }, 420);
}

// ------------------------------------------------------------------------------------------------------------- tooltips
export function initTooltips() {
  const tip = $("#tip");
  if (!tip) return;
  let target = null;
  const place = (x, y) => {
    const w = tip.offsetWidth;
    const hgt = tip.offsetHeight;
    const left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14));
    const top = y - hgt - 14 < 8 ? y + 18 : y - hgt - 14;
    tip.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
  };
  const show = (el, x, y) => {
    target = el;
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
    place(x, y);
    tip.classList.add("is-on");
  };
  const hide = () => { target = null; tip.classList.remove("is-on"); };
  document.addEventListener("pointerover", (e) => { const el = e.target.closest && e.target.closest("[data-tip]"); if (el && el !== target) show(el, e.clientX, e.clientY); });
  document.addEventListener("pointermove", (e) => { if (target) place(e.clientX, e.clientY); }, { passive: true });
  document.addEventListener("pointerout", (e) => { if (target && !(e.relatedTarget && target.contains(e.relatedTarget))) hide(); });
  document.addEventListener("focusin", (e) => { const el = e.target.closest && e.target.closest("[data-tip]"); if (el) { const r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); } });
  document.addEventListener("focusout", hide);
  window.addEventListener("scroll", hide, { passive: true });
}

// ------------------------------------------------------------------------------------------------------------- panels
function trap(event, root) {
  if (event.key !== "Tab") return;
  const focusable = Array.from(root.querySelectorAll("button, [href], input, select, textarea, summary, [tabindex]:not([tabindex='-1'])")).filter((el) => !el.disabled && el.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

/** Slide a panel in over a dimmed page. Returns close(); Escape, the scrim and the close button all call it. */
export function openPanel(panel, closeButton, onClose) {
  const scrim = $("#scrim");
  const opener = document.activeElement;
  scrim.hidden = false;
  panel.hidden = false;
  void panel.offsetWidth;
  panel.classList.add("is-open");
  scrim.classList.add("is-open");
  document.body.style.setProperty("overflow", "hidden");
  const keys = (event) => {
    if (event.key === "Escape") { event.stopPropagation(); close(); }
    else trap(event, panel);
  };
  const close = () => {
    panel.classList.remove("is-open");
    document.removeEventListener("keydown", keys, true);
    scrim.onclick = null;
    if (!document.querySelector(".drawer.is-open")) {
      scrim.classList.remove("is-open");
      document.body.style.removeProperty("overflow");
    }
    window.setTimeout(() => {
      if (!panel.classList.contains("is-open")) panel.hidden = true;
      if (!document.querySelector(".drawer.is-open")) scrim.hidden = true;
    }, 760);
    if (onClose) onClose();
    if (opener && opener.focus) opener.focus({ preventScroll: true });
  };
  document.addEventListener("keydown", keys, true);
  scrim.onclick = close;
  closeButton.onclick = close;
  closeButton.focus({ preventScroll: true });
  return close;
}
