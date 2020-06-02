# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import Optional

import pytest

from pants.backend.python.dependency_inference.module_mapper import determine_module


@pytest.mark.parametrize(
    "stripped_path,expected",
    [
        (PurePath("top_level.py"), "top_level"),
        (PurePath("dir", "subdir", "__init__.py"), "dir.subdir"),
        (PurePath("dir", "subdir", "app.py"), "dir.subdir.app"),
        (
            PurePath("src", "python", "project", "not_stripped.py"),
            "src.python.project.not_stripped",
        ),
        (PurePath("not_python.java"), None),
        (PurePath("bytecode.pyc"), None),
    ],
)
def test_determine_module(stripped_path: PurePath, expected: Optional[str]) -> None:
    assert determine_module(stripped_path) == expected
