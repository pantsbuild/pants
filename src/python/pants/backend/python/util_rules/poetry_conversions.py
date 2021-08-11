# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Iterable

from pkg_resources import Requirement

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints

_HEADER = dedent(
    """\
    [tool.poetry]
    name = "pants-lockfile-generation"
    version = "0.1.0"
    description = ""
    authors = ["pantsbuild"]
    """
)


def create_pyproject_toml(
    requirements: Iterable[str],
    interpreter_constraints: InterpreterConstraints,
    interpreter_universe: Iterable[str],
) -> str:
    poetry_deps = "\n".join(
        str(PoetryDependency.from_requirement(Requirement.parse(s))) for s in requirements
    )
    python_constraint = f'python = "{interpreter_constraints.flatten(interpreter_universe)}"'
    return f"{_HEADER}\n[tool.poetry.dependencies]\n{python_constraint}\n{poetry_deps}\n"


@dataclass(frozen=True)
class PoetryDependency:
    name: str
    version: str | None

    @classmethod
    def from_requirement(cls, requirement: Requirement) -> PoetryDependency:
        return PoetryDependency(
            requirement.project_name, version=str(requirement.specifier) or None
        )

    def __str__(self) -> str:
        version = repr(self.version if self.version else "*")
        return f"{self.name} = {{ version = {version} }}"
