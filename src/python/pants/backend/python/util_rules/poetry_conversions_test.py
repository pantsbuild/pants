# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from pkg_resources import Requirement

from pants.backend.python.util_rules.poetry_conversions import PoetryDependency


@pytest.mark.parametrize(
    "req_str,expected",
    [
        ("dep==1.0", PoetryDependency("dep", version="==1.0")),
        ("dep>=1.0,<6,!=2.0", PoetryDependency("dep", version="!=2.0,<6,>=1.0")),
        ("dep", PoetryDependency("dep", version=None)),
        # Extras.
        ("dep[extra1]", PoetryDependency("dep", version=None, extras=("extra1",))),
        ("dep[extra1,extra2]", PoetryDependency("dep", version=None, extras=("extra2", "extra1"))),
        # Markers.
        (
            "dep ; sys_platform == 'darwin'",
            PoetryDependency("dep", version=None, markers='sys_platform == "darwin"'),
        ),
    ],
)
def test_poetry_dependency_from_requirement(req_str: str, expected: PoetryDependency) -> None:
    req = Requirement.parse(req_str)
    assert PoetryDependency.from_requirement(req) == expected


@pytest.mark.parametrize(
    "dep,expected",
    [
        (PoetryDependency("dep", version="==1.0"), {"dep": {"version": "==1.0"}}),
        (PoetryDependency("dep", version=">=1.0,<6,!=2.0"), {"dep": {"version": ">=1.0,<6,!=2.0"}}),
        (PoetryDependency("dep", version=None), {"dep": {"version": "*"}}),
        # Extras.
        (
            PoetryDependency("dep", version=None, extras=("extra1", "extra2")),
            {"dep": {"version": "*", "extras": ("extra1", "extra2")}},
        ),
        # Markers.
        (
            PoetryDependency("dep", version=None, markers='sys_platform == "darwin"'),
            {"dep": {"version": "*", "markers": 'sys_platform == "darwin"'}},
        ),
    ],
)
def test_poetry_dependency_to_pyproject_toml(dep: PoetryDependency, expected: str) -> None:
    assert dep.to_pyproject_toml_dependency() == expected
