# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.utils.yaml import YamlPath


@pytest.mark.parametrize(
    "path, is_absolute, is_root, is_index",
    [
        ("/", True, True, False),
        ("/0", True, False, True),
        ("/path", True, False, False),
        ("0", False, False, True),
        ("path", False, False, False),
    ],
)
def test_yaml_path_parser(path: str, is_absolute: bool, is_root: bool, is_index: bool) -> None:
    parsed = YamlPath.parse(path)

    assert parsed.is_absolute == is_absolute
    assert parsed.is_root == is_root
    assert parsed.is_index == is_index

    if parsed.is_root:
        assert not parsed.parent

        nested = parsed / "nested"

        assert not nested.is_root
        assert nested.parent == parsed

    if not parsed.is_absolute:
        absolute = YamlPath.root() / parsed

        assert absolute.is_absolute

    if parsed.is_index:
        index = YamlPath.index(int(parsed.current))

        assert not index.is_absolute
        assert index.is_index
        assert index.current == parsed.current
