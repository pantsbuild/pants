# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from _pytest.fixtures import FixtureRequest

from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import LockfileContext
from pants.util.docutil import bin_name
from pants.jvm.resolve.common import ArtifactRequirement
from pants.jvm.resolve.common import ArtifactRequirements
from pants.jvm.resolve.coordinate import Coordinate


@dataclass(frozen=True)
class JVMLockfileFixtureDefinition:
    lockfile_rel_path: Path
    requirements: tuple[Coordinate, ...]

    def __init__(
        self, lockfile_rel_path: Path | str, requirements: Iterable[Coordinate | str]
    ) -> None:
        coordinates: list[Coordinate] = []
        for requirement in requirements:
            if isinstance(requirement, Coordinate):
                coordinates.append(requirement)
            elif isinstance(requirement, str):
                coordinate = Coordinate.from_coord_str(requirement)
                coordinates.append(coordinate)
            else:
                raise TypeError(
                    f"Unsupported type `{type(requirement)}` for JVM coordinate. Expected `Coordinate` or `str`."
                )

        object.__setattr__(
            self,
            "lockfile_rel_path",
            lockfile_rel_path if isinstance(lockfile_rel_path, Path) else Path(lockfile_rel_path),
        )
        object.__setattr__(self, "requirements", tuple(coordinates))

    @classmethod
    def from_json_dict(cls, kwargs) -> JVMLockfileFixtureDefinition:
        lockfile_rel_path = kwargs["lockfile_rel_path"]
        if not lockfile_rel_path:
            raise ValueError("`path` must be specified as a relative path to a lockfile")

        requirements = kwargs["requirements"] or []
        return cls(
            lockfile_rel_path=Path(lockfile_rel_path),
            requirements=requirements,
        )

    def load(self, request: FixtureRequest) -> JVMLockfileFixture:
        lockfile_path = request.node.path.parent / self.lockfile_rel_path
        lockfile_contents = lockfile_path.read_bytes()
        lockfile = CoursierResolvedLockfile.from_serialized(lockfile_contents)

        # Check the lockfile's requirements against the requirements in the lockfile.
        # Fail the test if the lockfile needs to be regenerated.
        artifact_reqs = ArtifactRequirements(
            [ArtifactRequirement(coordinate) for coordinate in self.requirements]
        )
        if not lockfile.metadata:
            raise ValueError(f"Expected JVM lockfile {self.lockfile_rel_path} to have metadata.")
        if not lockfile.metadata.is_valid_for(artifact_reqs, LockfileContext.TOOL):
            raise ValueError(
                f"Lockfile fixture {self.lockfile_rel_path} is not valid. "
                "Please re-generate it using: "
                f"{bin_name()} internal-generate-test-lockfile-fixtures ::"
            )

        return JVMLockfileFixture(lockfile, lockfile_contents.decode(), artifact_reqs)


@dataclass(frozen=True)
class JVMLockfileFixture:
    lockfile: CoursierResolvedLockfile
    serialized_lockfile: str
    requirements: ArtifactRequirements

    def requirements_as_jvm_artifact_targets(
        self, *, version_in_target_name: bool = False, resolve: str | None = None
    ) -> str:
        targets = ""
        for requirement in self.requirements:
            maybe_version = f"_{requirement.coordinate.version}" if version_in_target_name else ""
            maybe_resolve = f'resolve="{resolve}",' if resolve else ""
            targets += textwrap.dedent(
                f"""\
            jvm_artifact(
              name="{requirement.coordinate.group}_{requirement.coordinate.artifact}{maybe_version}",
              group="{requirement.coordinate.group}",
              artifact="{requirement.coordinate.artifact}",
              version="{requirement.coordinate.version}",
              {maybe_resolve}
            )
            """
            )
        return targets
