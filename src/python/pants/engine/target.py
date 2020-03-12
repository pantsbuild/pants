# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Tuple, Type, TypeVar, Union, cast

from pants.engine.objects import union
from pants.engine.rules import UnionMembership
from pants.util.collections import ensure_str_list
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class Field(ABC):
    alias: ClassVar[str]
    raw_value: Optional[Any] = None  # None indicates that the field was not explicitly defined

    def __repr__(self) -> str:
        return f"{self.__class__}(alias={repr(self.alias)}, raw_value={self.raw_value})"


class PrimitiveField(Field, metaclass=ABCMeta):
    """A Field that does not need the engine in order to be hydrated.

    This should be subclassed by the majority of fields.
    """

    def __str__(self) -> str:
        return f"{self.alias}={self.value}"

    @memoized_property
    @abstractmethod
    def value(self) -> Any:
        """Get the underlying value.

        The value will possibly be first hydrated and/or validated, such as converting a field that
        might be a single string or a list of strings to always being a list of strings.

        This property is memoized because hydration and validation can often be costly. This
        hydration is lazy, i.e. will only happen when a downstream rule explicitly requests this
        field.
        """


class AsyncField(Field, metaclass=ABCMeta):
    """A field that needs the engine in order to be hydrated."""

    # TODO: what should this be?
    @memoized_property
    @abstractmethod
    def value_request(self) -> Any:
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


_F = TypeVar("_F", bound=Field)


@frozen_after_init
@dataclass(unsafe_hash=True)
class Target(ABC):
    # Subclasses must define these
    alias: ClassVar[str]
    core_fields: ClassVar[Tuple[Type[Field], ...]]
    plugin_field_type: ClassVar[Type[PluginField]]

    # These get calculated in the constructor
    plugin_fields: Tuple[Type[Field], ...]
    field_values: Dict[Type[Field], Any]

    def __init__(
        self,
        unhydrated_values: Dict[str, Any],
        *,
        union_membership: Optional[UnionMembership] = None,
    ) -> None:
        self.plugin_fields = cast(
            Tuple[Type[Field], ...],
            (
                ()
                if union_membership is None
                else tuple(union_membership.union_rules.get(self.plugin_field_type, ()))
            ),
        )

        self.field_values = {}
        for alias, value in unhydrated_values.items():
            field = next((field for field in self.field_types if field.alias == alias), None)
            if field is None:
                raise ValueError(
                    f"Unrecognized field `{alias}={value}` for target type `{self.alias}`."
                )
            self.field_values[field] = field(value)
        # For missing fields, call their default constructors.
        for field in set(self.field_types) - set(self.field_values.keys()):
            self.field_values[field] = field()

    @property
    def field_types(self) -> Tuple[Type[Field], ...]:
        return (*self.core_fields, *self.plugin_fields)

    def __repr__(self) -> str:
        return (
            f"{self.__class__}("
            f"alias={repr(self.alias)}, "
            f"plugin_field_type={self.plugin_field_type}, "
            f"core_fields={list(self.core_fields)}, "
            f"plugin_fields={list(self.plugin_fields)}, "
            f"raw_field_values={list(self.field_values.values())}"
            f")"
        )

    def __str__(self) -> str:
        fields = ", ".join(str(field) for field in self.field_values.values())
        return f"{self.alias}({fields})"

    def get(self, field: Type[_F]) -> _F:
        return cast(_F, self.field_values[field])


class Sources(AsyncField):
    alias: ClassVar = "sources"
    raw_value: Optional[Iterable[str]] = None

    @memoized_property
    def value_request(self) -> Any:
        return self.raw_value


class BinarySources(Sources):
    @memoized_property
    def value_request(self):
        if self.raw_value is not None and len(list(self.raw_value)) not in [0, 1]:
            raise ValueError("Binary targets must have only 0 or 1 source files.")
        return super().value_request


class Compatibility(PrimitiveField):
    alias: ClassVar = "compatibility"
    raw_value: Optional[Union[str, Iterable[str]]] = None

    @memoized_property
    def value(self) -> Optional[List[str]]:
        if self.raw_value is None:
            return None
        return ensure_str_list(self.raw_value)


class Coverage(PrimitiveField):
    alias: ClassVar = "coverage"
    raw_value: Optional[Union[str, Iterable[str]]] = None

    @memoized_property
    def value(self) -> Optional[List[str]]:
        if self.raw_value is None:
            return None
        return ensure_str_list(self.raw_value)


class Timeout(PrimitiveField):
    alias: ClassVar = "timeout"
    raw_value: Optional[int] = None

    @memoized_property
    def value(self) -> Optional[int]:
        if self.raw_value is None:
            return None
        if not isinstance(self.raw_value, int):
            raise ValueError(
                f"The `timeout` field must be an `int`. Was {type(self.raw_value)} "
                f"({self.raw_value})."
            )
        if self.raw_value <= 0:
            raise ValueError(f"The `timeout` field must be > 1. Was {self.raw_value}.")
        return self.raw_value


class EntryPoint(PrimitiveField):
    alias: ClassVar = "entry_point"
    raw_value: Optional[str] = None

    @memoized_property
    def value(self) -> Optional[str]:
        return self.raw_value


class ZipSafe(PrimitiveField):
    alias: ClassVar = "zip_safe"
    raw_value: Optional[bool] = None

    @memoized_property
    def value(self) -> bool:
        if self.raw_value is None:
            return True
        return self.raw_value


class AlwaysWriteCache(PrimitiveField):
    alias: ClassVar = "always_write_cache"
    raw_value: Optional[bool] = None

    @memoized_property
    def value(self) -> bool:
        if self.raw_value is None:
            return False
        return self.raw_value


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
    plugin_field_type: ClassVar = PythonBinaryField


class PythonLibrary(Target):
    alias: ClassVar = "python_library"
    core_fields: ClassVar = PYTHON_TARGET_FIELDS
    plugin_field_type: ClassVar = PythonLibraryField


class PythonTests(Target):
    alias: ClassVar = "python_tests"
    core_fields: ClassVar = (*PYTHON_TARGET_FIELDS, Coverage, Timeout)
    plugin_field_type: ClassVar = PythonTestsField
