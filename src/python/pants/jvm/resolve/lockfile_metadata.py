# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, cast

from pants.core.util_rules.lockfile_metadata import (
    LockfileMetadata,
    LockfileMetadataValidation,
    LockfileScope,
    _get_metadata,
    lockfile_metadata_registrar,
)
from pants.jvm.resolve.common import ArtifactRequirement
from pants.util.ordered_set import FrozenOrderedSet

_jvm_lockfile_metadata = lockfile_metadata_registrar(LockfileScope.JVM)


class InvalidJVMLockfileReason(Enum):
    REQUIREMENTS_MISMATCH = "requirements_mismatch"


@dataclass(frozen=True)
class JVMLockfileMetadata(LockfileMetadata):

    scope = LockfileScope.JVM

    @staticmethod
    def new(
        requirements: Iterable[ArtifactRequirement],
    ) -> JVMLockfileMetadata:
        """Call the most recent version of the `LockfileMetadata` class to construct a concrete
        instance.

        This static method should be used in place of the `LockfileMetadata` constructor. This gives
        calling sites a predictable method to call to construct a new `LockfileMetadata` for
        writing, while still allowing us to support _reading_ older, deprecated metadata versions.
        """

        return JVMLockfileMetadataV1.from_artifact_requirements(requirements)

    @classmethod
    def from_lockfile(
        cls, lockfile: bytes, lockfile_path: str | None = None, resolve_name: str | None = None
    ) -> JVMLockfileMetadataV1:
        return cast(
            JVMLockfileMetadataV1,
            LockfileMetadata.from_lockfile_for_scope(
                LockfileScope.JVM, lockfile, lockfile_path, resolve_name
            ),
        )

    def is_valid_for(
        self,
        requirements: Iterable[ArtifactRequirement] | None,
    ) -> LockfileMetadataValidation:
        """Returns Truthy if this `JVMLockfileMetadata` can be used in the current execution
        context."""

        raise NotImplementedError("call `is_valid_for` on subclasses only")


@_jvm_lockfile_metadata(1)
@dataclass(frozen=True)
class JVMLockfileMetadataV1(JVMLockfileMetadata):
    """Lockfile version that permits specifying a requirements as a set rather than a digest.

    Validity is tested by the set of requirements strings being the same in the user requirements as
    those in the stored requirements.
    """

    requirements: FrozenOrderedSet[str]

    @classmethod
    def from_artifact_requirements(
        cls, requirements: Iterable[ArtifactRequirement]
    ) -> JVMLockfileMetadataV1:
        return cls(FrozenOrderedSet(i.to_metadata_str() for i in requirements))

    @classmethod
    def _from_json_dict(
        cls: type[JVMLockfileMetadataV1],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> JVMLockfileMetadataV1:
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)

        requirements = metadata(
            "generated_with_requirements",
            FrozenOrderedSet[str],
            FrozenOrderedSet,
        )

        return JVMLockfileMetadataV1(requirements)

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        instance = cast(JVMLockfileMetadataV1, instance)
        return {
            "generated_with_requirements": (
                sorted(instance.requirements) if instance.requirements is not None else None
            )
        }

    def is_valid_for(
        self,
        requirements: Iterable[ArtifactRequirement] | None,
    ) -> LockfileMetadataValidation:
        """Returns a truthy object if the request requirements match the metadata requirements.

        For this version, "match" is defined as the request requirements being a non-strict subset
        of the metadata requirements.
        """

        failure_reasons: set[InvalidJVMLockfileReason] = set()

        if not self.requirements.issuperset(i.to_metadata_str() for i in requirements or []):
            failure_reasons.add(InvalidJVMLockfileReason.REQUIREMENTS_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)
