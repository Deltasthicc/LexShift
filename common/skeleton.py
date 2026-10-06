"""Helpers for skeleton modules that are not implemented yet.

A skeleton function raises NotImplementedError naming its owner and README, instead of returning a plausible
looking value. Delete the call (and this import) when you implement the function.
"""

from __future__ import annotations

from typing import NoReturn


def not_implemented(owner: str, what: str) -> NoReturn:
    raise NotImplementedError(f"{owner}: {what} is not implemented yet. See the module README for the spec.")


def todo_main(owner: str, what: str) -> int:
    """Body for a skeleton `python -m <module>` entry point: say so honestly and exit non-zero."""
    print(f"[{owner}] {what}: not implemented yet (see the module README).")
    return 2
