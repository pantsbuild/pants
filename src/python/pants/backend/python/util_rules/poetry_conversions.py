# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import toml
from pkg_resources import Requirement

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints

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
        # TODO(#12314): add error handling. Probably better is for the function to expect already
        #  parsed Requirement objects.
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
