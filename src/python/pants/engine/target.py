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
            # possibly validate `sources.raw_value`
            ...
            result = await Get[Snapshot](PathGlobs(sources.raw_value))
            # possibly validate `result`
            ...
            return SourcesResult(result)


        def rules():
            return [hydrate_sources]

    Then, call sites can `await Get` if they need to hydrate the field:

        sources = await Get[SourcesResult](Sources, my_tgt.get(Sources))
    """

    def __str__(self) -> str:
        return f"{self.alias}={repr(self.raw_value)}"


_F = TypeVar("_F", bound=Field)


@frozen_after_init
@dataclass(unsafe_hash=True)
class Target(ABC):
    """A Target represents a combination of fields that are valid _together_."""

    # Subclasses must define these
    alias: ClassVar[str]
    core_fields: ClassVar[Tuple[Type[Field], ...]]

    # These get calculated in the constructor
    plugin_fields: Tuple[Type[Field], ...]
    field_values: Dict[Type[Field], Field]

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
                else tuple(union_membership.union_rules.get(self.PluginField, ()))
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

    class PluginField:
        """A sentinel class to allow plugin authors to add additional fields to this target type.

        Plugin authors may add additional fields by simply registering UnionRules between the
        `Target.PluginField` and the custom field, e.g. `UnionRule(PythonLibrary.PluginField,
        TypeChecked)`. The `Target` will then treat `TypeChecked` as a first-class citizen and
        plugins can use that Field like any other Field.
        """

    def __repr__(self) -> str:
        return (
            f"{self.__class__}("
            f"alias={repr(self.alias)}, "
            f"core_fields={list(self.core_fields)}, "
            f"plugin_fields={list(self.plugin_fields)}, "
            f"raw_field_values={list(self.field_values.values())}"
            f")"
        )

    def __str__(self) -> str:
        fields = ", ".join(str(field) for field in self.field_values.values())
        return f"{self.alias}({fields})"

    def _find_registered_field_subclass(self, requested_field: Type[_F]) -> Optional[Type[_F]]:
        """Check if the Target has registered a subclass of the requested Field.

        This is necessary to allow targets to override the functionality of common fields like
        `Sources`. For example, Python targets may want to have `PythonSources` to add extra
        validation that every source file ends in `*.py`. At the same time, we still want to be able
        to call `my_python_tgt.get(Sources)`, in addition to `my_python_tgt.get(PythonSources)`.
        """
        subclass = next(
            (
                registered_field
                for registered_field in self.field_types
                if issubclass(registered_field, requested_field)
            ),
            None,
        )
        return cast(Optional[Type[_F]], subclass)

    def get(self, field: Type[_F]) -> _F:
        result = self.field_values.get(field, None)
        if result is not None:
            return cast(_F, result)
        field_subclass = self._find_registered_field_subclass(field)
        if field_subclass is not None:
            return cast(_F, self.field_values[field_subclass])
        raise KeyError(
            f"The target `{self}` does not have a field `{field}`. Before calling "
            f"`my_tgt.get({field.__name__})`, call `my_tgt.has_fields([{field.__name__}])` to "
            "filter out any irrelevant Targets."
        )

    def has_fields(self, fields: Iterable[Type[Field]]) -> bool:
        unrecognized_fields = [field for field in fields if field not in self.field_types]
        if not unrecognized_fields:
            return True
        for unrecognized_field in unrecognized_fields:
            if self._find_registered_field_subclass(unrecognized_field) is None:
                return False
        return True
