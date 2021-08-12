# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from pkg_resources import Requirement


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
    def to_pyproject_toml_dependency(
        cls, deps: Sequence[PoetryDependency]
    ) -> dict[str, dict[str, Any] | list[dict[str, Any]]]:
        """Return a one-element dictionary of `project_name -> metadata`.

        This can then be serialized using the `toml` library by being added to the
        `[tool.poetry.dependencies]` section.
        """

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
            return {deps[0].name: convert_dep(deps[0])}

        entries = []
        name = deps[0].name
        for dep in deps:
            if dep.name != name:
                raise AssertionError(f"All elements must have the same project name. Given: {deps}")
            entries.append(convert_dep(dep))
        return {name: entries}
