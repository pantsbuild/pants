# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import fields
from enum import Enum
from typing import Any

from pants.option.global_options import DynamicRemoteOptions


def summarize_options_map_diff(old: dict[str, Any], new: dict[str, Any]) -> str:
    """Compare two options map (as produced by `OptionsFingerprinter.options_map_for_scope`), and
    return a one-liner summarizing all differences, e.g.:

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


def summarize_dynamic_options_diff(old: DynamicRemoteOptions, new: DynamicRemoteOptions) -> str:
    """Compare two `DynamicRemoteOptions` and return a one-liner summarizing all differences, e.g.:

    `provider: 'reapi' -> 'experimental-file'; cache_read: False -> True`
    """
    diffs = []
    for field in fields(DynamicRemoteOptions):
        key = field.name
        o = getattr(old, key)
        n = getattr(new, key)

        if o == n:
            continue

        o = o.value if isinstance(o, Enum) else o
        n = n.value if isinstance(n, Enum) else n

        diffs.append(f"{key}: {o!r} -> {n!r}")

    return "; ".join(diffs)
