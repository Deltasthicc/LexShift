"""M3: citations and judicial treatment. Public API: health(), authority()."""

__all__ = ["authority", "health"]


def __getattr__(name: str):
    # Imported on first use, so `python -m m3_treatment.scores` does not import scores twice (runpy's RuntimeWarning).
    if name in __all__:
        from m3_treatment import scores

        return getattr(scores, name)
    raise AttributeError(f"module 'm3_treatment' has no attribute {name!r}")
