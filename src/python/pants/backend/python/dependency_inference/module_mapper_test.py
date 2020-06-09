# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

import pytest

from pants.backend.python.dependency_inference.module_mapper import PythonModule
from pants.base.specs import AscendantAddresses


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
    ],
)
def test_create_module_from_path(stripped_path: PurePath, expected: str) -> None:
    assert PythonModule.create_from_stripped_path(stripped_path) == PythonModule(expected)


def test_module_possible_paths() -> None:
    assert PythonModule("typing").possible_stripped_paths() == (
        PurePath("typing.py"),
        PurePath("typing") / "__init__.py",
    )
    assert PythonModule("typing.List").possible_stripped_paths() == (
        PurePath("typing") / "List.py",
        PurePath("typing") / "List" / "__init__.py",
        PurePath("typing.py"),
        PurePath("typing") / "__init__.py",
    )


def test_module_address_spec() -> None:
    assert PythonModule("helloworld.app").address_spec(source_root=".") == AscendantAddresses(
        directory="helloworld/app"
    )
    assert PythonModule("helloworld.app").address_spec(
        source_root="src/python"
    ) == AscendantAddresses(directory="src/python/helloworld/app")
