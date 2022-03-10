# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, ClassVar, Generic, Iterable, Tuple, Type, TypeVar, cast

from pants.util.docutil import bin_name
from pants.util.ordered_set import FrozenOrderedSet

BEGIN_LOCKFILE_HEADER = b"# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---"
END_LOCKFILE_HEADER = b"# --- END PANTS LOCKFILE METADATA ---"


class LockfileScope(Enum):
    JVM = "jvm"
    PYTHON = "python"


_LockfileMetadataSubclass = TypeVar("_LockfileMetadataSubclass", bound="LockfileMetadata")
# N.B. the value type is `type[_LockfileMetadataSubclass]`
_concrete_metadata_classes: dict[Tuple[LockfileScope, int], type] = {}


# Registrar types (pre-declaring to avoid repetition)
RegisterClassForVersion = Callable[[Type["LockfileMetadata"]], Type["LockfileMetadata"]]


def lockfile_metadata_registrar(scope: LockfileScope) -> Callable[[int], RegisterClassForVersion]:
    """Decorator factory -- returns a decorator that can be used to register Lockfile metadata
    version subclasses belonging to a specific `LockfileScope`."""

    def _lockfile_metadata_version(
        version: int,
    ) -> RegisterClassForVersion:
        """Decorator to register a Lockfile metadata version subclass with a given version number.

        The class must be a frozen dataclass
        """

        def _dec(cls: Type[LockfileMetadata]) -> Type[LockfileMetadata]:

            # Only frozen dataclasses may be registered as lockfile metadata:
            cls_dataclass_params = getattr(cls, "__dataclass_params__", None)
            if not cls_dataclass_params or not cls_dataclass_params.frozen:
                raise ValueError(
                    "Classes registered with `_lockfile_metadata_version` may only be "
                    "frozen dataclasses"
                )
            _concrete_metadata_classes[(scope, version)] = cls
            return cls

        return _dec

    return _lockfile_metadata_version


class InvalidLockfileError(Exception):
    pass


@dataclass(frozen=True)
class LockfileMetadata:
    """Base class for metadata that is attached to a given lockfile.

    This class provides the external API for serializing, deserializing, and validating the
    contents of individual lockfiles. New versions of metadata implement a concrete subclass and
    provide deserialization and validation logic, along with specialist serialization logic.

    To construct an instance of the most recent concrete subclass, call `LockfileMetadata.new()`.
    """

    # N.B. This __must not__ change between multiple versions of a lockfile metadata for a
    # particular scope. The delimeter for version 1 must be the delimeter for version N.
    delimeter: ClassVar[str]
    scope: ClassVar[LockfileScope]

    @classmethod
    def from_lockfile(
        cls: type[_LockfileMetadataSubclass],
        lockfile: bytes,
        lockfile_path: str | None = None,
        resolve_name: str | None = None,
    ) -> _LockfileMetadataSubclass:
        """Parse and return the metadata from the lockfile's header.

        This shouldn't be called on `LockfileMetadata`, but rather on the "base class" for your
        metadata class. See the existing callers for an example.
        """
        assert cls is not LockfileMetadata, "Call me on a subclass!"
        in_metadata_block = False
        metadata_lines = []
        for line in lockfile.splitlines():
            if line == BEGIN_LOCKFILE_HEADER:
                in_metadata_block = True
            elif line == END_LOCKFILE_HEADER:
                break
            elif in_metadata_block:
                metadata_lines.append(line[len(cls.delimeter) + 1 :])

        error_suffix = (
            "To resolve this error, you will need to regenerate the lockfile by running "
            f"`{bin_name()} generate-lockfiles"
        )
        if resolve_name:
            error_suffix += f" --resolve={resolve_name}"
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
                f"Could not find a Pants metadata block in {lockfile_description}. {error_suffix}"
            )

        try:
            metadata = json.loads(b"\n".join(metadata_lines))
        except json.decoder.JSONDecodeError:
            raise InvalidLockfileError(
                f"Metadata header in {lockfile_description} is not a valid JSON string and can't "
                "be decoded. " + error_suffix
            )

        version = metadata.get("version", 1)
        concrete_class = _concrete_metadata_classes[(cls.scope, version)]

        assert issubclass(concrete_class, cls)
        assert concrete_class.delimeter == cls.delimeter, (
            "Delimeters __must not__ change between versions for a given scope. "
            f"Expected '{concrete_class.delimeter}', got '{cls.delimeter}'"
        )

        assert concrete_class.scope == cls.scope, (
            "The class used to call `from_lockfile` has a different scope than what was "
            f"expected given the metadata. Expected '{cls.scope}', got '{concrete_class.scope}'",
        )

        return concrete_class._from_json_dict(metadata, lockfile_description, error_suffix)

    @classmethod
    def _from_json_dict(
        cls: type[_LockfileMetadataSubclass],
        json_dict: dict[Any, Any],
        lockfile_description: str,
        error_suffix: str,
    ) -> _LockfileMetadataSubclass:
        """Construct a `LockfileMetadata` subclass from the supplied JSON dict.

        *** Not implemented. Subclasses should override. ***


        `lockfile_description` is a detailed, human-readable description of the lockfile, which can
        be read by the user to figure out which lockfile is broken in case of an error.

        `error_suffix` is a string describing how to fix the lockfile.
        """

        raise NotImplementedError(
            "`LockfileMetadata._from_json_dict` should not be directly called."
        )

    def add_header_to_lockfile(self, lockfile: bytes, *, regenerate_command: str) -> bytes:
        metadata_dict = self.__render_header_dict()
        metadata_json = json.dumps(metadata_dict, ensure_ascii=True, indent=2).splitlines()
        metadata_as_a_comment = "\n".join(f"{self.delimeter} {l}" for l in metadata_json).encode(
            "ascii"
        )
        header = b"%b\n%b\n%b" % (BEGIN_LOCKFILE_HEADER, metadata_as_a_comment, END_LOCKFILE_HEADER)

        regenerate_command_bytes = (
            f"{self.delimeter} This lockfile was autogenerated by Pants. To regenerate, run:\n"
            f"{self.delimeter}\n"
            f"{self.delimeter}    {regenerate_command}"
        ).encode()

        return b"%b\n%b\n%b\n\n%b" % (
            regenerate_command_bytes,
            self.delimeter.encode(),
            header,
            lockfile,
        )

    def __render_header_dict(self) -> dict[Any, Any]:
        """Produce a dictionary to be serialized into the lockfile header.

        Each class should implement a class method called `additional_header_attrs`, which returns a
        `dict` containing the metadata attributes that should be stored in the lockfile.
        """

        attrs: dict[Any, Tuple[Any, Type]] = {}  # attr name -> (value, where we first saw it)
        for cls in reversed(self.__class__.__mro__[:-1]):
            new_attrs = cast(LockfileMetadata, cls).additional_header_attrs(self)
            for attr in new_attrs:
                if attr in attrs and attrs[attr][0] != new_attrs[attr]:
                    raise AssertionError(
                        f"Lockfile header attribute `{attr}` was returned by both "
                        f"`{attrs[attr][1]}` and `{cls}`, returning different values. If these "
                        "classes return the same attribute, they must also return the same "
                        "value."
                    )
                attrs[attr] = new_attrs[attr], cls

        return {key: val[0] for key, val in attrs.items()}

    @classmethod
    def additional_header_attrs(cls, instance: LockfileMetadata) -> dict[Any, Any]:
        return {"version": instance.metadata_version()}

    def metadata_version(self):
        """Returns the version number for this metadata class, or raises an exception.

        To avoid raising an exception, ensure the subclass is decorated with
        `lockfile_metadata_version`
        """
        for (scope, ver), cls in _concrete_metadata_classes.items():
            if isinstance(self, cls):
                return ver
        raise ValueError("Trying to serialize an unregistered `LockfileMetadata` subclass.")


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


T = TypeVar("T")


class LockfileMetadataValidation(Generic[T]):
    """Boolean-like value which additionally carries reasons why a validation failed."""

    failure_reasons: set[T]

    def __init__(self, failure_reasons: Iterable[T] = ()):
        self.failure_reasons = set(failure_reasons)

    def __bool__(self):
        return not self.failure_reasons


def _get_metadata(
    metadata: dict[Any, Any],
    lockfile_description: str,
    error_suffix: str,
) -> Callable[[str, type[T], Callable[[Any], T] | None], T]:
    """Returns a function that will get a given key from the `metadata` dict, and optionally do some
    verification and post-processing to return a value of the correct type."""

    def get_metadata(key: str, type_: type[T], coerce: Callable[[Any], T] | None) -> T:
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

            raise InvalidLockfileError(
                f"Metadata value `{key}` in {lockfile_description} must "
                f"be a {type(type_).__name__}. {error_suffix}"
            )
        else:
            try:
                return coerce(val)
            except Exception:
                raise InvalidLockfileError(
                    f"Metadata value `{key}` in {lockfile_description} must be able to "
                    f"be converted to a {type(type_).__name__}. {error_suffix}"
                )

    return get_metadata
