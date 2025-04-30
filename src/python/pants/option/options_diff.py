# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Any


def summarize_options_map_diff(old: dict[str, Any], new: dict[str, Any]) -> str:
    """Compare two options map (as produced by `OptionsFingerprinter.options_map_for_scope`), and
    return a one-liner like:

    `key1: 'old' -> "new'; list_key: ['x', 'y'] -> ['x']`
    """
    diffs = []
    for key in sorted({*old, *new}):
        o = old.get(key)
        n = new.get(key)

        if o == n:
            continue

        diffs.append(f"{key}: {o!r} -> {n!r}")

    return "; ".join(diffs)
