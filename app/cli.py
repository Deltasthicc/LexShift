"""Command-line demo: ranked precedent search with the score breakdown and the evidence behind every status.

    python -m app.cli "BNS 103 murder" --offence-date 2025-01-10
    python -m app.cli "common intention" --config b0 -k 5 --verbose
    python -m app.cli "dowry death" --json

The output shows treatment signals with evidence, not legal advice. When any signal comes from a fixed-value stub the run is
labelled as such on screen and in every JSON result.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.docmeta import describe, load_doc_meta  # noqa: E402
from common.config import load_config  # noqa: E402
from common.providers import Providers, load_providers  # noqa: E402
from common.schema import Result  # noqa: E402
from m4_rank.explain import split_explanation  # noqa: E402
from m4_rank.rank import ContractViolation, rank  # noqa: E402
from m4_rank.weights import active_signals, canonical_config, load_weights, weights_source  # noqa: E402

BAR_WIDTH = 20
NOTE = (
    "These are treatment signals with evidence, produced by automated analysis of later judgments. They are not legal\n"
    "advice. A signal can be wrong, can apply to one point of a judgment only, or can be superseded by a pending\n"
    "reference to a larger bench: read the cited sentences and the judgments before relying on any of it."
)


def bar(value: float, width: int = BAR_WIDTH) -> str:
    filled = max(0, min(width, round(value * width)))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def banner(stubbed: list[str]) -> str:
    return (f"*** STUB MODE: {', '.join(stubbed)} come from fixed-value stand-ins, not from real data. "
            "This output is NOT a result. ***")


def render(results: list[Result], meta: dict, weights: dict[str, float]) -> str:
    lines: list[str] = []
    for i, r in enumerate(results, start=1):
        label = describe(meta.get(r.doc_id))
        lines.append(f"{i:>2}. {r.doc_id}   final {r.final:.3f}" + (f"   {label}" if label else ""))
        for piece in split_explanation(r.explanation):
            name = piece.split(" ", 1)[0]
            lines.append(f"      {name:<6} {bar(getattr(r, name))}  {piece[len(name) + 1:]}")
        for ev in r.evidence:
            quoted = textwrap.shorten(ev["sentence"], width=220, placeholder=" ...")
            lines.append(f"      evidence: {ev['label']} in {ev['citing_doc']}: \"{quoted}\"")
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n\n")[0])
    ap.add_argument("query", help="free text, a section such as 'BNS 103', or a Boolean/proximity query (M1 syntax)")
    ap.add_argument("--offence-date", help="date of the offence (YYYY-MM-DD): decides IPC (before 2024-07-01) or BNS")
    ap.add_argument("--config", default="full", help="b0 (BM25 only), b1 (+continuity) or full (default)")
    ap.add_argument("-k", type=int, default=10, help="results to show (default 10)")
    ap.add_argument("--verbose", action="store_true", help="also show the query parse, weights and raw signals")
    ap.add_argument("--json", action="store_true", help="print results as JSON on stdout")
    return ap.parse_args(argv)


def run(args: argparse.Namespace, providers: Providers | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # never crash on a console that cannot show a character
    cfg = load_config()
    try:
        config = canonical_config(args.config, cfg)
        providers = providers or load_providers(cfg)
        weights = load_weights(config, cfg)
        results = rank(args.query, args.offence_date, k=args.k, config=config, providers=providers)
    except NotImplementedError as exc:
        print(f"{exc}\nThat function is not built yet. Keep its switch under `stubs:` in common/config.yaml set to true "
              "to run the interface against the labelled stand-ins.", file=sys.stderr)
        return 2
    except ContractViolation as exc:
        print(f"A module returned data that breaks its contract: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2

    used = [s for s in ("rel", "cont", "health", "auth") if s in active_signals(weights)]
    stubbed = providers.stubbed_signals(used)
    meta = load_doc_meta()

    if args.json:
        if stubbed:
            print(banner(stubbed), file=sys.stderr)
        payload = [{**r.to_dict(), "title": describe(meta.get(r.doc_id)) or None} for r in results]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    when = f"  |  offence date {args.offence_date}" if args.offence_date else ""
    print(f"LexShift  |  config {config}  |  top {len(results)}{when}")
    print(f"query: {args.query}\n")
    if stubbed:
        print(banner(stubbed) + "\n")
    if args.verbose:
        qs = providers.parse_query(args.query, args.offence_date)
        refs = ", ".join(f"{r.act} {r.section}" + (f" -> {r.offence_id}" if r.offence_id else "") for r in qs.refs) or "none found"
        print(f"providers: {providers.describe()}")
        print(f"weights from {weights_source(config, cfg)}: " + ", ".join(f"{s} {weights[s]:.2f}" for s in used))
        print(f"query statutes: governing act {qs.governing_act or 'unknown'}; sections: {refs}")
        for note in qs.notes:
            print(f"  note: {note}")
        print()
    if not results:
        print("No results.")
    else:
        print(render(results, meta, weights))
        if args.verbose:
            print("raw signals before normalisation:")
            for r in results:
                print(f"  {r.doc_id}: " + ", ".join(f"{k} {v:.3f}" for k, v in r.raw.items()))
            print()
    print(NOTE)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
