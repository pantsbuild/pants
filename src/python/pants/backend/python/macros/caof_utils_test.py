# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.macros.caof_utils import (
    flatten_overrides,
    flatten_overrides_to_dependency_field,
)
from pants.engine.target import InvalidFieldException


def test_flatten() -> None:
    result = flatten_overrides(
        {
            "d1": {"dependencies": ["a"]},
            ("d2", "d3"): {"tags": ["manual"]},
            ("UnNormalized_key",): {"itsakey": "its a value"},
        },
        macro_name="macro",
        build_file_dir="dir",
    )
    assert result == {
        "d1": {"dependencies": ["a"]},
        "d2": {"tags": ["manual"]},
        "d3": {"tags": ["manual"]},
        "UnNormalized_key": {"itsakey": "its a value"},
    }


def test_flatten_same_key() -> None:
    with pytest.raises(InvalidFieldException, match="Conflicting overrides"):
        flatten_overrides_to_dependency_field(
            {"d1": {}, ("d1", "d2"): {}},
            macro_name="macro",
            build_file_dir="dir",
        )

    with pytest.raises(InvalidFieldException, match="Conflicting overrides"):
        flatten_overrides_to_dependency_field(
            {("d1", "d1"): {}},
            macro_name="macro",
            build_file_dir="dir",
        )


def test_flatten_overrides_to_dependency_field() -> None:
    result = flatten_overrides_to_dependency_field(
        {
            "d1": {"dependencies": ["a"]},
            ("d2", "d3"): {"dependencies": {"b"}},
            ("UnNormalized_proj"): {"dependencies": {"c"}},
        },
        macro_name="macro",
        build_file_dir="dir",
    )
    assert result == {"d1": ["a"], "d2": ["b"], "d3": ["b"], "unnormalized-proj": ["c"]}


def test_flatten_overrides_same_key() -> None:
    with pytest.raises(InvalidFieldException, match="Conflicting overrides"):
        flatten_overrides_to_dependency_field(
            {"d1": {"dependencies": []}, ("d1", "d2"): {"dependencies": []}},
            macro_name="macro",
            build_file_dir="dir",
        )

    with pytest.raises(InvalidFieldException, match="Conflicting overrides"):
        flatten_overrides_to_dependency_field(
            {("d1", "d1"): {"dependencies": []}},
            macro_name="macro",
            build_file_dir="dir",
        )


def test_flatten_overrides_only_dependencies_field() -> None:
    with pytest.raises(InvalidFieldException, match="Can only specify the `dependencies` field"):
        flatten_overrides_to_dependency_field(
            {"d": {"tags": []}}, macro_name="macro", build_file_dir="dir"
        )


def test_flatten_overrides_basic_data_validation() -> None:
    with pytest.raises(InvalidFieldException, match=r"must be `list\[str\]`"):
        flatten_overrides_to_dependency_field(
            {"d": {"dependencies": 1}}, macro_name="macro", build_file_dir="dir"
        )
