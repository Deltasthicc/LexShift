// The editorial sections: the horizontal accordion of the four signals, and the evidence carousel fed by the current results.
import { $, $$, clear, f2, h } from "./dom.js";
import { growMeters, motionOn, onceVisible } from "./motion.js";
import { openReader } from "./reader.js";

const gsap = window.gsap;
const MONO_SKIP = new Set(["v", "vs", "versus", "state", "of", "the", "and", "ors", "anr", "others", "union", "india", "m", "s", "etc"]);
const ORDER = { overruled: 0, doubted: 1, criticised: 1, criticized: 1, followed: 2, neutral: 3 };
const statusVar = (label) => (label === "overruled" ? "var(--st-over)" : label === "doubted" || label === "criticised" ? "var(--st-doubt)" : label === "followed" ? "var(--st-follow)" : "var(--st-neutral)");

// ------------------------------------------------------------------------------------------------------------- accordion
export function initAccordion() {
  const acc = $("#acc");
  if (!acc) return;
  const slices = $$(".acc-slice", acc);
  const terms = $$("#formula .f-term");
  let current = slices.find((s) => s.classList.contains("is-open")) || null;
  let intent = 0;

  const open = (slice) => {
    if (!slice || slice === current) return;
    current = slice;
    slices.forEach((s) => { const on = s === slice; s.classList.toggle("is-open", on); s.setAttribute("aria-expanded", String(on)); });
    terms.forEach((t) => t.classList.toggle("is-hot", t.dataset.sig === slice.dataset.sig));
  };

  slices.forEach((slice, i) => {
    slice.addEventListener("pointerenter", (e) => {
      if (e.pointerType === "touch") return;
      window.clearTimeout(intent);
      intent = window.setTimeout(() => open(slice), 90); // a short intent delay stops the row flickering as the pointer crosses slices
    });
    slice.addEventListener("click", () => open(slice));
    slice.addEventListener("focus", () => open(slice));
    slice.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(slice); }
      else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); slices[Math.min(slices.length - 1, i + 1)].focus(); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); slices[Math.max(0, i - 1)].focus(); }
    });
    slice.addEventListener("pointermove", (e) => {
      const r = slice.getBoundingClientRect();
      slice.style.setProperty("--mx", `${Math.round(e.clientX - r.left)}px`);
      slice.style.setProperty("--my", `${Math.round(e.clientY - r.top)}px`);
    }, { passive: true });
  });
  acc.addEventListener("pointerleave", () => window.clearTimeout(intent));
  terms.forEach((t) => {
    const slice = slices.find((s) => s.dataset.sig === t.dataset.sig);
    t.addEventListener("pointerenter", () => open(slice));
    t.addEventListener("click", () => { open(slice); slice.focus({ preventScroll: true }); });
  });
  terms.forEach((t) => t.classList.toggle("is-hot", current && t.dataset.sig === current.dataset.sig));
  onceVisible(acc, () => growMeters(acc), "top 85%");
}

// ------------------------------------------------------------------------------------------------------------- carousel
function monogram(title) {
  const words = String(title || "").split(/[^A-Za-z]+/).filter((w) => w.length > 1 && !MONO_SKIP.has(w.toLowerCase()));
  return (words.slice(0, 2).map((w) => w[0]).join("") || "§").toUpperCase();
}

function gather(data, config) {
  const block = data.configs[config];
  const out = [];
  for (const r of block.results) {
    for (const e of r.evidence || []) {
      const label = String(e.label || "neutral").toLowerCase();
      out.push({ r, e, label, stub: block.stubbed.includes("health") });
    }
  }
  out.sort((a, b) => (ORDER[a.label] ?? 4) - (ORDER[b.label] ?? 4) || (b.e.confidence || 0) - (a.e.confidence || 0));
  return out.slice(0, 12);
}

export function initCarousel() {
  const carousel = $("#carousel");
  const plates = $("#plates");
  const quote = $("#quote");
  const meta = $("#quote-meta");
  const count = $("#car-count");
  const dots = $("#car-dots");
  const prev = $("#car-prev");
  const next = $("#car-next");
  const sub = $("#evidence-sub");
  let items = [];
  let index = 0;
  let query = "";
  let busy = false;

  function fill() {
    clear(plates);
    clear(quote);
    clear(meta);
    clear(dots);
    if (!items.length) {
      quote.appendChild(h("p", {}, "No evidence to show yet."));
      count.textContent = "";
      prev.disabled = next.disabled = true;
      return;
    }
    const item = items[index];
    quote.appendChild(h("p", {}, item.e.sentence));
    meta.append(...[
      h("span", { class: `chip st-${item.label}${item.stub ? " is-stub" : ""}` }, item.label),
      h("span", {}, ["in ", h("span", { class: "mono" }, item.e.citing_doc)]),
      item.e.citing_bench ? h("span", {}, `${item.e.citing_bench}-judge bench`) : null,
      typeof item.e.confidence === "number" ? h("span", {}, `confidence ${f2(item.e.confidence)}`) : null,
      item.stub ? h("span", { class: "tag is-stub" }, "stub, not real data") : null,
      h("button", { class: "linklike", type: "button", onclick: () => openReader(item.e.citing_doc, "", query, { passage: item.e.sentence }) }, "Show it in the judgment"),
    ].filter(Boolean));
    for (let k = Math.min(3, items.length) - 1; k >= 0; k -= 1) {
      const it = items[(index + k) % items.length];
      plates.appendChild(h("div", { class: "plate", vars: { "--k": String(k), "--st": statusVar(it.label) } }, [
        h("span", { class: "mono-gram" }, monogram(it.r.title || it.r.doc_id)),
        h("span", { class: "p-label" }, it.r.title || it.r.doc_id),
      ]));
    }
    items.forEach((_, i) => dots.appendChild(h("i", { class: i === index ? "is-on" : null })));
    count.textContent = `${index + 1} / ${items.length}`;
    prev.disabled = next.disabled = items.length < 2;
  }

  function layoutPlates(animate, dir) {
    const list = $$(".plate", plates);
    list.forEach((p) => { const k = Number(p.style.getPropertyValue("--k")); p.style.opacity = String(1 - k * 0.28); });
    if (!gsap || !motionOn() || !animate) { list.forEach((p) => { const k = Number(p.style.getPropertyValue("--k")); p.style.transform = `scale(${1 - k * 0.06})`; }); return; }
    list.forEach((p) => {
      const k = Number(p.style.getPropertyValue("--k"));
      gsap.fromTo(p, { x: k === 0 ? dir * 70 : dir * 26, opacity: 0, scale: 1 - k * 0.06 - 0.05 }, { x: 0, opacity: 1 - k * 0.28, scale: 1 - k * 0.06, duration: 0.9, delay: k * 0.06, ease: "power3.out" });
    });
  }

  async function go(dir) {
    if (busy || items.length < 2) return;
    busy = true;
    const targets = [quote, meta];
    if (gsap && motionOn()) await gsap.to(targets, { opacity: 0, x: -dir * 28, duration: 0.26, ease: "power2.in" });
    index = (index + dir + items.length) % items.length;
    fill();
    layoutPlates(true, dir);
    if (gsap && motionOn()) await gsap.fromTo(targets, { opacity: 0, x: dir * 28 }, { opacity: 1, x: 0, duration: 0.6, stagger: 0.05, ease: "power3.out", clearProps: "transform,opacity" });
    busy = false;
  }

  prev.addEventListener("click", () => go(-1));
  next.addEventListener("click", () => go(1));
  carousel.addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") go(-1); else if (e.key === "ArrowRight") go(1); });

  // drag or swipe sideways
  let startX = null;
  carousel.addEventListener("pointerdown", (e) => { if (e.target.closest("button, a")) return; startX = e.clientX; });
  window.addEventListener("pointerup", (e) => {
    if (startX === null) return;
    const dx = e.clientX - startX;
    startX = null;
    if (Math.abs(dx) > 48) go(dx < 0 ? 1 : -1);
  });

  window.addEventListener("lexshift:results", (e) => {
    items = gather(e.detail.data, e.detail.config);
    index = 0;
    query = e.detail.data.query;
    sub.textContent = items.length
      ? `Treatment evidence from the results for “${query}”, strongest first. The treating sentence sits inside the quoted window.`
      : `The results for “${query}” carry no treatment evidence: no later judgment in the corpus was found to overrule, doubt or follow them.`;
    fill();
    layoutPlates(false, 1);
  });
  fill();
}
