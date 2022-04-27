# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements, Coordinate
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import LockfileContext
from pants.util.docutil import bin_name


@dataclass(frozen=True)
class JVMLockfileFixtureDefinition:
    lockfile_rel_path: Path
    coordinates: tuple[Coordinate, ...]

    @classmethod
    def from_kwargs(cls, kwargs) -> JVMLockfileFixtureDefinition:
        lockfile_rel_path = kwargs["path"]
        if not lockfile_rel_path:
            raise ValueError("`path` must be specified as a relative path to a lockfile")

        requirements = kwargs["requirements"] or []
        coordinates: list[Coordinate] = []
        for requirement in requirements:
            if isinstance(requirement, Coordinate):
                coordinates.append(requirement)
            elif isinstance(requirement, str):
                coordinate = Coordinate.from_coord_str(requirement)
                coordinates.append(coordinate)
            else:
                raise ValueError(
                    f"Unsupported type `{type(requirement)}` for JVM coordinate. Expected `Coordinate` or `str`."
                )

        return cls(
            lockfile_rel_path=Path(lockfile_rel_path),
            coordinates=tuple(coordinates),
        )


@dataclass(frozen=True)
class JVMLockfileFixture:
    lockfile: CoursierResolvedLockfile
    serialized_lockfile: str
    requirements: ArtifactRequirements

    def requirements_as_jvm_artifact_targets(self) -> str:
        targets = ""
        for requirement in self.requirements:
            targets += textwrap.dedent(f"""\
            jvm_artifact(
              name="{requirement.coordinate.group}_{requirement.coordinate.artifact}_{requirement.coordinate.version}",
              group="{requirement.coordinate.group}",
              artifact="{requirement.coordinate.artifact}",
              version="{requirement.coordinate.version}",
            )
            """)
        return targets


class JvmLockfilePlugin:
    def pytest_configure(self, config):
        config.addinivalue_line(
            "markers",
            "jvm_lockfile(path, requirements): mark test to configure a `jvm_lockfile` fixture",
        )

    @pytest.fixture
    def jvm_lockfile(self, request) -> JVMLockfileFixture:
        mark = request.node.get_closest_marker("jvm_lockfile")

        definition = JVMLockfileFixtureDefinition.from_kwargs(mark.kwargs)

        # Load the lockfile.
        lockfile_path = request.node.path.parent / definition.lockfile_rel_path
        lockfile_contents = lockfile_path.read_bytes()
        lockfile = CoursierResolvedLockfile.from_serialized(lockfile_contents)

        # Check the lockfile's requirements against the requirements in the lockfile.
        # Fail the test if the lockfile needs to be regenerated.
        artifact_reqs = ArtifactRequirements(
            [ArtifactRequirement(coordinate) for coordinate in definition.coordinates]
        )
        if not lockfile.metadata:
            raise ValueError(
                f"Expected JVM lockfile {definition.lockfile_rel_path} to have metadata."
            )
        if not lockfile.metadata.is_valid_for(artifact_reqs, LockfileContext.TOOL):
            raise ValueError(
                f"Lockfile fixture {definition.lockfile_rel_path} is not valid. "
                "Please re-generate it using: "
                f"{bin_name()} internal-generate-test-lockfile-fixtures ::"
            )

        return JVMLockfileFixture(lockfile, lockfile_contents.decode(), artifact_reqs)
