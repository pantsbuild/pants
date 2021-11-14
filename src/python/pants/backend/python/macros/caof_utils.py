# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.engine.target import InvalidFieldException
from pants.util.collections import ensure_str_list

OVERRIDES_TYPE = Optional[Dict[Union[str, Tuple[str, ...]], Dict[str, Any]]]


def flatten_overrides(
    overrides: OVERRIDES_TYPE, *, macro_name: str, build_file_dir: str
) -> dict[str, Dict[str, Any]]:
    overrides = overrides or {}
    result: dict[str, Dict[str, Any]] = {}
    for key_or_keys, override_values in (overrides or {}).items():
        keys = (key_or_keys,) if isinstance(key_or_keys, str) else key_or_keys
        for key in keys:
            if key in result:
                raise InvalidFieldException(
                    f"Conflicting overrides in the `overrides` field of the `{macro_name}` macro "
                    f"in the BUILD file in {build_file_dir} for the key `{key}`. You cannot specify "
                    "the same field name multiple times for the same key.\n\n"
                    f"(One override sets the field to `{repr(result[key])}` "
                    f"but another sets to `{repr(overrides[key_or_keys])}`.)"
                )
            result[key] = override_values
    return result


def flatten_overrides_to_dependency_field(
    overrides: OVERRIDES_TYPE, *, macro_name: str, build_file_dir: str
) -> dict[str, list[str]]:
    """Flatten `overrides` by ensuring that only `dependencies` is specified."""

    result: dict[str, list[str]] = {}
    for raw_key, override_values in flatten_overrides(
        overrides, macro_name=macro_name, build_file_dir=build_file_dir
    ).items():
        key = canonicalize_project_name(raw_key)
        for field, value in override_values.items():
            if field != "dependencies":
                raise InvalidFieldException(
                    "Can only specify the `dependencies` field (for now) in the `overrides` "
                    f"field of the `{macro_name}` macro in the BUILD file in {build_file_dir} "
                    f"for the key `{key}`, but you specified `{field}`."
                )
            try:
                normalized_value = ensure_str_list(value)
            except ValueError:
                raise InvalidFieldException(
                    f"The `{field}` field in the `overrides` field of the `{macro_name}` "
                    f"macro in the BUILD file in {build_file_dir} must be `list[str]`, "
                    f"but was `{repr(value)}` with type `{type(value).__name__}`."
                )
            result[key] = normalized_value
    return result
