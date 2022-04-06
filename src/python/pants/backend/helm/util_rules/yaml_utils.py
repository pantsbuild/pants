# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, Mapping


def _to_snake_case(str: str) -> str:
    """Translates an camel-case or kebab-case identifier by a snake-case one."""
    base_string = str.replace("-", "_")

    result = ""
    idx = 0
    for c in base_string:
        char_to_add = c
        if char_to_add.isupper():
            char_to_add = c.lower()
            if idx > 0:
                result += "_"
        result += char_to_add
        idx += 1

    return result


def snake_case_attr_dict(d: Mapping[str, Any]) -> dict[str, Any]:
    """Transforms all keys in the given mapping to be snake-case."""
    return {_to_snake_case(name): value for name, value in d.items()}
