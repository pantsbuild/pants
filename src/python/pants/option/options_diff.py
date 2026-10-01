# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import fields
from enum import Enum
from typing import Any

from pants.option.bootstrap_options import DynamicRemoteOptions

# Option / DynamicRemoteOptions field names whose values must not appear in
# scheduler-reinit log lines (see pantsbuild/pants#23685).
_SENSITIVE_KEYS = frozenset(
    {
        "remote_store_headers",
        "remote_execution_headers",
        "remote_oauth_bearer_token",
        "store_headers",
        "execution_headers",
    }
)

_REDACTED = "<redacted>"


def _format_value(key: str, value: Any) -> str:
    """Format a value for a diff summary, redacting sensitive option values."""
    if key in _SENSITIVE_KEYS and value is not None:
        return _REDACTED
    return repr(value)


def summarize_options_map_diff(old: dict[str, Any], new: dict[str, Any]) -> str:
    """Compare two options map (as produced by `OptionsFingerprinter.options_map_for_scope`), and
    return a one-liner summarizing all differences, e.g.:

    `key1: 'old' -> "new"; list_key: ['x', 'y'] -> ['x']`
    """
    diffs = []
    for key in sorted({*old, *new}):
        o = old.get(key)
        n = new.get(key)

        if o == n:
            continue

        diffs.append(f"{key}: {_format_value(key, o)} -> {_format_value(key, n)}")

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

        diffs.append(f"{key}: {_format_value(key, o)} -> {_format_value(key, n)}")

    return "; ".join(diffs)
