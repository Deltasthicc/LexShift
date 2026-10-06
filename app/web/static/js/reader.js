// The judgment reader: a slide-over panel with the judgment's text, the query's words marked, previous and next result, and, when it is
// opened from a piece of treatment evidence, the cited passage found, marked and scrolled to.
import { api } from "./api.js";
import { $, clear, formatDate, h, plural } from "./dom.js";
import { openPanel, toast } from "./ui.js";

const STOP = new Set(["and", "or", "not", "the", "of", "to", "in", "a", "an", "for", "on", "under", "is", "are", "by", "with", "s", "p"]);
let closePanel = null;
let session = 0;

export function termsOf(query) {
  const seen = new Set();
  for (const word of String(query || "").toLowerCase().match(/[a-z0-9]{2,}/g) || []) if (!STOP.has(word)) seen.add(word);
  return Array.from(seen);
}

function marked(text, regex) {
  if (!regex) return [text];
  const out = [];
  text.split(regex).forEach((piece, i) => out.push(i % 2 ? h("mark", {}, piece) : piece));
  return out;
}

function paragraphs(text) {
  let parts = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  if (parts.length < 6 && text.length > 3000) parts = text.split(/\n/).map((p) => p.trim()).filter(Boolean);
  return parts.slice(0, 2500);
}

const normal = (s) => String(s || "").toLowerCase().replace(/\[\[|\]\]/g, " ").replace(/[^a-z0-9]+/g, " ").trim();

/** The paragraph that holds the start (or, failing that, the middle) of a cited passage; -1 when it is not in this text. */
export function findPassage(paras, passage) {
  const n = normal(passage);
  if (n.length < 24) return -1;
  const probes = [n.slice(0, 70), n.slice(Math.max(0, Math.floor(n.length / 2) - 35), Math.floor(n.length / 2) + 35)];
  const normalised = paras.map(normal);
  for (const probe of probes) {
    const i = normalised.findIndex((p) => p.includes(probe));
    if (i !== -1) return i;
  }
  return -1;
}

export async function openReader(docId, titleHint = "", query = "", opts = {}) {
  const panel = $("#reader");
  const body = $("#reader-body");
  const title = $("#reader-title");
  const meta = $("#reader-meta");
  const prev = $("#reader-prev");
  const next = $("#reader-next");
  const mine = ++session;
  const list = opts.list || null;
  const index = list ? list.findIndex((x) => x.doc_id === docId) : -1;

  title.textContent = titleHint || docId;
  meta.textContent = docId;
  clear(body);
  body.appendChild(h("div", { class: "skeleton" }));
  const navigate = (step) => {
    const to = list[index + step];
    if (to) openReader(to.doc_id, to.title || "", query, { list });
  };
  [prev, next].forEach((b) => { b.hidden = !(list && index !== -1); });
  if (list && index !== -1) {
    prev.disabled = index === 0;
    next.disabled = index === list.length - 1;
    prev.onclick = () => navigate(-1);
    next.onclick = () => navigate(1);
  }
  if (!panel.classList.contains("is-open")) closePanel = openPanel(panel, $("#reader-close"), () => { session += 1; });
  const terms = termsOf(query);
  const regex = terms.length ? new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi") : null;

  async function load(maxChars, allowMore = true) {
    try {
      const doc = await api.doc(docId, maxChars);
      if (mine !== session) return;
      title.textContent = doc.title || docId;
      meta.textContent = [doc.doc_id, formatDate(doc.date), doc.bench_size ? `${doc.bench_size}-judge bench` : "", list && index !== -1 ? `result ${index + 1} of ${list.length}` : ""].filter(Boolean).join("  ·  ");
      clear(body);
      const paras = paragraphs(doc.text);
      const at = opts.passage ? findPassage(paras, opts.passage) : -1;
      if (opts.passage && at === -1 && doc.truncated && allowMore) { await load(400000, false); return; }
      if (opts.passage) {
        body.appendChild(h("div", { class: "evidence-banner" }, at === -1
          ? "The cited passage could not be located in this judgment's text (the citation window may have been cleaned differently), so it is shown from the start."
          : "The passage cited as treatment evidence is marked below."));
      }
      const facts = h("dl", { class: "facts" });
      const add = (k, v) => { if (v && String(v).length) { facts.appendChild(h("dt", {}, k)); facts.appendChild(h("dd", {}, v)); } };
      add("Judges", doc.judges.join(", "));
      add("Cited as", doc.reporter_citations.join("; "));
      add("Length", `${doc.characters.toLocaleString("en-IN")} characters`);
      if (terms.length && !opts.passage) add("Marked", `${plural(terms.length, "word")} from your query: ${terms.join(", ")}`);
      body.appendChild(facts);
      const nodes = paras.map((p, i) => h("p", { class: i === at ? "is-evidence" : null }, marked(p, i === at ? null : regex)));
      body.appendChild(h("div", { class: "doc-text" }, nodes));
      if (doc.truncated) {
        body.appendChild(h("button", { class: "btn btn-secondary btn-small", type: "button", onclick: () => load(400000, false) }, "Show the rest of the judgment"));
      }
      if (at !== -1) window.setTimeout(() => nodes[at].scrollIntoView({ behavior: "smooth", block: "center" }), 520);
      else body.scrollTop = 0;
    } catch (err) {
      if (mine !== session) return;
      clear(body);
      body.appendChild(h("div", { class: "empty" }, h("strong", {}, "This judgment cannot be shown"), err.message));
      toast(err.message, "warn");
    }
  }
  await load(60000);
}

export function closeReader() { if (closePanel) closePanel(); }
