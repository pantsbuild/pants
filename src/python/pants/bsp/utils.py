# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

from pants.util.frozendict import FrozenDict


def freeze_json(item: Any) -> Any:
    if item is None:
        return None
    elif isinstance(item, list) or isinstance(item, tuple):
        return tuple(freeze_json(x) for x in item)
    elif isinstance(item, dict):
        result = {}
        for k, v in item.items():
            if not isinstance(k, str):
                raise AssertionError("Got non-`str` key for _freeze.")
            result[k] = freeze_json(v)
        return FrozenDict(result)
    elif isinstance(item, str) or isinstance(item, int) or isinstance(item, float):
        return item
    else:
        raise AssertionError(f"Unsupported value type for _freeze: {type(item)}")
