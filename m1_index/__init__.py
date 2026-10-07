"""M1: corpus, indexing and search. Public API: search().

`search` is imported on first use, so `import m1_index` is instant and prints nothing, and `python -m m1_index.index build` does
not load the search engine (or NLTK) before it runs.
"""

from __future__ import annotations

__all__ = ["search"]


def __getattr__(name: str):
    if name == "search":
        from m1_index.searcher import search

        return search
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
