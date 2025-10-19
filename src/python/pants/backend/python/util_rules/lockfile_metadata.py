# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.lockfile_metadata import (
    LockfileMetadata,
    LockfileMetadataValidation,
    LockfileScope,
    _get_metadata,
    lockfile_metadata_registrar,
)
from pants.util.pip_requirement import PipRequirement

_python_lockfile_metadata = lockfile_metadata_registrar(LockfileScope.PYTHON)


class InvalidPythonLockfileReason(Enum):
    INVALIDATION_DIGEST_MISMATCH = "invalidation_digest_mismatch"
    INTERPRETER_CONSTRAINTS_MISMATCH = "interpreter_constraints_mismatch"
    REQUIREMENTS_MISMATCH = "requirements_mismatch"
    MANYLINUX_MISMATCH = "manylinux_mismatch"
    CONSTRAINTS_FILE_MISMATCH = "constraints_file_mismatch"
    ONLY_BINARY_MISMATCH = "only_binary_mismatch"
    NO_BINARY_MISMATCH = "no_binary_mismatch"
    EXCLUDES_MISMATCH = "excludes_mismatch"
    OVERRIDES_MISMATCH = "overrides_mismatch"
    SOURCES_MISMATCH = "sources_mismatch"


@dataclass(frozen=True)
class PythonLockfileMetadata(LockfileMetadata):
    scope = LockfileScope.PYTHON

    valid_for_interpreter_constraints: InterpreterConstraints

    @staticmethod
    def new(
        *,
        valid_for_interpreter_constraints: InterpreterConstraints,
        requirements: set[PipRequirement],
        manylinux: str | None,
        requirement_constraints: set[PipRequirement],
        only_binary: set[str],
        no_binary: set[str],
        excludes: set[str],
        overrides: set[str],
        sources: set[str],
    ) -> PythonLockfileMetadata:
        """Call the most recent version of the `LockfileMetadata` class to construct a concrete
        instance.

        This static method should be used in place of the `LockfileMetadata` constructor. This gives
        calling sites a predictable method to call to construct a new `LockfileMetadata` for
        writing, while still allowing us to support _reading_ older, deprecated metadata versions.
        """

        return PythonLockfileMetadataV5(
            valid_for_interpreter_constraints,
            requirements,
            manylinux=manylinux,
            requirement_constraints=requirement_constraints,
            only_binary=only_binary,
            no_binary=no_binary,
            excludes=excludes,
            overrides=overrides,
            sources=sources,
        )

    @staticmethod
    def metadata_location_for_lockfile(lockfile_location: str) -> str:
        return f"{lockfile_location}.metadata"

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        instance = cast(PythonLockfileMetadata, instance)
        return {
            "valid_for_interpreter_constraints": [
                str(ic) for ic in instance.valid_for_interpreter_constraints
            ]
        }

    def is_valid_for(
        self,
        *,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],
        manylinux: str | None,
        requirement_constraints: Iterable[PipRequirement],
        only_binary: Iterable[str],
        no_binary: Iterable[str],
        excludes: Iterable[str],
        overrides: Iterable[str],
        sources: Iterable[str],
    ) -> LockfileMetadataValidation:
        """Returns Truthy if this `PythonLockfileMetadata` can be used in the current execution
        context."""

        raise NotImplementedError("call `is_valid_for` on subclasses only")


@_python_lockfile_metadata(1)
@dataclass(frozen=True)
class PythonLockfileMetadataV1(PythonLockfileMetadata):
    requirements_invalidation_digest: str

    @classmethod
    def _from_json_dict(
        cls: type[PythonLockfileMetadataV1],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> PythonLockfileMetadataV1:
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)

        interpreter_constraints = metadata(
            "valid_for_interpreter_constraints", InterpreterConstraints, InterpreterConstraints
        )
        requirements_digest = metadata("requirements_invalidation_digest", str, None)

        return PythonLockfileMetadataV1(interpreter_constraints, requirements_digest)

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        instance = cast(PythonLockfileMetadataV1, instance)
        return {"requirements_invalidation_digest": instance.requirements_invalidation_digest}

    def is_valid_for(
        self,
        *,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        # Everything below is not used by v1.
        user_requirements: Iterable[PipRequirement],
        manylinux: str | None,
        requirement_constraints: Iterable[PipRequirement],
        only_binary: Iterable[str],
        no_binary: Iterable[str],
        excludes: Iterable[str],
        overrides: Iterable[str],
        sources: Iterable[str],
    ) -> LockfileMetadataValidation:
        failure_reasons: set[InvalidPythonLockfileReason] = set()

        if expected_invalidation_digest is None:
            return LockfileMetadataValidation(failure_reasons)

        if self.requirements_invalidation_digest != expected_invalidation_digest:
            failure_reasons.add(InvalidPythonLockfileReason.INVALIDATION_DIGEST_MISMATCH)

        if not self.valid_for_interpreter_constraints.contains(
            user_interpreter_constraints, interpreter_universe
        ):
            failure_reasons.add(InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)


@_python_lockfile_metadata(2)
@dataclass(frozen=True)
class PythonLockfileMetadataV2(PythonLockfileMetadata):
    """Lockfile version that permits specifying a requirements as a set rather than a digest.

    Validity is tested by the set of requirements strings being the same in the user requirements as
    those in the stored requirements.
    """

    requirements: set[PipRequirement]

    @classmethod
    def _from_json_dict(
        cls: type[PythonLockfileMetadataV2],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> PythonLockfileMetadataV2:
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)

        requirements = metadata(
            "generated_with_requirements",
            set[PipRequirement],
            lambda l: {
                PipRequirement.parse(i, description_of_origin=lockfile_description) for i in l
            },
        )
        interpreter_constraints = metadata(
            "valid_for_interpreter_constraints", InterpreterConstraints, InterpreterConstraints
        )

        return PythonLockfileMetadataV2(interpreter_constraints, requirements)

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        instance = cast(PythonLockfileMetadataV2, instance)
        # Requirements need to be stringified then sorted so that tests are deterministic. Sorting
        # followed by stringifying does not produce a meaningful result.
        return {"generated_with_requirements": (sorted(str(i) for i in instance.requirements))}

    def is_valid_for(
        self,
        *,
        expected_invalidation_digest: str | None,  # Not used by V2.
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],
        # Everything below is not used by V2.
        manylinux: str | None,
        requirement_constraints: Iterable[PipRequirement],
        only_binary: Iterable[str],
        no_binary: Iterable[str],
        excludes: Iterable[str],
        overrides: Iterable[str],
        sources: Iterable[str],
    ) -> LockfileMetadataValidation:
        failure_reasons = set()
        if not set(user_requirements).issubset(self.requirements):
            failure_reasons.add(InvalidPythonLockfileReason.REQUIREMENTS_MISMATCH)

        if not self.valid_for_interpreter_constraints.contains(
            user_interpreter_constraints, interpreter_universe
        ):
            failure_reasons.add(InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)


@_python_lockfile_metadata(3)
@dataclass(frozen=True)
class PythonLockfileMetadataV3(PythonLockfileMetadataV2):
    """Lockfile version that considers constraints files."""

    manylinux: str | None
    requirement_constraints: set[PipRequirement]
    only_binary: set[str]
    no_binary: set[str]

    @classmethod
    def _from_json_dict(
        cls: type[PythonLockfileMetadataV3],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> PythonLockfileMetadataV3:
        v2_metadata = super()._from_json_dict(json_dict, lockfile_description, error_suffix)
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)
        manylinux = metadata("manylinux", str, lambda l: l)
        requirement_constraints = metadata(
            "requirement_constraints",
            set[PipRequirement],
            lambda l: {
                PipRequirement.parse(i, description_of_origin=lockfile_description) for i in l
            },
        )
        only_binary = metadata("only_binary", set[str], lambda l: set(l))
        no_binary = metadata("no_binary", set[str], lambda l: set(l))

        return PythonLockfileMetadataV3(
            valid_for_interpreter_constraints=v2_metadata.valid_for_interpreter_constraints,
            requirements=v2_metadata.requirements,
            manylinux=manylinux,
            requirement_constraints=requirement_constraints,
            only_binary=only_binary,
            no_binary=no_binary,
        )

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        instance = cast(PythonLockfileMetadataV3, instance)
        return {
            "manylinux": instance.manylinux,
            "requirement_constraints": sorted(str(i) for i in instance.requirement_constraints),
            "only_binary": sorted(instance.only_binary),
            "no_binary": sorted(instance.no_binary),
        }

    def is_valid_for(
        self,
        *,
        expected_invalidation_digest: str | None,  # Validation digests are not used by V2.
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],
        manylinux: str | None,
        requirement_constraints: Iterable[PipRequirement],
        only_binary: Iterable[str],
        no_binary: Iterable[str],
        # not used for V3
        excludes: Iterable[str],
        overrides: Iterable[str],
        sources: Iterable[str],
    ) -> LockfileMetadataValidation:
        failure_reasons = (
            super()
            .is_valid_for(
                expected_invalidation_digest=expected_invalidation_digest,
                user_interpreter_constraints=user_interpreter_constraints,
                interpreter_universe=interpreter_universe,
                user_requirements=user_requirements,
                manylinux=manylinux,
                requirement_constraints=requirement_constraints,
                only_binary=only_binary,
                no_binary=no_binary,
                excludes=excludes,
                overrides=overrides,
                sources=sources,
            )
            .failure_reasons
        )

        if self.manylinux != manylinux:
            failure_reasons.add(InvalidPythonLockfileReason.MANYLINUX_MISMATCH)
        if self.requirement_constraints != set(requirement_constraints):
            failure_reasons.add(InvalidPythonLockfileReason.CONSTRAINTS_FILE_MISMATCH)
        if self.only_binary != set(only_binary):
            failure_reasons.add(InvalidPythonLockfileReason.ONLY_BINARY_MISMATCH)
        if self.no_binary != set(no_binary):
            failure_reasons.add(InvalidPythonLockfileReason.NO_BINARY_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)


@_python_lockfile_metadata(4)
@dataclass(frozen=True)
class PythonLockfileMetadataV4(PythonLockfileMetadataV3):
    """Lockfile version with excludes/overrides."""

    excludes: set[str]
    overrides: set[str]

    @classmethod
    def _from_json_dict(
        cls: type[PythonLockfileMetadataV4],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> PythonLockfileMetadataV4:
        v3_metadata = super()._from_json_dict(json_dict, lockfile_description, error_suffix)
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)

        excludes = metadata("excludes", set[str], lambda l: set(l))
        overrides = metadata("overrides", set[str], lambda l: set(l))

        return PythonLockfileMetadataV4(
            valid_for_interpreter_constraints=v3_metadata.valid_for_interpreter_constraints,
            requirements=v3_metadata.requirements,
            manylinux=v3_metadata.manylinux,
            requirement_constraints=v3_metadata.requirement_constraints,
            only_binary=v3_metadata.only_binary,
            no_binary=v3_metadata.no_binary,
            excludes=excludes,
            overrides=overrides,
        )

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        instance = cast(PythonLockfileMetadataV4, instance)
        return {
            "excludes": sorted(instance.excludes),
            "overrides": sorted(instance.overrides),
        }

    def is_valid_for(
        self,
        *,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],
        manylinux: str | None,
        requirement_constraints: Iterable[PipRequirement],
        only_binary: Iterable[str],
        no_binary: Iterable[str],
        excludes: Iterable[str],
        overrides: Iterable[str],
        # not used for V4
        sources: Iterable[str],
    ) -> LockfileMetadataValidation:
        failure_reasons = (
            super()
            .is_valid_for(
                expected_invalidation_digest=expected_invalidation_digest,
                user_interpreter_constraints=user_interpreter_constraints,
                interpreter_universe=interpreter_universe,
                user_requirements=user_requirements,
                manylinux=manylinux,
                requirement_constraints=requirement_constraints,
                only_binary=only_binary,
                no_binary=no_binary,
                excludes=excludes,
                overrides=overrides,
                sources=sources,
            )
            .failure_reasons
        )

        if self.excludes != set(excludes):
            failure_reasons.add(InvalidPythonLockfileReason.EXCLUDES_MISMATCH)
        if self.overrides != set(overrides):
            failure_reasons.add(InvalidPythonLockfileReason.OVERRIDES_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)


@_python_lockfile_metadata(5)
@dataclass(frozen=True)
class PythonLockfileMetadataV5(PythonLockfileMetadataV4):
    """Lockfile version with sources."""

    sources: set[str]

    @classmethod
    def _from_json_dict(
        cls: type[PythonLockfileMetadataV5],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> PythonLockfileMetadataV5:
        v4_metadata = PythonLockfileMetadataV4._from_json_dict(
            json_dict, lockfile_description, error_suffix
        )
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)

        sources = metadata("sources", set[str], lambda l: set(l))

        return PythonLockfileMetadataV5(
            valid_for_interpreter_constraints=v4_metadata.valid_for_interpreter_constraints,
            requirements=v4_metadata.requirements,
            manylinux=v4_metadata.manylinux,
            requirement_constraints=v4_metadata.requirement_constraints,
            only_binary=v4_metadata.only_binary,
            no_binary=v4_metadata.no_binary,
            excludes=v4_metadata.excludes,
            overrides=v4_metadata.overrides,
            sources=sources,
        )

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        instance = cast(PythonLockfileMetadataV5, instance)
        return {
            "sources": sorted(instance.sources),
        }

    def is_valid_for(
        self,
        *,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],
        manylinux: str | None,
        requirement_constraints: Iterable[PipRequirement],
        only_binary: Iterable[str],
        no_binary: Iterable[str],
        excludes: Iterable[str],
        overrides: Iterable[str],
        sources: Iterable[str],
    ) -> LockfileMetadataValidation:
        failure_reasons = (
            super()
            .is_valid_for(
                expected_invalidation_digest=expected_invalidation_digest,
                user_interpreter_constraints=user_interpreter_constraints,
                interpreter_universe=interpreter_universe,
                user_requirements=user_requirements,
                manylinux=manylinux,
                requirement_constraints=requirement_constraints,
                only_binary=only_binary,
                no_binary=no_binary,
                excludes=excludes,
                overrides=overrides,
                sources=sources,
            )
            .failure_reasons
        )

        if self.sources != set(sources):
            failure_reasons.add(InvalidPythonLockfileReason.SOURCES_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)
