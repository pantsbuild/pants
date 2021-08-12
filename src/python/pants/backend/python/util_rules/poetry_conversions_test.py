# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

import pytest
from pkg_resources import Requirement

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.poetry_conversions import (
    _HEADER,
    PoetryDependency,
    create_pyproject_toml_as_dict,
)


def test_create_pyproject_toml() -> None:
    created = create_pyproject_toml_as_dict(
        [
            "dep1",
            "dep2==4.2",
            "with-extra[some-extra]",
            "marker ; sys_platform == 'darwin'",
            "duplicate==1.0",
            "duplicate==2.0",
        ],
        InterpreterConstraints(["==3.7.*", "==3.8.*"]),
    )
    print(created)
    assert created == {
        "tool": {
            "poetry": {
                **_HEADER,
                "dependencies": {
                    "python": "==3.7.* || ==3.8.*",
                    "dep1": {"version": "*"},
                    "dep2": {"version": "==4.2"},
                    "with-extra": {"version": "*", "extras": ("some-extra",)},
                    "marker": {"version": "*", "markers": 'sys_platform == "darwin"'},
                    "duplicate": [{"version": "==1.0"}, {"version": "==2.0"}],
                },
            }
        }
    }


@pytest.mark.parametrize(
    "req_str,expected",
    [
        ("dep==1.0", PoetryDependency("dep", version="==1.0")),
        ("dep>=1.0,<6,!=2.0", PoetryDependency("dep", version="!=2.0,<6,>=1.0")),
        ("dep", PoetryDependency("dep", version=None)),
        # Extras.
        ("dep[extra1]", PoetryDependency("dep", version=None, extras=("extra1",))),
        ("dep[extra1,extra2]", PoetryDependency("dep", version=None, extras=("extra1", "extra2"))),
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
    "deps,expected",
    [
        ([PoetryDependency("dep", version="==1.0")], {"version": "==1.0"}),
        ([PoetryDependency("dep", version=">=1.0,<6,!=2.0")], {"version": ">=1.0,<6,!=2.0"}),
        ([PoetryDependency("dep", version=None)], {"version": "*"}),
        # Extras.
        (
            [PoetryDependency("dep", version=None, extras=("extra1", "extra2"))],
            {"version": "*", "extras": ("extra1", "extra2")},
        ),
        # Markers.
        (
            [PoetryDependency("dep", version=None, markers='sys_platform == "darwin"')],
            {"version": "*", "markers": 'sys_platform == "darwin"'},
        ),
        # Multiple values for the same dependency.
        (
            [
                PoetryDependency("dep", version="==1.0"),
                PoetryDependency("dep", version="==2.0"),
                PoetryDependency("dep", version="==3.0", extras=("some-extra",)),
            ],
            [
                {"version": "==1.0"},
                {"version": "==2.0"},
                {"version": "==3.0", "extras": ("some-extra",)},
            ],
        ),
    ],
)
def test_poetry_dependency_to_pyproject_toml(
    deps: list[PoetryDependency],
    expected: dict[str, Any] | list[dict[str, Any]],
) -> None:
    assert PoetryDependency.to_pyproject_toml_metadata(deps) == expected
