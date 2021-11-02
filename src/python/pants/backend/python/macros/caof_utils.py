# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.engine.target import InvalidFieldException
from pants.util.collections import ensure_str_list

OVERRIDES_TYPE = Optional[Dict[Union[str, Tuple[str, ...]], Dict[str, Any]]]


def flatten_overrides_to_dependency_field(
    overrides_value: OVERRIDES_TYPE, *, macro_name: str, build_file_dir: str
) -> dict[str, list[str]]:
    """Flatten `overrides` by ensuring that only `dependencies` is specified."""

    result: dict[str, list[str]] = {}
    for maybe_key_or_keys, override in (overrides_value or {}).items():
        keys = (maybe_key_or_keys,) if isinstance(maybe_key_or_keys, str) else maybe_key_or_keys
        for _raw_key in keys:
            key = canonicalize_project_name(_raw_key)
            for field, value in override.items():
                if field != "dependencies":
                    raise InvalidFieldException(
                        "Can only specify the `dependencies` field (for now) in the `overrides` "
                        f"field of the {macro_name} macro in the BUILD file in {build_file_dir} "
                        f"for the key `{key}`, but you specified `{field}`."
                    )
                if key in result:
                    raise InvalidFieldException(
                        f"Conflicting overrides in the `overrides` field of "
                        f"the {macro_name} macro in the BUILD file in {build_file_dir} for the key "
                        f"`{key}` for the field `{field}`. You cannot specify the same field name "
                        "multiple times for the same key.\n\n"
                        f"(One override sets the field to `{repr(result[key])}` "
                        f"but another sets to `{repr(value)}`.)"
                    )
                try:
                    normalized_value = ensure_str_list(value)
                except ValueError:
                    raise InvalidFieldException(
                        f"The 'overrides' field in the {macro_name} macro in the BUILD file in "
                        f"{build_file_dir} must be `dict[str | tuple[str, ...], dict[str, Any]]`, "
                        f"but was `{repr(value)}` with type `{type(value).__name__}`."
                    )
                result[key] = normalized_value
    return result
