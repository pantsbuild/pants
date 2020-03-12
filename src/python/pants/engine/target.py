# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, List, Optional, Tuple, Type, Union, cast

from pants.engine.objects import union
from pants.engine.rules import UnionMembership
from pants.util.collections import ensure_str_list
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class Field(ABC):
    alias: ClassVar[str]
    unhydrated: Any


@dataclass(frozen=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class PrimitiveField(Field, metaclass=ABCMeta):
    """A Field that does not need the engine in order to be hydrated.

    This applies to the majority of fields.
    """

    @memoized_property
    @abstractmethod
    def hydrated(self) -> Any:
        """Validate and hydrate self.unhydrated into a value usable by downstream rules.

        All validation and hydration should happen here, such as converting a field that might be
        a single string or a list of strings to always being a list of strings.

        This property is memoized because hydration and validation can often be costly. This
        hydration will only happen when a downstream rule explicitly requests this field.
        """


@dataclass(frozen=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class AsyncField(Field, metaclass=ABCMeta):
    """A field that needs the engine in order to be hydrated."""

    # TODO: what should this be?
    @memoized_property
    @abstractmethod
    def hydration_request(self) -> Any:
        pass


class PluginField:
    """Allows plugin authors to add new fields to pre-existing target types via UnionRules.

    When defining a Target, authors should create a corresponding PluginField class marked with
    `@union`. Then, plugin authors simply need to create whatever new `Field` they want and in a
    `register.py`'s `rules()` function call. For example, to add a
    `TypeChecked` field to `python_library`, register `UnionRule(PythonLibraryField, TypeChecked)`.

        @union
        class PythonLibraryField(PluginField):
            pass


        class PythonLibrary(Target):
            core_fields = (Compatibility, PythonSources, ...)
            plugin_field_type = PythonLibraryField


        class TypeChecked(PrimitiveField):
            ...


        def rules():
            return [
                UnionRule(PythonLibraryField, TypeChecked),
            ]
    """


@frozen_after_init
@dataclass(unsafe_hash=True)
class Target(ABC):
    # Subclasses must define these
    alias: ClassVar[str]
    core_fields: ClassVar[Tuple[Type[Field], ...]]
    plugin_field_type: ClassVar[Type[PluginField]]

    # These get calculated in the constructor
    plugin_fields: Tuple[Type[Field], ...]
    field_types: Tuple[Type[Field], ...]

    def __init__(self, *, union_membership: Optional[UnionMembership] = None) -> None:
        self.plugin_fields = cast(
            Tuple[Type[Field], ...],
            (
                ()
                if union_membership is None
                else tuple(union_membership.union_rules.get(self.plugin_field_type, ()))
            ),
        )
        self.field_types = (*self.core_fields, *self.plugin_fields)


@dataclass(frozen=True)
class Sources(AsyncField):
    alias: ClassVar = "sources"
    unhydrated: Optional[Iterable[str]] = None

    @memoized_property
    def hydration_request(self) -> Any:
        """Create a request to hydrate self.unhydrated into ...

        Any validation should happen here.
        """
        return self.unhydrated


@dataclass(frozen=True)
class BinarySources(Sources):
    @memoized_property
    def hydration_request(self):
        if self.unhydrated is not None and len(list(self.unhydrated)) not in [0, 1]:
            raise ValueError("Binary targets must have only 0 or 1 source files.")
        return super().hydration_request


@dataclass(frozen=True)
class Compatibility(PrimitiveField):
    alias: ClassVar = "compatibility"
    unhydrated: Optional[Union[str, Iterable[str]]] = None

    @memoized_property
    def hydrated(self) -> Optional[List[str]]:
        if self.unhydrated is None:
            return None
        return ensure_str_list(self.unhydrated)


@dataclass(frozen=True)
class Coverage(PrimitiveField):
    alias: ClassVar = "coverage"
    unhydrated: Optional[Union[str, Iterable[str]]] = None

    @memoized_property
    def hydrated(self) -> Optional[List[str]]:
        if self.unhydrated is None:
            return None
        return ensure_str_list(self.unhydrated)


@dataclass(frozen=True)
class Timeout(PrimitiveField):
    alias: ClassVar = "timeout"
    unhydrated: Optional[int] = None

    @memoized_property
    def hydrated(self) -> Optional[int]:
        if self.unhydrated is None:
            return None
        if not isinstance(self.unhydrated, int):
            raise ValueError(
                f"The `timeout` field must be an `int`. Was {type(self.unhydrated)} "
                f"({self.unhydrated})."
            )
        if self.unhydrated <= 0:
            raise ValueError(f"The `timeout` field must be > 1. Was {self.unhydrated}.")
        return self.unhydrated


@dataclass(frozen=True)
class EntryPoint(PrimitiveField):
    alias: ClassVar = "entry_point"
    unhydrated: Optional[str] = None

    @memoized_property
    def hydrated(self) -> Optional[str]:
        return self.unhydrated


@dataclass(frozen=True)
class ZipSafe(PrimitiveField):
    alias: ClassVar = "zip_safe"
    unhydrated: bool = True

    @memoized_property
    def hydrated(self) -> bool:
        return self.unhydrated


@dataclass(frozen=True)
class AlwaysWriteCache(PrimitiveField):
    alias: ClassVar = "always_write_cache"
    unhydrated: bool = False

    @memoized_property
    def hydrated(self) -> bool:
        return self.unhydrated


@union
class PythonBinaryField(PluginField):
    pass


@union
class PythonLibraryField(PluginField):
    pass


@union
class PythonTestsField(PluginField):
    pass


PYTHON_TARGET_FIELDS = (Compatibility,)


class PythonBinary(Target):
    alias: ClassVar = "python_binary"
    core_fields: ClassVar = (*PYTHON_TARGET_FIELDS, EntryPoint, ZipSafe, AlwaysWriteCache)
    plugin_field_type = PythonBinaryField


class PythonLibrary(Target):
    alias: ClassVar = "python_library"
    core_fields: ClassVar = PYTHON_TARGET_FIELDS
    plugin_field_type = PythonLibraryField


class PythonTests(Target):
    alias: ClassVar = "python_tests"
    core_fields: ClassVar = (*PYTHON_TARGET_FIELDS, Coverage, Timeout)
    plugin_field_type = PythonTestsField
