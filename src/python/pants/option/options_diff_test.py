# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Any

import pytest

from pants.option.options_diff import summarize_options_map_diff


@pytest.mark.parametrize(
    "old, new, expected_diff",
    [
        [
            {"a": 1, "b": ["x", "y"], "c": True},
            {"a": 1, "b": ["x", "y"], "c": True},
            "",
        ],
        [
            {"l": ["x", "y"]},
            {"l": ["x", "y", "z"]},
            "l: ['x', 'y'] -> ['x', 'y', 'z']",
        ],
        [
            {"flag": True, "a": 30},
            {"flag": False, "a": 30},
            "flag: True -> False",
        ],
        [
            {},
            {"foo": "bar"},
            "foo: None -> 'bar'",
        ],
        [
            {"x": "a", "y": ["b", "c"], "z": True},
            {"x": "d", "y": ["e", "f", "g"], "z": False},
            "x: 'a' -> 'd'; y: ['b', 'c'] -> ['e', 'f', 'g']; z: True -> False",
        ],
    ],
)
def test_summarize_options_map_diff(
    old: dict[str, Any], new: dict[str, Any], expected_diff: str
) -> None:
    diff = summarize_options_map_diff(old, new)
    assert diff == expected_diff
