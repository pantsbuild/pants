# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Tuple, Type, TypeVar, Union, cast

from typing_extensions import final

from pants.build_graph.address import Address
from pants.engine.fs import Snapshot
from pants.engine.rules import UnionMembership
from pants.util.collections import ensure_str_list
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)  # type: ignore[misc]  # MyPy doesn't like the abstract __init__()
class Field(ABC):
    alias: ClassVar[str]

    # This is a little weird to have an abstract __init__(). We do this to ensure that all
    # subclasses have this exact type signature for their constructor.
    #
    # Normally, with dataclasses, each constructor parameter would instead be specified via a
    # dataclass field declaration. But, we don't want to declare either `address` or `raw_value` as
    # attributes because we make no assumptions whether the subclasses actually store those values
    # on each instance. All that we care about is a common constructor interface.
    @abstractmethod
    def __init__(self, raw_value: Optional[Any], *, address: Address) -> None:
        pass


class PrimitiveField(Field, metaclass=ABCMeta):
    """A Field that does not need the engine in order to be hydrated.

    This should be used by the majority of fields.

    Subclasses must implement `hydrate()` to convert the `raw_value` into `self.value`. This
    hydration and/or validation happens eagerly in the constructor. If the hydration is
    particularly expensive, use `AsyncField` instead to get the benefits of the engine's caching.

    The hydrated `value` must be immutable and hashable so that this Field may be used by the
    V2 engine. This means, for example, using tuples rather than lists and using
    `FrozenOrderedSet` rather than `set`.

    Subclasses should also override the type hints for `value` to be more precise than `Any`.

    Example:

        class ZipSafe(PrimitiveField):
            alias: ClassVar = "zip_safe"
            value: bool

            def hydrate(self, raw_value: Optional[bool], *, address: Address) -> bool:
                if raw_value is None:
                    return True
                return raw_value
    """

    value: Any

    @final
    def __init__(self, raw_value: Optional[Any], *, address: Address) -> None:
        # NB: We neither store the `address` or `raw_value` as attributes on this dataclass:
        # * Don't store `raw_value` because it very often is mutable and/or unhashable, which means
        #   this Field could not be passed around in the engine.
        # * Don't store `address` to avoid the cost in memory of storing `Address` on every single
        #   field encountered by Pants in a run.
        self.value = self.hydrate(raw_value, address=address)

    @abstractmethod
    def hydrate(self, raw_value: Optional[Any], *, address: Address) -> Any:
        """Convert the `raw_value` into `self.value`.

        You should perform any validation and/or hydration here. For example, you may want to check
        that an integer is > 0, apply a default value if `raw_value` is None, or convert an
        Iterable[str] to List[str].

        The resulting value should be immutable and hashable.

        If you have no validation/hydration, simply set this function to `return raw_value`.
        """

    def __repr__(self) -> str:
        return f"{self.__class__}(alias={repr(self.alias)}, value={self.value})"

    def __str__(self) -> str:
        return f"{self.alias}={self.value}"


class AsyncField(Field, metaclass=ABCMeta):
    """A field that needs the engine in order to be hydrated.

    You must implement `sanitize_raw_value()` to convert the `raw_value` into a type that is
    immutable and hashable so that this Field may be used by the V2 engine. This means, for example,
    using tuples rather than lists and using `FrozenOrderedSet` rather than `set`.

    You should also create a corresponding Result class and define a rule to go from this
    AsyncField to the Result.

    For example:

        class Sources(AsyncField):
            alias: ClassVar = "sources"
            sanitized_raw_value: Optional[Tuple[str, ...]]

            def sanitize_raw_value(
                raw_value: Optional[List[str]], *, address: Address
            ) -> Optional[Tuple[str, ...]]:
                ...


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

    address: Address
    sanitized_raw_value: Any

    @final
    def __init__(self, raw_value: Optional[Any], *, address: Address) -> None:
        self.address = address
        self.sanitized_raw_value = self.sanitize_raw_value(raw_value)

    @abstractmethod
    def sanitize_raw_value(self, raw_value: Optional[Any]) -> Any:
        """Sanitize the `raw_value` into a type that is safe for the V2 engine to use.

        The resulting type should be immutable and hashable.

        You may also do light-weight validation in this method, such as ensuring that all
        elements of a list are strings.
        """

    def __repr__(self) -> str:
        return (
            f"{self.__class__}(alias={self.alias}, sanitized_raw_value={self.sanitized_raw_value})"
        )

    def __str__(self) -> str:
        return f"{self.alias}={self.sanitized_raw_value}"


# NB: This TypeVar is what allows `Target.get()` to properly work with MyPy so that MyPy knows
# the precise Field returned.
_F = TypeVar("_F", bound=Field)


@frozen_after_init
@dataclass(unsafe_hash=True)
class Target(ABC):
    """A Target represents a combination of fields that are valid _together_."""

    # Subclasses must define these
    alias: ClassVar[str]
    core_fields: ClassVar[Tuple[Type[Field], ...]]

    # These get calculated in the constructor
    address: Address
    plugin_fields: Tuple[Type[Field], ...]
    field_values: Dict[Type[Field], Field]

    @final
    def __init__(
        self,
        unhydrated_values: Dict[str, Any],
        *,
        address: Address,
        union_membership: Optional[UnionMembership] = None,
    ) -> None:
        self.address = address
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
                    f"Unrecognized field `{alias}={value}` for target {address} with target "
                    f"type `{self.alias}`."
                )
            field_type = aliases_to_field_types[alias]
            self.field_values[field_type] = field_type(value, address=address)
        # For undefined fields, mark the raw value as None.
        for field_type in set(self.field_types) - set(self.field_values.keys()):
            self.field_values[field_type] = field_type(raw_value=None, address=address)

    @final
    @property
    def field_types(self) -> Tuple[Type[Field], ...]:
        return (*self.core_fields, *self.plugin_fields)

    @final
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
            f"address={self.address}, "
            f"alias={repr(self.alias)}, "
            f"core_fields={list(self.core_fields)}, "
            f"plugin_fields={list(self.plugin_fields)}, "
            f"field_values={list(self.field_values.values())}"
            f")"
        )

    def __str__(self) -> str:
        fields = ", ".join(str(field) for field in self.field_values.values())
        address = f"address=\"{self.address}\"{', ' if fields else ''}"
        return f"{self.alias}({address}{fields})"

    @final
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

    @final
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

    @final
    def has_fields(self, fields: Iterable[Type[Field]]) -> bool:
        unrecognized_fields = [field for field in fields if field not in self.field_types]
        if not unrecognized_fields:
            return True
        for unrecognized_field in unrecognized_fields:
            if self._find_registered_field_subclass(unrecognized_field) is None:
                return False
        return True


# TODO: add light-weight runtime type checking to these helper fields, such as ensuring that
# the raw_value of `BoolField` is in fact a `bool` and not an int or str. Use `instanceof`. All
# the types are primitive objects like `str` and `int`, so this should be performant and easy to
# implement.
#
# We should also sort where relevant, e.g. in `StringSequenceField`. This is important for cacahe
# hits.


class BoolField(PrimitiveField):
    value: bool
    default: ClassVar[bool]

    def hydrate(self, raw_value: Optional[bool], *, address: Address) -> bool:
        if raw_value is None:
            return self.default
        return raw_value


class StringField(PrimitiveField):
    value: Optional[str]

    def hydrate(self, raw_value: Optional[str], *, address: Address) -> Optional[str]:
        return raw_value


class StringSequenceField(PrimitiveField):
    value: Optional[Tuple[str, ...]]

    def hydrate(
        self, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Optional[Tuple[str, ...]]:
        if raw_value is None:
            return None
        return tuple(raw_value)


class StringOrStringSequenceField(PrimitiveField):
    """The raw_value may either be a string or be an iterable of strings.

    This is syntactic sugar that we use for certain fields to make BUILD files simpler when the user
    has no need for more than one element.

    Generally, this should not be used by any new Fields. This mechanism is a misfeature.
    """

    value: Optional[Tuple[str, ...]]

    def hydrate(
        self, raw_value: Optional[Union[str, Iterable[str]]], *, address: Address
    ) -> Optional[Tuple[str, ...]]:
        if raw_value is None:
            return None
        return tuple(ensure_str_list(raw_value))


class Tags(StringSequenceField):
    alias: ClassVar = "tags"


# TODO: figure out what support looks like for this. This already gets hydrated into a
#  List[Address] by the time we have a HydratedStruct. Should it stay that way, or should it go
#  back to being a List[str] and we only hydrate into Addresses when necessary? Alternatively, does
#  hydration mean getting back `Targets`?
class Dependencies(AsyncField):
    alias: ClassVar = "dependencies"
    sanitized_raw_value: Optional[Tuple[Address, ...]]

    def sanitize_raw_value(
        self, raw_value: Optional[List[Address]]
    ) -> Optional[Tuple[Address, ...]]:
        if raw_value is None:
            return None
        return tuple(raw_value)


COMMON_TARGET_FIELDS = (Dependencies, Tags)


# TODO: implement the hydration for this so that you can
#  `await Get[SourcesResult](Sources, my_tgt.get(Sources)`. Tricky part of this...this _must_
#  support subclassing the field to give custom behavior.
class Sources(AsyncField):
    alias: ClassVar = "sources"
    default_globs: ClassVar[Optional[Tuple[str, ...]]] = None
    sanitized_raw_value: Optional[Tuple[str, ...]]

    def sanitize_raw_value(self, raw_value: Optional[Iterable[str]]) -> Optional[Tuple[str, ...]]:
        if raw_value is None:
            return None
        return tuple(raw_value)

    @classmethod
    def validate_result(cls, _: "SourcesResult") -> None:
        pass


@dataclass(frozen=True)
class SourcesResult:
    address: Address
    snapshot: Snapshot
