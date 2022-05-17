# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Iterable, Sequence

import toml
from pkg_resources import Requirement

from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.engine.fs import FileContent

# ----------------------------------------------------------------------------------------
# Subsystem
# ----------------------------------------------------------------------------------------


class PoetrySubsystem(PythonToolRequirementsBase):
    options_scope = "poetry"
    help = "Used to generate lockfiles for third-party Python dependencies."

    default_version = "poetry==1.1.8"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]


# We must monkeypatch Poetry to include `setuptools` and `wheel` in the lockfile. This was fixed
# in Poetry 1.2. See https://github.com/python-poetry/poetry/issues/1584.
# WONTFIX(#12314): only use this custom launcher if using Poetry 1.1..
POETRY_LAUNCHER = FileContent(
    "__pants_poetry_launcher.py",
    dedent(
        """\
        from poetry.console import main
        from poetry.puzzle.provider import Provider

        Provider.UNSAFE_PACKAGES = set()
        main()
        """
    ).encode(),
)


# ----------------------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------------------

_HEADER = {
    "name": "pants-lockfile-generation",
    "version": "0.1.0",
    "description": "",
    "authors": ["pantsbuild"],
}


def create_pyproject_toml(
    requirements: Iterable[str], interpreter_constraints: InterpreterConstraints
) -> str:
    return toml.dumps(create_pyproject_toml_as_dict(requirements, interpreter_constraints))


def create_pyproject_toml_as_dict(
    raw_requirements: Iterable[str], interpreter_constraints: InterpreterConstraints
) -> dict:
    python_constraint = {"python": interpreter_constraints.to_poetry_constraint()}
    project_name_to_poetry_deps = defaultdict(list)
    for raw_req in raw_requirements:
        # WONTFIX(#12314): add error handling.
        req = Requirement.parse(raw_req)
        poetry_dep = PoetryDependency.from_requirement(req)
        project_name_to_poetry_deps[req.project_name].append(poetry_dep)

    deps = {
        project_name: PoetryDependency.to_pyproject_toml_metadata(poetry_deps)
        for project_name, poetry_deps in project_name_to_poetry_deps.items()
    }
    return {"tool": {"poetry": {**_HEADER, "dependencies": {**python_constraint, **deps}}}}


@dataclass(frozen=True)
class PoetryDependency:
    name: str
    version: str | None
    extras: tuple[str, ...] = ()
    markers: str | None = None

    @classmethod
    def from_requirement(cls, requirement: Requirement) -> PoetryDependency:
        return PoetryDependency(
            requirement.project_name,
            version=str(requirement.specifier) or None,  # type: ignore[attr-defined]
            extras=tuple(sorted(requirement.extras)),
            markers=str(requirement.marker) if requirement.marker else None,
        )

    @classmethod
    def to_pyproject_toml_metadata(
        cls, deps: Sequence[PoetryDependency]
    ) -> dict[str, Any] | list[dict[str, Any]]:
        def convert_dep(dep: PoetryDependency) -> dict[str, Any]:
            metadata: dict[str, Any] = {"version": dep.version or "*"}
            if dep.extras:
                metadata["extras"] = dep.extras
            if dep.markers:
                metadata["markers"] = dep.markers
            return metadata

        if not deps:
            raise AssertionError("Must have at least one element!")
        if len(deps) == 1:
            return convert_dep(deps[0])

        entries = []
        name = deps[0].name
        for dep in deps:
            if dep.name != name:
                raise AssertionError(f"All elements must have the same project name. Given: {deps}")
            entries.append(convert_dep(dep))
        return entries
