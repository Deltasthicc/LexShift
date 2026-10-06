// The only module that talks to the server. Every call returns parsed JSON or throws an ApiError with a readable message.

export class ApiError extends Error {
  constructor(message, kind = "network", status = 0) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { cache: "no-store", ...options });
  } catch {
    throw new ApiError("Cannot reach the LexShift server. Is `python -m app.server` still running?", "network", 0);
  }
  let body = null;
  try { body = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    const err = body && body.error ? body.error : {};
    throw new ApiError(err.message || `The server answered ${response.status}.`, err.kind || "server", response.status);
  }
  return body;
}

const query = (params) => {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null && value !== "") usp.set(key, value);
  const text = usp.toString();
  return text ? `?${text}` : "";
};

export const api = {
  status: () => request("/api/status"),
  compare: (q, date, k) => request(`/api/compare${query({ q, date, k })}`),
  search: (q, date, k, config) => request(`/api/search${query({ q, date, k, config })}`),
  doc: (id, maxChars) => request(`/api/doc${query({ id, max_chars: maxChars })}`),
  examples: () => request("/api/examples"),
  corpus: (n) => request(`/api/corpus${query({ n })}`),
  evaluation: () => request("/api/evaluation"),
  judgeRounds: () => request("/api/judge/rounds"),
  judgeSheet: (round, judge) => request(`/api/judge/sheet${query({ round, judge })}`),
  judgeGrade: (payload) =>
    request("/api/judge/grade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
};
