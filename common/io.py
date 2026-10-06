"""Small, dependency-free file helpers shared by every module (JSON Lines, TSV, CSV).

All files are UTF-8 with LF line endings so a Windows/macOS/Linux team produces identical bytes.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator


def read_jsonl(path: str | os.PathLike) -> Iterator[dict[str, Any]]:
    """Yield one dict per non-blank line; a malformed line raises with its line number."""
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON ({exc.msg})") from exc


def write_jsonl(path: str | os.PathLike, records: Iterable[dict[str, Any]]) -> int:
    """Write records atomically (temp file then rename) so a crash never leaves a half-written corpus."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return count


def read_delimited(path: str | os.PathLike, delimiter: str = ",") -> list[dict[str, str]]:
    """Read a CSV/TSV with a header row into a list of dicts (all values are strings).

    Reads `utf-8-sig`: spreadsheet programs save "CSV UTF-8" with a byte-order mark, which would otherwise end up glued to
    the first column name. Files without a mark read exactly as before.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delimiter))


def write_delimited(
    path: str | os.PathLike, columns: Iterable[str], rows: Iterable[dict[str, Any]], delimiter: str = ","
) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), delimiter=delimiter, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count
