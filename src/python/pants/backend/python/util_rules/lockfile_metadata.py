# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Set, cast

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.lockfile_metadata import (
    LockfileMetadata,
    LockfileMetadataValidation,
    LockfileScope,
    _get_metadata,
    lockfile_metadata_registrar,
)

_python_lockfile_metadata = lockfile_metadata_registrar(LockfileScope.PYTHON)


class InvalidPythonLockfileReason(Enum):
    INVALIDATION_DIGEST_MISMATCH = "invalidation_digest_mismatch"
    INTERPRETER_CONSTRAINTS_MISMATCH = "interpreter_constraints_mismatch"
    REQUIREMENTS_MISMATCH = "requirements_mismatch"


@dataclass(frozen=True)
class PythonLockfileMetadata(LockfileMetadata):

    scope = LockfileScope.PYTHON

    valid_for_interpreter_constraints: InterpreterConstraints

    @staticmethod
    def new(
        valid_for_interpreter_constraints: InterpreterConstraints,
        requirements: set[PipRequirement],
    ) -> LockfileMetadata:
        """Call the most recent version of the `LockfileMetadata` class to construct a concrete
        instance.

        This static method should be used in place of the `LockfileMetadata` constructor. This gives
        calling sites a predictable method to call to construct a new `LockfileMetadata` for
        writing, while still allowing us to support _reading_ older, deprecated metadata versions.
        """

        return PythonLockfileMetadataV2(valid_for_interpreter_constraints, requirements)

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
        is_tool: bool,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],
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
        is_tool: bool,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],  # User requirements are not used by V1
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
            Set[PipRequirement],
            lambda l: {PipRequirement.parse(i) for i in l},
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
        return {
            "generated_with_requirements": (
                sorted(str(i) for i in instance.requirements)
                if instance.requirements is not None
                else None
            )
        }

    def is_valid_for(
        self,
        *,
        is_tool: bool,
        expected_invalidation_digest: str | None,  # Validation digests are not used by V2.
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[PipRequirement],
    ) -> LockfileMetadataValidation:
        failure_reasons = set()

        invalid_reqs = (
            self.requirements != set(user_requirements)
            if is_tool
            else not set(user_requirements).issubset(self.requirements)
        )
        if invalid_reqs:
            failure_reasons.add(InvalidPythonLockfileReason.REQUIREMENTS_MISMATCH)

        if not self.valid_for_interpreter_constraints.contains(
            user_interpreter_constraints, interpreter_universe
        ):
            failure_reasons.add(InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)
