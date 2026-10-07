"""An unreadable index file gives one message that says how to rebuild it, never a bare zlib error (the Index page showed 'Error -3 ... incorrect header check')."""

from __future__ import annotations

import pytest

pytest.importorskip("nltk")
from m1_index.index import INDEX_FILE, InvertedIndex  # noqa: E402


@pytest.mark.parametrize("blob", [b"\x1f\x8b" + b"garbage-not-deflate" * 40, b"<html>error page</html>", b"", b"\x1f\x8b\x08"])
def test_an_unreadable_index_says_how_to_rebuild_it(tmp_path, blob):
    (tmp_path / INDEX_FILE).write_bytes(blob)
    with pytest.raises(RuntimeError, match="m1_index.index build"):
        InvertedIndex.load(tmp_path)


def test_a_missing_index_still_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="m1_index.index build"):
        InvertedIndex.load(tmp_path)
