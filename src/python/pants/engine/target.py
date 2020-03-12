# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterable, Optional, Tuple, Type, TypeVar, cast

from pants.engine.rules import UnionMembership
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class Field(ABC):
    alias: ClassVar[str]
    raw_value: Optional[Any]  # None indicates that the field was not explicitly defined

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
        """Get the field's value.

        The value will possibly be first hydrated and/or validated, such as using a default value
        if the field was not defined or ensuring that an int value is positive.

        This property is memoized because hydration and validation can often be costly. This
        hydration is lazy, i.e. it will only happen when a downstream rule explicitly requests this
        field.
        """


class AsyncField(Field, metaclass=ABCMeta):
    """A field that needs the engine in order to be hydrated.

    You should create a corresponding Result class and define a rule to go from this AsyncField to
    the Result. For example:

        class Sources(AsyncField):
            alias: ClassVar = "sources"
            raw_value: Optional[List[str]]


        @dataclass(frozen=True)
        class SourcesResult:
            snapshot: Snapshot


        @rule
        def hydrate_sources(sources: Sources) -> SourcesResult:
            sources.validate_pre_hydration()
            result = await Get[Snapshot](PathGlobs(sources.raw_value))
            sources.validate_post_hydration(result)
            return SourcesResult(result)


        def rules():
            return [hydrate_sources]

    Then, call sites can `await Get` if they need to hydrate the field:

        sources = await Get[SourcesResult](Sources, my_tgt.get(Sources))
    """

    def validate_pre_hydration(self) -> None:
        """Any validation that can be done on the original `raw_value`.

        It is cheaper to do any possible validation here, rather than in `validate_post_hydration`,
        because we can short-circuit if an invariant is violated before incurring the expense of
        hydration.
        """

    def validate_post_hydration(self, result: Any) -> None:
        """Any validation that must be done after hydration by inspecting the result of that
        hydration.

        For example, a `PythonSources` field may validate that all hydrated source files end in
        `.py`.
        """


class PluginField:
    """Allows plugin authors to add new fields to pre-existing target types via UnionRules.

    When defining a Target, authors should create a corresponding PluginField class marked with
    `@union`. Then, plugin authors simply need to create whatever new `Field` they want and in a
    `register.py`'s `rules()` function, call `UnionRule`. For example, to add a
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
            return [UnionRule(PythonLibraryField, TypeChecked)]
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
        aliases_to_field_types = {field_type.alias: field_type for field_type in self.field_types}
        for alias, value in unhydrated_values.items():
            if alias not in aliases_to_field_types:
                raise ValueError(
                    f"Unrecognized field `{alias}={value}` for target type `{self.alias}`."
                )
            field_type = aliases_to_field_types[alias]
            self.field_values[field_type] = field_type(value)
        # For undefined fields, mark the raw value as None.
        for field_type in set(self.field_types) - set(self.field_values.keys()):
            self.field_values[field_type] = field_type(raw_value=None)

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

    def has_fields(self, fields: Iterable[Type[Field]]) -> bool:
        # TODO: consider if this should support subclasses. For example, if a target has a
        #  field PythonSources(Sources), then .has_fields(Sources) should still return True. Why?
        #  This allows overriding how fields behave for custom target types, e.g. a `python3_library`
        #  subclassing the Field Compatibility with its own custom Python3Compatibility field.
        #  When adding this, be sure to update `.get()` to allow looking up by subclass, too.
        #  (Is it possible to do that in a performant way, i.e. w/o having to iterate over every
        #  self.field_type (O(n) vs the current O(1))?)
        return all(field in self.field_types for field in fields)
