"""WatDiv execution support is intentionally out of scope for this patch."""

from __future__ import annotations


def run(*args, **kwargs):
    raise NotImplementedError(
        "WatDiv execution is intentionally not implemented in this patch; "
        "this adapter prepares the official workload manifest only."
    )
