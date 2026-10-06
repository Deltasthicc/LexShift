// The judgment reader: a slide-over panel that shows a judgment's text with the query's words marked.
import { api } from "./api.js";
import { $, clear, h, formatDate, plural } from "./dom.js";

const STOP = new Set(["and", "or", "not", "the", "of", "to", "in", "a", "an", "for", "on", "under", "is", "are", "by", "with", "s", "p"]);
let opener = null;
let current = null;

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

function trap(event, root) {
  if (event.key !== "Tab") return;
  const focusable = Array.from(root.querySelectorAll("button, [href], input, select, textarea, summary, [tabindex]:not([tabindex='-1'])")).filter((el) => !el.disabled && el.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

export function openDrawer(panel, closeButton, onClose) {
  opener = document.activeElement;
  $("#scrim").hidden = false;
  panel.hidden = false;
  document.body.style.setProperty("overflow", "hidden");
  const keys = (event) => {
    if (event.key === "Escape") close();
    else trap(event, panel);
  };
  const close = () => {
    panel.hidden = true;
    $("#scrim").hidden = true;
    document.body.style.removeProperty("overflow");
    document.removeEventListener("keydown", keys);
    $("#scrim").onclick = null;
    if (onClose) onClose();
    if (opener && opener.focus) opener.focus();
  };
  document.addEventListener("keydown", keys);
  $("#scrim").onclick = close;
  closeButton.onclick = close;
  closeButton.focus();
  return close;
}

export async function openReader(docId, titleHint = "", query = "") {
  const panel = $("#reader");
  const body = $("#reader-body");
  const title = $("#reader-title");
  const meta = $("#reader-meta");
  title.textContent = titleHint || docId;
  meta.textContent = docId;
  clear(body);
  body.appendChild(h("div", { class: "skeleton" }));
  current = openDrawer(panel, $("#reader-close"));
  const terms = termsOf(query);
  const regex = terms.length ? new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi") : null;

  async function load(maxChars) {
    try {
      const doc = await api.doc(docId, maxChars);
      title.textContent = doc.title || docId;
      meta.textContent = [doc.doc_id, formatDate(doc.date), doc.bench_size ? `${doc.bench_size}-judge bench` : ""].filter(Boolean).join("  ·  ");
      clear(body);
      const facts = h("dl", { class: "facts" });
      const add = (k, v) => { if (v && String(v).length) { facts.appendChild(h("dt", {}, k)); facts.appendChild(h("dd", {}, v)); } };
      add("Judges", doc.judges.join(", "));
      add("Cited as", doc.reporter_citations.join("; "));
      add("Length", `${doc.characters.toLocaleString("en-IN")} characters`);
      if (terms.length) add("Marked", `${plural(terms.length, "word")} from your query: ${terms.join(", ")}`);
      body.appendChild(facts);
      const text = h("div", { class: "doc-text" }, paragraphs(doc.text).map((p) => h("p", {}, marked(p, regex))));
      body.appendChild(text);
      if (doc.truncated) {
        body.appendChild(h("button", { class: "btn btn-secondary btn-small", type: "button", onclick: () => load(400000) }, "Show the rest of the judgment"));
      }
    } catch (err) {
      clear(body);
      body.appendChild(h("div", { class: "empty" }, h("strong", {}, "This judgment cannot be shown"), err.message));
    }
  }
  await load(60000);
}

export function closeReader() { if (current) current(); }
