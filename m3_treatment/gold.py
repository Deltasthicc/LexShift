"""Gold set for treatment labels: data/treatment_gold.csv (about 150-300 windows, two labellers on a subset).

Cue words may only be used to FIND candidate windows (so rare classes such as overruled are represented); the
label is assigned by reading. Report Cohen's kappa on the doubly-labelled subset.

Workflow (nothing here assigns a label):
  1. python -m m3_treatment.gold sample --n 250 --double 60
       writes data/labelling/m3_L1.csv (all windows) and m3_L2.csv (the double-labelled subset), blank gold_label
       columns, plus candidates.csv (provenance: citing doc, cited case, cue bucket; labellers should not open it).
  2. Each labeller fills gold_label in their own sheet by reading the window (see LABELLING_GUIDE.md).
  3. python -m m3_treatment.gold merge
       checks both sheets, reports Cohen's kappa, writes disagreements.csv for adjudication (fill `adjudicated`),
       and writes data/treatment_gold.csv: one row per (window, labeller), plus an "ADJ" row for each adjudicated
       disagreement.
The label used for evaluation is the ADJ row if present, else the labellers' common label; an unadjudicated
disagreement is left out of evaluation and counted.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from common.schema import TREATMENT_GOLD_COLUMNS, TREATMENT_LABELS, GoldWindow, SchemaError

# Cue patterns are used ONLY to stratify the candidate sample so rare treatments appear; they never label anything.
CUE_BUCKETS: list[tuple[str, re.Pattern[str]]] = [
    ("overrule", re.compile(r"over-?rul|per\s+incuriam|(?:no\s+longer|not)\s+(?:a\s+)?good\s+law", re.I)),
    ("doubt", re.compile(r"doubt|reconsider|larger\s+bench|criticis|disapprov|cannot\s+agree|not\s+(?:correct|sound)", re.I)),
    ("distinguish", re.compile(r"distinguish|not\s+applicable|inapplicable|no\s+application|different\s+facts", re.I)),
    ("follow", re.compile(r"follow|relied|rely|relying|approv|applied|affirm|reiterat", re.I)),
]
ADJUDICATOR = "ADJ"
SHEET_COLUMNS = ("window_id", "window", "gold_label", "labeller", "notes")


def window_id(citing_doc: str, start: int, end: int) -> str:
    return hashlib.sha1(f"{citing_doc}|{start}|{end}".encode("utf-8")).hexdigest()[:12]


def cue_bucket(marked_window: str) -> str:
    from m3_treatment.classifier import local_context

    near = local_context(marked_window)
    for name, pat in CUE_BUCKETS:
        if pat.search(near):
            return name
    return "none"


def _labelling_dir() -> Path:
    from common.config import ROOT, load_config

    return ROOT / load_config().get("m3_treatment", {}).get("labelling_dir", "data/labelling")


def _gold_path() -> Path:
    from common.config import resolve_path

    return resolve_path("treatment_gold")


def sample_candidate_windows(n: int, seed: int = 0, mentions: list[dict] | None = None) -> list[dict]:
    """Class-balanced candidate windows for hand labelling (a labelling helper, not a labeller).

    Draws evenly from the cue buckets (overrule, doubt, distinguish, follow, none); a bucket with too few candidates
    gives its share to the others, so every rare candidate is kept. Appeal-history mentions are skipped (they are excluded from treatment anyway); duplicate windows are dropped.
    """
    if mentions is None:
        from m3_treatment.pipeline import load_mentions

        mentions = load_mentions()
    pool: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for m in mentions:
        if m.get("is_appeal_history") or m.get("is_self"):
            continue
        w = m["marked_window"]
        if w in seen:
            continue
        seen.add(w)
        b = cue_bucket(w)
        pool[b].append({**m, "bucket": b, "window_id": window_id(m["citing_doc"], m["start"], m["end"])})
    rng = random.Random(seed)
    for b in pool:
        pool[b].sort(key=lambda r: r["window_id"])
        rng.shuffle(pool[b])
    quota = _water_fill({b: len(rows) for b, rows in pool.items()}, n)
    chosen = [r for b in sorted(quota) for r in pool[b][: quota[b]]]
    rng.shuffle(chosen)
    return chosen


def _water_fill(available: dict[str, int], n: int) -> dict[str, int]:
    """Split n evenly over the buckets; space a small bucket cannot use goes to the others (so rare ones are kept)."""
    quota = {b: 0 for b in available}
    left = min(n, sum(available.values()))
    open_ = sorted(b for b, k in available.items() if k > 0)
    while left > 0 and open_:
        share = max(1, left // len(open_))
        for b in list(open_):
            take = min(share, available[b] - quota[b], left)
            quota[b] += take
            left -= take
            if quota[b] == available[b]:
                open_.remove(b)
            if left == 0:
                break
    return quota


def write_sheets(cands: list[dict], out_dir: Path, double: int, seed: int = 0) -> dict[str, Path]:
    from common.io import write_delimited

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"L1": out_dir / "m3_L1.csv", "L2": out_dir / "m3_L2.csv", "provenance": out_dir / "candidates.csv"}
    for p in paths.values():
        if p.exists():
            raise FileExistsError(f"{p} exists; a labelling round is never overwritten (move it away first)")
    rng = random.Random(seed + 1)
    subset = sorted(rng.sample(range(len(cands)), min(double, len(cands))))
    sheet = lambda rows, who: [{"window_id": r["window_id"], "window": r["marked_window"], "gold_label": "", "labeller": who, "notes": ""} for r in rows]  # noqa: E731
    write_delimited(paths["L1"], SHEET_COLUMNS, sheet(cands, "L1"))
    write_delimited(paths["L2"], SHEET_COLUMNS, sheet([cands[i] for i in subset], "L2"))
    prov_cols = ("window_id", "citing_doc", "cited_doc", "cited_raw", "kind", "bucket")
    write_delimited(paths["provenance"], prov_cols, [{c: r.get(c) for c in prov_cols} for r in cands])
    return paths


# ----------------------------------------------------------------------------------------------------------------
# Agreement and merging
# ----------------------------------------------------------------------------------------------------------------
def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e): observed agreement corrected for the agreement expected by chance."""
    if len(labels_a) != len(labels_b):
        raise ValueError("the two label lists must be the same length")
    n = len(labels_a)
    if n == 0:
        raise ValueError("no doubly-labelled windows")
    p_o = sum(a == b for a, b in zip(labels_a, labels_b)) / n
    ca, cb = Counter(labels_a), Counter(labels_b)
    p_e = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if p_e == 1.0:
        return 1.0
    return (p_o - p_e) / (1 - p_e)


class MergeError(ValueError):
    """The labelling round is not in a state that can be merged. Nothing was written."""


def _read_sheet(path: Path, who: str) -> tuple[list[dict], list[str]]:
    """(labelled rows, every window_id in the sheet). A missing sheet, a duplicate id or a bad label is an error.

    Read as UTF-8 with an optional byte-order mark: Excel's "CSV UTF-8" adds one, which would otherwise hide the
    `window_id` column.
    """
    import csv

    if not path.exists():
        raise MergeError(
            f"{path} is missing. `gold sample` always writes both sheets (the second one even when empty); restore it "
            "before merging, otherwise the second labeller's work and every adjudication would be lost."
        )
    rows, ids, seen = [], [], set()
    with open(path, encoding="utf-8-sig", newline="") as fh:
        sheet = list(csv.DictReader(fh))
    for i, r in enumerate(sheet, start=2):
        wid = (r.get("window_id") or "").strip()
        if not wid or wid in seen:
            raise MergeError(f"{path.name} line {i}: missing or duplicate window_id {wid!r}")
        seen.add(wid)
        ids.append(wid)
        if (r.get("labeller") or who).strip() != who:
            raise MergeError(f"{path.name} line {i}: labeller {r['labeller']!r}, expected {who!r} (sheets swapped?)")
        label = (r.get("gold_label") or "").strip().lower()
        if not label:
            continue
        if label not in TREATMENT_LABELS:
            raise SchemaError(f"{path.name} line {i}: label {label!r} not in {TREATMENT_LABELS}")
        rows.append({"window_id": wid, "window": r["window"], "gold_label": label, "labeller": who})
    return rows, ids


def _write_atomic(path: Path, columns, rows) -> None:
    from common.io import write_delimited

    tmp = path.with_name(path.name + ".tmp")
    write_delimited(tmp, columns, rows)
    os.replace(tmp, path)


def merge(out_dir: Path | None = None, gold_path: Path | None = None, allow_incomplete: bool = False) -> dict:
    """Combine the labelled sheets (and any adjudications) into treatment_gold.csv; return the agreement report.

    Refuses, writing nothing, when: a sheet is missing; the second sheet has windows the first does not; any window
    is still blank (unless `allow_incomplete`, which writes only the labelled rows); or the merge would drop an
    adjudication someone already typed into disagreements.csv.
    """
    from common.io import read_delimited

    out_dir = out_dir or _labelling_dir()
    gold_path = gold_path or _gold_path()
    l1, ids1 = _read_sheet(out_dir / "m3_L1.csv", "L1")
    l2, ids2 = _read_sheet(out_dir / "m3_L2.csv", "L2")
    extra = set(ids2) - set(ids1)
    if extra:
        raise MergeError(f"m3_L2.csv has {len(extra)} windows that are not in m3_L1.csv (e.g. {sorted(extra)[0]})")
    blank = {"L1": len(ids1) - len(l1), "L2": len(ids2) - len(l2)}
    if any(blank.values()) and not allow_incomplete:
        detail = ", ".join(f"{who}: {n} of {len(ids)} windows blank" for (who, n), ids in zip(blank.items(), (ids1, ids2)) if n)
        raise MergeError(f"labelling is not finished ({detail}). Finish it, or pass --allow-incomplete to merge only the labelled rows.")

    a = {r["window_id"]: r for r in l1}
    b = {r["window_id"]: r for r in l2}
    both = sorted(set(a) & set(b))
    report = {"L1": len(a), "L2": len(b), "blank_L1": blank["L1"], "blank_L2": blank["L2"], "double": len(both)}
    if both:
        report["kappa"] = cohens_kappa([a[k]["gold_label"] for k in both], [b[k]["gold_label"] for k in both])
        report["agreement"] = sum(a[k]["gold_label"] == b[k]["gold_label"] for k in both) / len(both)
    disagree = [k for k in both if a[k]["gold_label"] != b[k]["gold_label"]]

    dis_path = out_dir / "disagreements.csv"
    adjudicated: dict[str, str] = {}
    if dis_path.exists():
        for r in read_delimited(dis_path):
            lab = (r.get("adjudicated") or "").strip().lower()
            if lab:
                if lab not in TREATMENT_LABELS:
                    raise SchemaError(f"disagreements.csv: adjudicated label {lab!r} not in {TREATMENT_LABELS}")
                adjudicated[r["window_id"]] = lab
    orphaned = sorted(set(adjudicated) - set(disagree))
    if orphaned:
        raise MergeError(
            f"disagreements.csv has {len(orphaned)} typed adjudication(s) that are no longer disagreements "
            f"(e.g. {orphaned[0]}): a sheet changed since the last merge. Nothing was written; check the sheets, "
            "or move those rows out of disagreements.csv yourself if they are really obsolete."
        )

    rows_dis = [
        {"window_id": k, "window": a[k]["window"], "L1": a[k]["gold_label"], "L2": b[k]["gold_label"], "adjudicated": adjudicated.get(k, "")}
        for k in disagree
    ]
    adj_rows = [{"window_id": k, "window": a[k]["window"], "gold_label": adjudicated[k], "labeller": ADJUDICATOR} for k in disagree if k in adjudicated]
    out = l1 + l2 + adj_rows
    for r in out:
        GoldWindow.from_dict(r)
    _write_atomic(dis_path, ("window_id", "window", "L1", "L2", "adjudicated"), rows_dis)
    _write_atomic(gold_path, TREATMENT_GOLD_COLUMNS, out)
    report["disagreements"] = len(disagree)
    report["unadjudicated"] = len([k for k in disagree if k not in adjudicated])
    report["written"] = len(out)
    return report


def load_gold(path: Path | None = None) -> list[GoldWindow]:
    from common.io import read_delimited

    path = path or _gold_path()
    if not path.exists():
        return []
    return [GoldWindow.from_dict(r) for r in read_delimited(path)]


def final_labels(rows: list[GoldWindow]) -> list[tuple[str, str]]:
    """(marked window, label) per window: the ADJ label if any, else the labellers' common label.

    Windows whose labellers disagree and that have no adjudication are left out.
    """
    by_id: dict[str, list[GoldWindow]] = defaultdict(list)
    for r in rows:
        by_id[r.window_id].append(r)
    out = []
    for wid in sorted(by_id):
        group = by_id[wid]
        adj = [r for r in group if r.labeller == ADJUDICATOR]
        labels = {r.gold_label for r in group if r.labeller != ADJUDICATOR}
        if adj:
            out.append((group[0].window, adj[-1].gold_label))
        elif len(labels) == 1:
            out.append((group[0].window, labels.pop()))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m m3_treatment.gold", description="M3 gold-set tooling (never assigns labels)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="write blank labelling sheets from data/processed/m3_mentions.jsonl")
    s.add_argument("--n", type=int, default=250)
    s.add_argument("--double", type=int, default=60, help="windows also given to the second labeller")
    s.add_argument("--seed", type=int, default=0)
    mg = sub.add_parser("merge", help="check sheets, report kappa, write treatment_gold.csv")
    mg.add_argument("--allow-incomplete", action="store_true", help="merge only the labelled rows while labelling continues")
    args = ap.parse_args(argv)
    if args.cmd == "sample":
        try:
            cands = sample_candidate_windows(args.n, args.seed)
            paths = write_sheets(cands, _labelling_dir(), args.double, args.seed)
        except (FileNotFoundError, FileExistsError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{len(cands)} candidate windows; buckets {dict(Counter(c['bucket'] for c in cands))}")
        for k, p in paths.items():
            print(f"  {k}: {p}")
        print("Label by reading each window; see m3_treatment/LABELLING_GUIDE.md. Do not open candidates.csv while labelling.")
        return 0
    try:
        rep = merge(allow_incomplete=args.allow_incomplete)
    except MergeError as exc:
        print(f"merge refused: {exc}")
        return 1
    print(" ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in rep.items()))
    if rep.get("unadjudicated"):
        print("Fill the `adjudicated` column of disagreements.csv by re-reading each window, then run merge again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
