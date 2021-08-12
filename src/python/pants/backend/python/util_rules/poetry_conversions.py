# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
            version=str(requirement.specifier) or None,
            extras=requirement.extras,
            markers=str(requirement.marker) if requirement.marker else None,
        )

    def to_pyproject_toml_dependency(self) -> dict[str, Any]:
        """Return a dictionary with one element of `project_name -> metadata`.

        This can then be serialized using the `toml` library by being added to the
        `[tool.poetry.dependencies]` section.
        """
        metadata = {"version": self.version or "*"}
        if self.extras:
            metadata["extras"] = self.extras
        if self.markers:
            metadata["markers"] = self.markers
        return {self.name: metadata}
