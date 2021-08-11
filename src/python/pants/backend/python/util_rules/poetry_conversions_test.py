# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest
from pkg_resources import Requirement

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.poetry_conversions import (
    _HEADER,
    PoetryDependency,
    create_pyproject_toml,
)


def test_create_pyproject_toml() -> None:
    created = create_pyproject_toml(
        ["dep1", "dep2==4.2"],
        InterpreterConstraints(["==3.7.*", "==3.8.*"]),
        interpreter_universe=["3.6", "3.7", "3.8", "3.9"],
    )
    assert created == _HEADER + dedent(
        """\

        [tool.poetry.dependencies]
        python = "<3.9,>=3.7"
        dep1 = { version = '*' }
        dep2 = { version = '==4.2' }
        """
    )


@pytest.mark.parametrize(
    "req_str,expected",
    [
        ("dep==1.0", PoetryDependency("dep", version="==1.0")),
        ("dep>=1.0,<6,!=2.0", PoetryDependency("dep", version="!=2.0,<6,>=1.0")),
        ("dep", PoetryDependency("dep", version=None)),
    ],
)
def test_poetry_dependency_from_requirement(req_str: str, expected: PoetryDependency) -> None:
    req = Requirement.parse(req_str)
    assert PoetryDependency.from_requirement(req) == expected


@pytest.mark.parametrize(
    "dep,expected",
    [
        (PoetryDependency("dep", version="==1.0"), "dep = { version = '==1.0' }"),
        (PoetryDependency("dep", version=">=1.0,<6,!=2.0"), "dep = { version = '>=1.0,<6,!=2.0' }"),
        (PoetryDependency("dep", version=None), "dep = { version = '*' }"),
    ],
)
def test_poetry_dependency_repr(dep: PoetryDependency, expected: str) -> None:
    assert str(dep) == expected
