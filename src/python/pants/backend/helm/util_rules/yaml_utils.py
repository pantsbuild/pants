# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, Mapping


def _as_python_attribute_name(str: str) -> str:
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


def yaml_attr_dict(d: Mapping[str, Any]) -> dict[str, Any]:
    return {_as_python_attribute_name(name): value for name, value in d.items()}
