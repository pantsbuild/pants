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


class LockfileContext(Enum):
    USER = "user"
    TOOL = "tool"


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

    def is_valid_for(
        self,
        requirements: Iterable[ArtifactRequirement] | None,
        context: LockfileContext,
    ) -> LockfileMetadataValidation:
        """Returns Truthy if this `JVMLockfileMetadata` can be used in the current execution
        context."""

        raise NotImplementedError("call `is_valid_for` on subclasses only")


@_jvm_lockfile_metadata(1)
@dataclass(frozen=True)
class JVMLockfileMetadataV1(JVMLockfileMetadata):
    """Initial metadata version for JVM user lockfiles.

    User validity is tested by the set of user requirements strings appearing as a subset of those
    in the metadata requirements.

    Tool validity is tested by the set of user requirements strings being an exact match of those in
    the metadata requirements.
    """

    requirements: FrozenOrderedSet[str]

    @classmethod
    def from_artifact_requirements(
        cls, requirements: Iterable[ArtifactRequirement]
    ) -> JVMLockfileMetadataV1:
        return cls(FrozenOrderedSet(sorted(i.to_metadata_str() for i in requirements)))

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
        context: LockfileContext,
    ) -> LockfileMetadataValidation:
        """Returns a truthy object if the request requirements match the metadata requirements."""

        failure_reasons: set[InvalidJVMLockfileReason] = set()
        req_strings = FrozenOrderedSet(sorted(i.to_metadata_str() for i in requirements or []))

        if (context == LockfileContext.USER and not self.requirements.issuperset(req_strings)) or (
            context == LockfileContext.TOOL and self.requirements != req_strings
        ):
            failure_reasons.add(InvalidJVMLockfileReason.REQUIREMENTS_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)
