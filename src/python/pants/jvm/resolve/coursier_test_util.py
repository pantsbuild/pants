# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable

from pants.jvm.resolve.common import ArtifactRequirement
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.util.docutil import bin_name


@dataclass
class TestCoursierWrapper:
    """Utility class to make it easier to create a serialized Coursier lockfile with a correct
    metadata header in tests."""

    lockfile: CoursierResolvedLockfile

    @classmethod
    def new(cls, entries: Iterable[CoursierLockfileEntry]):
        return cls(CoursierResolvedLockfile(entries=tuple(entries)))

    def serialize(self, requirements: Iterable[ArtifactRequirement] = ()) -> str:
        return (
            JVMLockfileMetadata.new(requirements)
            .add_header_to_lockfile(
                self.lockfile.to_serialized(), regenerate_command=f"{bin_name()} generate_lockfiles"
            )
            .decode()
        )
