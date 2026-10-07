"""One command that makes a fresh clone fully working, with every module real and nothing to download.

    python -m app.setup            # what everyone runs once after a clone or a pull (about 3 minutes, almost all of it the search index)
    python -m app.setup --pack     # maintainers only: pack the derived data after rebuilding it, then commit data/corpus/derived/

What it restores, each step only when it is missing or does not match the corpus:

1. the corpus, `data/processed/judgments.jsonl`, from the tracked `data/corpus/judgments.jsonl.xz` (SHA-256 checked);
2. the derived data the pages read, from the tracked `data/corpus/derived/*.jsonl.xz` (statute references, treatment and authority scores, titles,
   citation records), each checked against the row counts in `manifest.json`;
3. the search index, `data/processed/index/index.pkl.gz` (53 MB, so it is built here, not tracked): it is loaded to prove it is readable and to count its documents,
   and rebuilt if it is missing, unreadable (an interrupted build, an older format) or from another corpus.

It then checks that no `stubs:` switch is true and that no `LEXSHIFT_STUBS` override is set in your shell, and prints the command to start the interface.
Nothing here labels, grades or tunes anything: the packed treatment scores are the output of `make m3` from the committed Gemini label cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load_config, resolve_path  # noqa: E402

PACK_DIR = ROOT / "data" / "corpus" / "derived"
MANIFEST = PACK_DIR / "manifest.json"
DERIVED = ("doc_statutes", "doc_health", "doc_meta", "citations")  # keys of `paths:` in common/config.yaml
CORPUS_PACK = ROOT / "data" / "corpus" / "judgments.jsonl.xz"
CORPUS_SHA = ROOT / "data" / "corpus" / "judgments.jsonl.sha256"


def say(msg: str) -> None:
    print(msg, flush=True)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def count_rows(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for line in fh if line.strip())


def corpus_ok(cfg: dict) -> bool:
    path = resolve_path("judgments", cfg)
    return path.is_file() and CORPUS_SHA.is_file() and sha256_of(path) == CORPUS_SHA.read_text(encoding="utf-8").split()[0]


def pack_derived(cfg: dict | None = None) -> None:
    """Pack the derived data that exists now (after `make m3`, `make build-statutes`, `python -m app.docmeta`) into data/corpus/derived/."""
    cfg = cfg or load_config()
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"corpus_sha256": CORPUS_SHA.read_text(encoding="utf-8").split()[0], "files": {}}
    for key in DERIVED:
        src = resolve_path(key, cfg)
        if not src.is_file():
            raise SystemExit(f"cannot pack: {src} does not exist (run the step that builds it first)")
        data = src.read_bytes()
        out = PACK_DIR / f"{src.name}.xz"
        tmp = out.with_suffix(".tmp")
        with lzma.open(tmp, "wb", preset=6) as fh:
            fh.write(data)
        tmp.replace(out)
        manifest["files"][key] = {"file": out.name, "rows": data.count(b"\n"), "sha256": hashlib.sha256(data).hexdigest()}
        say(f"packed {src.name}: {len(data) / 1e6:.1f} MB -> {out.stat().st_size / 1e6:.2f} MB, {manifest['files'][key]['rows']} rows")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def restore_derived(cfg: dict) -> None:
    if not MANIFEST.is_file():
        say("  no packed derived data in this checkout (data/corpus/derived/manifest.json): build it with `make build-statutes`, `make m3` and `python -m app.docmeta`")
        return
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("corpus_sha256") != CORPUS_SHA.read_text(encoding="utf-8").split()[0]:
        raise SystemExit("data/corpus/derived/ was packed from another corpus than data/corpus/judgments.jsonl.xz: ask the maintainer to run `python -m app.setup --pack` again")
    for key, info in manifest["files"].items():
        dst = resolve_path(key, cfg)
        if dst.is_file() and sha256_of(dst) == info["sha256"]:
            say(f"  {dst.name}: already restored")
            continue
        with lzma.open(PACK_DIR / info["file"], "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise SystemExit(f"{info['file']} does not match its checksum in manifest.json")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dst)
        say(f"  {dst.name}: restored ({info['rows']} rows)")


def index_ok(documents: int) -> tuple[bool, str]:
    try:
        from m1_index.index import InvertedIndex

        idx = InvertedIndex.load()
    except Exception as exc:  # noqa: BLE001 - any failure to read the index means "rebuild it"
        return False, f"{type(exc).__name__}: {exc}"
    if idx.num_docs != documents:
        return False, f"the index holds {idx.num_docs} documents, the corpus {documents}"
    return True, f"{idx.num_docs} documents"


def ensure_index(cfg: dict) -> None:
    documents = count_rows(resolve_path("judgments", cfg))
    ok, why = index_ok(documents)
    if ok:
        say(f"  index: readable, {why}")
        return
    say(f"  index: {why}; rebuilding (about 2 to 3 minutes)")
    started = time.time()
    rc = subprocess.call([sys.executable, "-m", "m1_index.index", "build"], cwd=ROOT)
    if rc != 0:
        raise SystemExit("the index build failed (see the messages above)")
    ok, why = index_ok(documents)
    if not ok:
        raise SystemExit(f"the rebuilt index is still unusable: {why}")
    say(f"  index: rebuilt in {time.time() - started:.0f} s, {why}")


def check_real(cfg: dict) -> bool:
    ok = True
    stubs = [k for k, v in (cfg.get("stubs") or {}).items() if v]
    if stubs:
        say(f"  STILL STUBS in common/config.yaml: {', '.join(stubs)}. Pull the latest main (`git pull`), the switches are false there.")
        ok = False
    override = os.environ.get("LEXSHIFT_STUBS")
    if override:
        say(f"  LEXSHIFT_STUBS={override!r} is set in this shell and forces stand-ins: the page will show stub mode. Clear it: PowerShell `Remove-Item Env:LEXSHIFT_STUBS`, bash `unset LEXSHIFT_STUBS`.")
        ok = False
    return ok


def setup() -> int:
    cfg = load_config()
    say("1. corpus")
    if corpus_ok(cfg):
        say("  judgments.jsonl: present and matches data/corpus/judgments.jsonl.xz")
    else:
        from m1_index import ingest

        ingest.unpack()
    say("2. derived data (statutes, treatment and authority, titles, citations)")
    restore_derived(cfg)
    say("3. search index")
    ensure_index(cfg)
    say("4. every module real?")
    real = check_real(cfg)
    say("")
    say("READY: every module is real. Start the interface with:  python -m app.server --open" if real else "NOT READY: fix the points above, then run this again.")
    return 0 if real else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.setup", description=__doc__.split("\n\n")[0])
    ap.add_argument("--pack", action="store_true", help="maintainers: pack the derived data into data/corpus/derived/ (commit the result)")
    args = ap.parse_args(argv)
    if args.pack:
        pack_derived()
        return 0
    return setup()


if __name__ == "__main__":
    sys.exit(main())
