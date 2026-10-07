"""Sanity check of our BM25 against a library BM25, and latency. Run: python -m m1_index.benchmark

The library (rank_bm25.BM25Okapi) is used here and nowhere else: it is a cross-check of `scoring.bm25_scores`, never part of the search
path. The corpus is data/processed/judgments.jsonl, tokenised once with our tokenizer; our index and the library's corpus are built
from the very same token lists (a document is its zones joined), so a difference in the scores can only come from the scoring formula.

For each query it reports the overlap of the two top-10 lists, the Spearman rank correlation between the two scorings over the top
100, and the median latency of ours, of the library and of the zone-weighted `search()`. The result is written to
m1_index/reports/benchmark.md; every number in it comes from the run.

Why the rankings differ slightly. Both use the same BM25 term-frequency part, tf (k1 + 1) / (tf + k1 (1 - b + b dl / avgdl)); they differ in the
idf. rank_bm25 uses ln((N - n + 0.5) / (n + 0.5)), which tends to 0 as the document frequency n approaches N/2 and is negative beyond it;
it then replaces a negative idf by epsilon times the average idf over the vocabulary, one constant for every such term. Ours uses
ln(1 + (N - n + 0.5) / (n + 0.5)), which is positive for every term and decreases smoothly. They agree on rare terms (the "1 +"
matters little when n is small) and disagree on terms that occur in about half the documents or more, where the library gives them
almost no weight just below N/2 and a constant above it; that reorders documents when a query mixes such terms with rare ones.
"""

from __future__ import annotations

import argparse
import datetime
import importlib
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from m1_index.index import JUDGMENTS_PATH, ROOT, IndexBuilder, memoised_tokenizer

REPORT_PATH = ROOT / "m1_index" / "reports" / "benchmark.md"
K1, B = 1.2, 0.75
QUERIES = (
    "murder", "bail", "cheating", "conspiracy", "dowry", "acquittal",
    "302", "section 302", "section 420 ipc", "498-a",
    "anticipatory bail", "common intention", "circumstantial evidence", "dying declaration",
    "quashing of FIR under section 482", "punishment for murder under section 103 BNS",
)


# ------------------------------------------------------------------------------------------------ pure helpers (tested by hand)
def overlap_at_k(a: Sequence[str], b: Sequence[str], k: int) -> float:
    """|top-k(a) & top-k(b)| / k_eff, where k_eff is k, or fewer when a list has fewer than k items (1.0 for two empty lists)."""
    top_a, top_b = list(a)[:k], list(b)[:k]
    k_eff = min(k, max(len(top_a), len(top_b)))
    if k_eff == 0:
        return 1.0
    return len(set(top_a) & set(top_b)) / k_eff


def average_ranks(values: Sequence[float]) -> list[float]:
    """Ranks 1..n of the values in increasing order; equal values share the mean of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for p in range(i, j + 1):
            ranks[order[p]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation: the Pearson correlation of the average ranks. nan when either side is constant or has < 2 items."""
    if len(xs) != len(ys):
        raise ValueError("the two score lists must have the same length")
    if len(xs) < 2:
        return float("nan")
    rx, ry = average_ranks(xs), average_ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var_x, var_y = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return float("nan")
    return cov / math.sqrt(var_x * var_y)


def median_ms(fn: Callable[[], object], repeats: int) -> float:
    """Median wall-clock milliseconds of `repeats` calls of fn (after one call that is not counted)."""
    fn()
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times)


def fmt(x: float, digits: int = 3) -> str:
    return "n/a" if x != x else f"{x:.{digits}f}"


# ------------------------------------------------------------------------------------------------ the run
def load_corpus(path: Path, limit: int | None):
    """Build our index and the library's corpus from the same tokens, one judgment at a time. Returns (index, library, n_tokens)."""
    from rank_bm25 import BM25Okapi

    from m1_index.tokenizer import tokenize

    builder = IndexBuilder()
    tokens_total = 0

    def stream():
        nonlocal tokens_total
        with open(path, encoding="utf-8") as fh:
            n = 0
            for line in fh:
                if not line.strip():
                    continue
                if limit is not None and n >= limit:
                    break
                rec = json.loads(line)
                n += 1
                zone_tokens = {zone: tokenize(text) for zone, text in (rec.get("zones") or {}).items()}
                date = rec.get("date")
                meta = {"year": int(date[:4]) if date and len(date) >= 4 else None, "bench_size": rec.get("bench_size"),
                        "title": rec.get("title"), "date": date}
                builder.add_tokens(rec["doc_id"], meta, zone_tokens)
                flat = [t for toks in zone_tokens.values() for t in toks]
                tokens_total += len(flat)
                yield flat

    with memoised_tokenizer():
        library = BM25Okapi(stream(), k1=K1, b=B)  # consumes the stream: the library's corpus and our index see the same tokens
    return builder.finish(), library, tokens_total


def run(judgments: Path, repeats: int, limit: int | None, queries: Sequence[str] = QUERIES) -> dict:
    import numpy as np

    from m1_index import scoring
    from m1_index.searcher import RankedSearchEngine
    from m1_index.tokenizer import tokenize

    started = time.perf_counter()
    index, library, n_tokens = load_corpus(judgments, limit)
    build_s = time.perf_counter() - started
    engine = RankedSearchEngine(index=index)
    ids = index.doc_ids
    rows = []
    for query in queries:
        tokens = tokenize(query)
        ours = scoring.bm25_scores(tokens, index, k1=K1, b=B)
        lib_scores = library.get_scores(tokens)
        lib = {ids[i]: float(s) for i, s in enumerate(lib_scores) if s > 0}
        top_ours = [d for d, _ in scoring.top_k(ours, 100)]
        top_lib = [d for d, _ in scoring.top_k(lib, 100)]
        union = sorted(set(top_ours) | set(top_lib))
        rho = spearman([ours.get(d, 0.0) for d in union], [lib.get(d, 0.0) for d in union])
        rows.append({
            "query": query, "tokens": tokens, "matches_ours": len(ours), "matches_library": len(lib),
            "overlap10": overlap_at_k(top_ours, top_lib, 10), "overlap100": overlap_at_k(top_ours, top_lib, 100), "spearman100": rho,
            "top1_same": bool(top_ours) and bool(top_lib) and top_ours[0] == top_lib[0],
            "ms_ours": median_ms(lambda: scoring.top_k(scoring.bm25_scores(tokens, index, k1=K1, b=B), 100), repeats),
            "ms_library": median_ms(lambda: np.argsort(library.get_scores(tokens))[::-1][:100], repeats),
            "ms_search": median_ms(lambda: engine.search(query, k=100), repeats),
        })
    n = index.num_docs
    token_rows = []
    for t in dict.fromkeys(t for q in queries for t in tokenize(q)):
        df = index.df(t)
        if df:
            token_rows.append({"token": t, "df": df, "fraction": df / n, "ours": math.log(1.0 + (n - df + 0.5) / (df + 0.5)),
                               "library": library.idf[t], "floored": 2 * df > n})
    idf_rows = []
    for frac in (0.001, 0.01, 0.1, 0.3, 0.5, 0.7, 0.9):
        df = max(1, round(frac * n))
        idf_rows.append({"df": df, "fraction": df / n, "ours": math.log(1.0 + (n - df + 0.5) / (df + 0.5)),
                         "library": math.log(n - df + 0.5) - math.log(df + 0.5)})
    return {"docs": n, "tokens": n_tokens, "terms": index.stats["terms"], "build_s": build_s, "repeats": repeats, "rows": rows,
            "idf_rows": idf_rows, "token_rows": token_rows, "average_idf": library.average_idf, "epsilon": library.epsilon,
            "floor": library.epsilon * library.average_idf}


def render(result: dict, judgments: Path, limit: int | None) -> str:
    try:
        from importlib.metadata import version

        lib_version = version("rank_bm25")
    except Exception:  # noqa: BLE001 - a missing version string is not worth failing the report
        lib_version = "unknown"
    rows = result["rows"]

    def mean(key: str) -> float:
        return statistics.fmean(r[key] for r in rows)

    rhos = [r["spearman100"] for r in rows if r["spearman100"] == r["spearman100"]]
    try:
        shown = judgments.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        shown = judgments.as_posix()
    lines = [
        "# BM25 sanity check: our scoring against rank_bm25",
        "",
        "Generated by `python -m m1_index.benchmark`; every number below comes from that run.",
        "",
        f"* Date: {datetime.date.today().isoformat()}; Python {platform.python_version()}; rank_bm25 {lib_version}; {platform.system()}",
        f"* Corpus: `{shown}`" + (f" (first {limit} judgments)" if limit else "") + f", {result['docs']} judgments, {result['tokens']} tokens, "
        f"{result['terms']} distinct terms. Tokenising the corpus and building both indexes took {result['build_s']:.1f} s.",
        f"* Both sides use k1 = {K1}, b = {B} and the same token lists (a judgment is its zones joined). Ours: `scoring.bm25_scores`; "
        "the library: `rank_bm25.BM25Okapi.get_scores`.",
        f"* Latency is the median of {result['repeats']} runs after a warm-up. \"ours\" = `bm25_scores` + heap top-100; \"library\" = `get_scores` + "
        "argsort top-100; \"search()\" = the live zone-weighted `RankedSearchEngine.search(query, k=100)` (parsing, Boolean evaluation, "
        "zone-weighted BM25, heap top-100, `Hit` objects).",
        "* Overlap@10 = share of the top 10 that both rankings contain (documents with a score above 0 only). Spearman = rank correlation "
        "of the two scorings over the union of the two top-100 lists (ties share the mean rank).",
        "",
        "## Per query",
        "",
        "| query | tokens | matches | overlap@10 | overlap@100 | Spearman (top 100) | same top-1 | ours ms | library ms | search() ms |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['query']} | {' '.join(r['tokens'])} | {r['matches_ours']} / {r['matches_library']} | {fmt(r['overlap10'], 2)} | "
            f"{fmt(r['overlap100'], 2)} | {fmt(r['spearman100'])} | {'yes' if r['top1_same'] else 'no'} | "
            f"{r['ms_ours']:.2f} | {r['ms_library']:.2f} | {r['ms_search']:.2f} |")
    lines += [
        "",
        "## Summary",
        "",
        f"* Mean overlap@10: {mean('overlap10'):.3f}; mean overlap@100: {mean('overlap100'):.3f}; "
        f"mean Spearman over the top 100: {statistics.fmean(rhos):.3f}" + (f" (lowest {min(rhos):.3f})" if rhos else "") + ".",
        f"* The top-1 document is the same for {sum(r['top1_same'] for r in rows)} of {len(rows)} queries.",
        f"* Median latency over the queries: ours {statistics.median(r['ms_ours'] for r in rows):.2f} ms, library "
        f"{statistics.median(r['ms_library'] for r in rows):.2f} ms, zone-weighted search() {statistics.median(r['ms_search'] for r in rows):.2f} ms.",
        "",
        "## Why the rankings differ: the idf",
        "",
        "The term-frequency part is the same formula on both sides. The idf differs:",
        "",
        "* rank_bm25: `ln((N - n + 0.5) / (n + 0.5))`, which tends to 0 as the document frequency n approaches N/2 and is negative above it; a "
        f"negative idf is replaced by `epsilon * average idf` (epsilon = {result['epsilon']}, average idf over the vocabulary = "
        f"{result['average_idf']:.3f}, so the floor is {result['floor']:.3f}), one constant for every such term. So the library's idf is about 0 "
        f"just below N/2 and {result['floor']:.3f} just above it.",
        "* ours: `ln(1 + (N - n + 0.5) / (n + 0.5))`, positive for every term and smoothly decreasing, so a very common term still counts "
        "a little and is never switched off or promoted.",
        "",
        f"With N = {result['docs']}:",
        "",
        "| df | df / N | ours | rank_bm25 (before the floor) |",
        "|---|---|---|---|",
    ]
    for r in result["idf_rows"]:
        lines.append(f"| {r['df']} | {r['fraction']:.3f} | {r['ours']:.3f} | {r['library']:.3f} |")
    lines += [
        "",
        "The idf of the terms in the queries above (the library's value is the one it uses, after the floor):",
        "",
        "| token | df | df / N | ours | rank_bm25 | floored |",
        "|---|---|---|---|---|---|",
    ]
    for r in result["token_rows"]:
        lines.append(f"| {r['token']} | {r['df']} | {r['fraction']:.3f} | {r['ours']:.3f} | {r['library']:.3f} | {'yes' if r['floored'] else '-'} |")
    lines += [
        "",
        "Rare terms get nearly the same idf from both, so queries made of rare terms (section numbers, specific words) agree closely. "
        "Terms found in about half the documents or more are weighted differently, which reorders documents when a query mixes them with "
        "rare terms (compare the rows above with the overlap and Spearman columns). Documents with exactly equal scores are ordered by "
        "document id on our side and arbitrarily on the library's, which can also lower the overlap a little when many documents tie.",
        "",
        "## What this does and does not show",
        "",
        "It shows that our BM25 behaves like a standard implementation up to the idf variant, on the real corpus. It is not a relevance "
        "evaluation: no judged queries are involved. The library is used only in this module; the live `search()` never imports it.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare our BM25 with rank_bm25 on the real corpus and measure latency.")
    parser.add_argument("--judgments", type=Path, default=JUDGMENTS_PATH)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--limit", type=int, default=None, help="use only the first N judgments (less memory and time)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        importlib.import_module("rank_bm25")
    except ImportError:
        print("rank_bm25 is not installed, so the library comparison cannot run. Install it (a sanity-check dependency only, "
              "never used by search()):  pip install rank_bm25", file=sys.stderr)
        return 2
    if not args.judgments.exists():
        print(f"Error: {args.judgments} does not exist.", file=sys.stderr)
        return 1
    result = run(args.judgments, max(1, args.repeats), args.limit)
    report = render(result, args.judgments, args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8", newline="\n")
    rows = result["rows"]
    print(f"{len(rows)} queries over {result['docs']} judgments; mean overlap@10 {statistics.fmean(r['overlap10'] for r in rows):.3f}; "
          f"report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
