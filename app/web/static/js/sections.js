// The editorial sections below the workspace: the evidence carousel (fed by the current results) and the corpus marquee.
import { api } from "./api.js";
import { $, clear, f2, h, show } from "./dom.js";

const MONO_SKIP = new Set(["v", "vs", "versus", "state", "of", "the", "and", "ors", "anr", "others", "union", "india", "m", "s", "etc"]);
const ORDER = { overruled: 0, doubted: 1, criticised: 1, criticized: 1, followed: 2, neutral: 3 };
const statusVar = (label) => (label === "overruled" ? "var(--st-over)" : label === "doubted" || label === "criticised" ? "var(--st-doubt)" : label === "followed" ? "var(--st-follow)" : "var(--st-neutral)");

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
  const plates = $("#plates");
  const quote = $("#quote");
  const meta = $("#quote-meta");
  const count = $("#car-count");
  const prev = $("#car-prev");
  const next = $("#car-next");
  const sub = $("#evidence-sub");
  let items = [];
  let index = 0;
  let query = "";

  function render() {
    clear(plates);
    clear(quote);
    clear(meta);
    if (!items.length) {
      quote.appendChild(h("p", {}, "No evidence to show yet."));
      count.textContent = "";
      prev.disabled = next.disabled = true;
      return;
    }
    const item = items[index];
    quote.appendChild(h("p", {}, item.e.sentence));
    // Element.append(null) would write the text "null", so absent parts are filtered out first
    meta.append(...[
      h("span", { class: `chip st-${item.label}${item.stub ? " is-stub" : ""}` }, item.label),
      h("span", {}, ["in ", h("span", { class: "mono" }, item.e.citing_doc)]),
      item.e.citing_bench ? h("span", {}, `${item.e.citing_bench}-judge bench`) : null,
      typeof item.e.confidence === "number" ? h("span", {}, `confidence ${f2(item.e.confidence)}`) : null,
      item.stub ? h("span", { class: "tag is-stub" }, "stub, not real data") : null,
    ].filter(Boolean));
    for (let k = 0; k < Math.min(3, items.length); k += 1) {
      const it = items[(index + k) % items.length];
      plates.appendChild(h("div", { class: "plate", vars: { "--k": String(k), "--st": statusVar(it.label) } }, [
        h("span", { class: "mono-gram" }, monogram(it.r.title || it.r.doc_id)),
        h("span", { class: "p-label" }, it.r.title || it.r.doc_id),
      ]));
    }
    count.textContent = `${index + 1} / ${items.length}`;
    prev.disabled = next.disabled = items.length < 2;
  }

  const step = (d) => { if (items.length > 1) { index = (index + d + items.length) % items.length; render(); } };
  prev.addEventListener("click", () => step(-1));
  next.addEventListener("click", () => step(1));
  $("#carousel").addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") step(-1); else if (e.key === "ArrowRight") step(1); });
  window.addEventListener("lexshift:results", (e) => {
    items = gather(e.detail.data, e.detail.config);
    index = 0;
    query = e.detail.data.query;
    sub.textContent = items.length
      ? `Treatment evidence from the results for “${query}”, strongest first. The treating sentence sits inside the quoted window.`
      : `The results for “${query}” carry no treatment evidence: no later judgment in the corpus was found to overrule, doubt or follow them.`;
    render();
  });
  render();
}

function yearOf(date) {
  const m = String(date || "").match(/(19|20)\d{2}/);
  return m ? m[0] : "";
}

export async function initMarquee(status) {
  const section = $("#corpus");
  try {
    const data = await api.corpus(40);
    if (!data.available || !data.titles.length) return;
    const track = $("#marquee-track");
    clear(track);
    const build = (hidden) => data.titles.map((t) => h("span", { class: "marquee-item", "aria-hidden": hidden ? "true" : null }, [t.title, h("small", {}, yearOf(t.date))]));
    track.append(...build(false), ...build(true));
    track.style.setProperty("--dur", `${Math.max(40, data.titles.length * 4)}s`);
    const total = status && status.corpus ? status.corpus.documents : null;
    $("#marquee-title").textContent = total
      ? `${data.titles.length} of the ${total.toLocaleString("en-IN")} judgments the search runs over`
      : "Judgments the search runs over";
    show(section, true);
  } catch {
    show(section, false);
  }
}
