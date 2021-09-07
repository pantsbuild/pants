# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Type, TypeVar

from pkg_resources import Requirement

from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet

BEGIN_LOCKFILE_HEADER = b"# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---"
END_LOCKFILE_HEADER = b"# --- END PANTS LOCKFILE METADATA ---"

LOCKFILE_VERSION = 1


_concrete_metadata_classes: dict[int, Type[LockfileMetadata]] = {}

LockfileSubclass = TypeVar("LockfileSubclass")


def _lockfile_metadata_version(
    version: int,
) -> Callable[[Type[LockfileMetadata]], Type[LockfileMetadata]]:
    """Decorator to register a Lockfile metadata version subclass with a given version number."""

    def _dec(cls: Type[LockfileMetadata]) -> Type[LockfileMetadata]:
        _concrete_metadata_classes[version] = cls
        return cls

    return _dec


class InvalidLockfileError(Exception):
    pass


@dataclass
class LockfileMetadata:
    """Base class for metadata that is attached to a given lockfiles.

    This class, and provides the external API for serializing, deserializing, and validating the
    contents of individual lockfiles. New versions of metadata implement a concrete subclass and
    provide deserialization and validation logic, along with specialist serialization logic.

    To construct an instance of the most recent concrete subclass, call `LockfileMetadata.new()`.
    """

    requirements_invalidation_digest: str | None
    valid_for_interpreter_constraints: InterpreterConstraints

    @staticmethod
    def new(
        requirements_invalidation_digest: str | None,
        valid_for_interpreter_constraints: InterpreterConstraints,
        requirements: set[Requirement],
    ) -> LockfileMetadata:
        """Call the most recent version of the `LockfileMetadata` class to construct a concrete
        instance.

        This static method should be used in place of the `LockfileMetadata` constructor.
        """

        return LockfileMetadataV2(
            requirements_invalidation_digest, valid_for_interpreter_constraints, requirements
        )

    @staticmethod
    def from_lockfile(
        lockfile: bytes, lockfile_path: str | None = None, resolve_name: str | None = None
    ) -> LockfileMetadata:
        """Parse all relevant metadata from the lockfile's header."""
        in_metadata_block = False
        metadata_lines = []
        for line in lockfile.splitlines():
            if line == BEGIN_LOCKFILE_HEADER:
                in_metadata_block = True
            elif line == END_LOCKFILE_HEADER:
                break
            elif in_metadata_block:
                metadata_lines.append(line[2:])

        error_suffix = (
            "To resolve this error, you will need to regenerate the lockfile by running "
            "`./pants generate-lockfiles"
        )
        if resolve_name:
            error_suffix += "--resolve={tool_name}"
        error_suffix += "`."

        if lockfile_path is not None and resolve_name is not None:
            lockfile_description = f"the lockfile `{lockfile_path}` for `{resolve_name}`"
        elif lockfile_path is not None:
            lockfile_description = f"the lockfile `{lockfile_path}`"
        elif resolve_name is not None:
            lockfile_description = f"the lockfile for `{resolve_name}`"
        else:
            lockfile_description = "this lockfile"

        if not metadata_lines:
            raise InvalidLockfileError(
                f"Could not find a pants metadata block in {lockfile_description}. {error_suffix}"
            )

        try:
            metadata = json.loads(b"\n".join(metadata_lines))
        except json.decoder.JSONDecodeError:
            raise InvalidLockfileError(
                f"Metadata header in {lockfile_description} is not a valid JSON string and can't "
                "be decoded. " + error_suffix
            )

        concrete_class = _concrete_metadata_classes[metadata["version"]]

        return concrete_class._from_json_dict(metadata, lockfile_description, error_suffix)

    @classmethod
    def _from_json_dict(
        cls: Type[LockfileSubclass],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> LockfileSubclass:
        """Construct a `LockfileMetadata` subclass from the supplied JSON dict.

        Not implemented. Subclasses should override.
        """

        raise NotImplementedError(
            "`LockfileMetadata._from_json_dict` should not be directly " "called."
        )

    def add_header_to_lockfile(self, lockfile: bytes, *, regenerate_command: str) -> bytes:
        metadata_dict = self._header_dict()
        metadata_json = json.dumps(metadata_dict, ensure_ascii=True, indent=2).splitlines()
        metadata_as_a_comment = "\n".join(f"# {l}" for l in metadata_json).encode("ascii")
        header = b"%b\n%b\n%b" % (BEGIN_LOCKFILE_HEADER, metadata_as_a_comment, END_LOCKFILE_HEADER)

        regenerate_command_bytes = (
            f"# This lockfile was autogenerated by Pants. To regenerate, run:\n#\n"
            f"#    {regenerate_command}"
        ).encode("utf-8")

        return b"%b\n#\n%b\n\n%b" % (regenerate_command_bytes, header, lockfile)

    def _header_dict(self) -> dict[Any, Any]:
        """Produce a dictionary to be serialized into the lockfile header.

        Subclasses should call `super` and update the resulting dictionary
        """

        version: int
        for ver, cls in _concrete_metadata_classes.items():
            if isinstance(self, cls):
                version = ver
                break
        else:
            raise ValueError("Trying to serialize an unregistered `LockfileMetadata` subclass.")

        return {
            "version": version,
            "requirements_invalidation_digest": self.requirements_invalidation_digest,
            "valid_for_interpreter_constraints": [
                str(ic) for ic in self.valid_for_interpreter_constraints
            ],
        }

    def is_valid_for(
        self,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[Requirement],
    ) -> LockfileMetadataValidation:
        """Returns Truthy if this `LockfileMetadata` can be used in the current execution
        context."""

        raise NotImplementedError("call `is_valid_for` on subclasses only")


@_lockfile_metadata_version(1)
@dataclass
class LockfileMetadataV1(LockfileMetadata):

    requirements_invalidation_digest: str

    @classmethod
    def _from_json_dict(
        cls: Type[LockfileMetadataV1],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> LockfileMetadataV1:
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)

        requirements_digest = metadata("requirements_invalidation_digest", str, None)
        interpreter_constraints = metadata(
            "valid_for_interpreter_constraints", InterpreterConstraints, InterpreterConstraints
        )

        return LockfileMetadataV1(requirements_digest, interpreter_constraints)

    def is_valid_for(
        self,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[Requirement],
    ) -> LockfileMetadataValidation:
        failure_reasons: set[InvalidLockfileReason] = set()

        if expected_invalidation_digest is None:
            return LockfileMetadataValidation(failure_reasons)

        if self.requirements_invalidation_digest != expected_invalidation_digest:
            failure_reasons.add(InvalidLockfileReason.INVALIDATION_DIGEST_MISMATCH)

        if not self.valid_for_interpreter_constraints.contains(
            user_interpreter_constraints, interpreter_universe
        ):
            failure_reasons.add(InvalidLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)


@_lockfile_metadata_version(2)
@dataclass
class LockfileMetadataV2(LockfileMetadata):
    """Lockfile version that permits specifying a requirements set instead of a requirements digest.

    When a requirements digest is not set, validity is tested by checking whether the expected
    requirements are a subset of the requirements specified in this metadata.
    """

    requirements: set[Requirement] | None

    @classmethod
    def _from_json_dict(
        cls: Type[LockfileMetadataV2],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> LockfileMetadataV2:
        metadata = _get_metadata(json_dict, lockfile_description, error_suffix)

        requirements_digest = metadata("requirements_invalidation_digest", str, None)
        requirements = metadata(
            "requirements", set[Requirement], lambda l: {Requirement.parse(i) for i in l}
        )
        interpreter_constraints = metadata(
            "valid_for_interpreter_constraints", InterpreterConstraints, InterpreterConstraints
        )

        return LockfileMetadataV2(requirements_digest, interpreter_constraints, requirements)

    def _header_dict(self) -> dict[Any, Any]:
        out = super()._header_dict()

        # Requirements need to be stringified then sorted (in that order) so that tests are
        # deterministic.
        out["requirements"] = (
            sorted([str(i) for i in self.requirements]) if self.requirements is not None else None
        )
        return out

    def is_valid_for(
        self,
        expected_invalidation_digest: str | None,
        user_interpreter_constraints: InterpreterConstraints,
        interpreter_universe: Iterable[str],
        user_requirements: Iterable[Requirement],
    ) -> LockfileMetadataValidation:
        failure_reasons: set[InvalidLockfileReason] = set()

        # TODO: Confirm behaviour when there's no digest -- if there's no case where we will not
        # supply requirements, then we don't need a way to bail out here. (cf. v0 where we bail out
        # if there is no expected digest.)

        if self.requirements_invalidation_digest != expected_invalidation_digest:
            failure_reasons.add(InvalidLockfileReason.INVALIDATION_DIGEST_MISMATCH)

        if self.requirements is not None and not self.requirements.issuperset(user_requirements):
            failure_reasons.add(InvalidLockfileReason.REQUIREMENTS_MISMATCH)

        if not self.valid_for_interpreter_constraints.contains(
            user_interpreter_constraints, interpreter_universe
        ):
            failure_reasons.add(InvalidLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH)

        return LockfileMetadataValidation(failure_reasons)


def calculate_invalidation_digest(requirements: Iterable[str]) -> str:
    """Returns an invalidation digest for the given requirements."""
    m = hashlib.sha256()
    inputs = {
        # `FrozenOrderedSet` deduplicates while keeping ordering, which speeds up the sorting if
        # the input was already sorted.
        "requirements": sorted(FrozenOrderedSet(requirements)),
    }
    m.update(json.dumps(inputs).encode("utf-8"))
    return m.hexdigest()


class InvalidLockfileReason(Enum):
    INVALIDATION_DIGEST_MISMATCH = "invalidation_digest_mismatch"
    INTERPRETER_CONSTRAINTS_MISMATCH = "interpreter_constraints_mismatch"
    REQUIREMENTS_MISMATCH = "requirements_mismatch"


class LockfileMetadataValidation:
    """Boolean-like value which additionally carries reasons why a validation failed."""

    failure_reasons: set[InvalidLockfileReason]

    def __init__(self, failure_reasons: Iterable[InvalidLockfileReason] = ()):
        self.failure_reasons = set(failure_reasons)

    def __bool__(self):
        return not self.failure_reasons


T = TypeVar("T")


def _get_metadata(
    metadata: dict[Any, Any],
    lockfile_description: str,
    error_suffix: str,
) -> Callable[[str, Type[T], Callable[[Any], T] | None], T]:
    """Returns a function that will get a given key from the `metadata` dict, and optionally do some
    verification and post-processing to return a value of the correct type."""

    def get_metadata(key: str, type_: Type[T], coerce: Callable[[Any], T] | None) -> T:
        val: Any
        try:
            val = metadata[key]
        except KeyError:
            raise InvalidLockfileError(
                f"Required key `{key}` is not present in metadata header for "
                f"{lockfile_description}. {error_suffix}"
            )

        if not coerce:
            if isinstance(val, type_):
                return val

            # TODO(#12314): Add a good error about invalid data type.
            raise InvalidLockfileError(
                f"Metadata value `{key}` in {lockfile_description} must "
                f"be a {type(type_).__name__}. {error_suffix}"
            )
        else:
            try:
                return coerce(val)
            except Exception:
                # TODO(#12314): Add a good error about invalid data type.
                raise InvalidLockfileError(
                    f"Metadata value `{key}` in {lockfile_description} must be able to "
                    f"be converted to a {type(type_).__name__}. {error_suffix}"
                )

    return get_metadata
