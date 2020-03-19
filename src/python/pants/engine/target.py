# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Tuple, Type, TypeVar, Union, cast

from typing_extensions import final

from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import RootRule, UnionMembership, rule
from pants.engine.selectors import Get
from pants.util.collections import ensure_str_list
from pants.util.meta import frozen_after_init

# Type alias to express the intent that the type should be immutable and hashable. There's nothing
# to actually enforce this, outside of convention. Maybe we could develop a MyPy plugin?
ImmutableValue = Any


# NB: We don't generate `__eq__` because dataclass would only look at the `alias` classvar, which
# is always the same between every Field instance. Instead, subclasses like `PrimitiveField` should
# define `__eq__`.
@frozen_after_init
@dataclass(eq=False)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
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


@frozen_after_init
@dataclass(unsafe_hash=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
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

    value: ImmutableValue

    @final
    def __init__(self, raw_value: Optional[Any], *, address: Address) -> None:
        # NB: We neither store the `address` or `raw_value` as attributes on this dataclass:
        # * Don't store `raw_value` because it very often is mutable and/or unhashable, which means
        #   this Field could not be passed around in the engine.
        # * Don't store `address` to avoid the cost in memory of storing `Address` on every single
        #   field encountered by Pants in a run.
        self.value = self.hydrate(raw_value, address=address)

    @abstractmethod
    def hydrate(self, raw_value: Optional[Any], *, address: Address) -> ImmutableValue:
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


# Type alias to express the intent that the type should be a new Request class created to
# correspond with its AsyncField.
AsyncFieldRequest = Any


@frozen_after_init
@dataclass(unsafe_hash=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class AsyncField(Field, metaclass=ABCMeta):
    """A field that needs the engine in order to be hydrated.

    You must implement `sanitize_raw_value()` to convert the `raw_value` into a type that is
    immutable and hashable so that this Field may be used by the V2 engine. This means, for example,
    using tuples rather than lists and using `FrozenOrderedSet` rather than `set`.

    You should also create corresponding HydratedField and HydrateFieldRequest classes and define a
    rule to go from this HydrateFieldRequest to HydratedField. The HydrateFieldRequest type must
    be registered as a RootRule. Then, implement the property `AsyncField.request` to instantiate
    the HydrateFieldRequest type. If you use MyPy, you should mark `AsyncField.request` as
    `@final` (from `typing_extensions)` to ensure that subclasses don't change this property.

    For example:

        class Sources(AsyncField):
            alias: ClassVar = "sources"
            sanitized_raw_value: Optional[Tuple[str, ...]]

            def sanitize_raw_value(
                raw_value: Optional[List[str]], *, address: Address
            ) -> Optional[Tuple[str, ...]]:
                ...

            @final
            @property
            def request(self) -> HydrateSourcesRequest:
                return HydrateSourcesRequest(self)

            # Example extension point provided by this field. Subclasses can override this to do
            # whatever validation they'd like. Each AsyncField must define its own entry points
            # like this to allow subclasses to change behavior.
            def validate_snapshot(self, snapshot: Snapshot) -> None:
                pass


        @dataclass(frozen=True)
        class HydrateSourcesRequest:
            field: Sources


        @dataclass(frozen=True)
        class HydratedSources:
            snapshot: Snapshot


        @rule
        def hydrate_sources(request: HydrateSourcesRequest) -> HydratedSources:
            result = await Get[Snapshot](PathGlobs(request.field.sanitized_raw_value))
            request.field.validate_snapshot(result)
            ...
            return HydratedSources(result)


        def rules():
            return [hydrate_sources, RootRule(HydrateSourcesRequest)]

    Then, call sites can `await Get` if they need to hydrate the field, even if they subclassed
    the original `AsyncField` to have custom behavior:

        sources1 = await Get[HydratedSources](HydrateSourcesRequest, my_tgt.get(Sources).request)
        sources2 = await Get[HydratedSources[(
            HydrateSourcesRequest, custom_tgt.get(CustomSources).request
        )
    """

    address: Address
    sanitized_raw_value: ImmutableValue

    @final
    def __init__(self, raw_value: Optional[Any], *, address: Address) -> None:
        self.address = address
        self.sanitized_raw_value = self.sanitize_raw_value(raw_value)

    @abstractmethod
    def sanitize_raw_value(self, raw_value: Optional[Any]) -> ImmutableValue:
        """Sanitize the `raw_value` into a type that is safe for the V2 engine to use.

        The resulting type should be immutable and hashable.

        You may also do light-weight validation in this method, such as ensuring that all
        elements of a list are strings.
        """

    def __repr__(self) -> str:
        return f"{self.__class__}(alias={repr(self.alias)}, sanitized_raw_value={self.sanitized_raw_value})"

    def __str__(self) -> str:
        return f"{self.alias}={self.sanitized_raw_value}"

    @property
    @abstractmethod
    def request(self) -> AsyncFieldRequest:
        """Wrap the field in its corresponding Request type.

        This is necessary to avoid ambiguity in the V2 rule graph when dealing with possible
        subclasses of this AsyncField.

        For example:

            @final
            @property
            def request() -> HydrateSourcesRequest:
                return HydrateSourcesRequest(self)
        """


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
        # NB: `union_membership` is only optional to facilitate tests. In production, we should
        # always provide this parameter. This should be safe to do because production code should
        # rarely directly instantiate Targets and should instead use the engine to request them.
        union_membership: Optional[UnionMembership] = None,
    ) -> None:
        self.address = address
        self.plugin_fields = self._find_plugin_fields(union_membership or UnionMembership({}))

        self.field_values = {}
        aliases_to_field_types = {field_type.alias: field_type for field_type in self.field_types}
        for alias, value in unhydrated_values.items():
            if alias not in aliases_to_field_types:
                raise TargetDefinitionException(
                    address,
                    f"Unrecognized field `{alias}={value}`. Valid fields for the target type "
                    f"`{self.alias}`: {sorted(aliases_to_field_types.keys())}.",
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
    @classmethod
    def _find_plugin_fields(cls, union_membership: UnionMembership) -> Tuple[Type[Field], ...]:
        return cast(
            Tuple[Type[Field], ...], tuple(union_membership.union_rules.get(cls.PluginField, ()))
        )

    @final
    @classmethod
    def _find_registered_field_subclass(
        cls, requested_field: Type[_F], *, registered_fields: Iterable[Type[Field]]
    ) -> Optional[Type[_F]]:
        """Check if the Target has registered a subclass of the requested Field.

        This is necessary to allow targets to override the functionality of common fields like
        `Sources`. For example, Python targets may want to have `PythonSources` to add extra
        validation that every source file ends in `*.py`. At the same time, we still want to be able
        to call `my_python_tgt.get(Sources)`, in addition to `my_python_tgt.get(PythonSources)`.
        """
        subclass = next(
            (
                registered_field
                for registered_field in registered_fields
                if issubclass(registered_field, requested_field)
            ),
            None,
        )
        return cast(Optional[Type[_F]], subclass)

    @final
    def get(self, field: Type[_F]) -> _F:
        """Get the requested `Field` instance belonging to this target.

        This will return an instance of the requested field type, e.g. an instance of
        `Compatibility`, `Sources`, `EntryPoint`, etc. Usually, you will want to grab the
        `Field`'s inner value, e.g. `tgt.get(Compatibility).value`. (For `AsyncField`s, you would
        call `await Get[SourcesResult](SourcesRequest, tgt.get(Sources).request)`).

        If the `Field` is not registered on this `Target` type, this method will raise a
        `KeyError`. To avoid this, you should first call `tgt.has_field()` or `tgt.has_fields()`
        to ensure that the field is registered.

        This works with subclasses of `Field`s. For example, if you subclass `Sources` to define a
        custom subclass `PythonSources`, both `python_tgt.get(PythonSources)` and
        `python_tgt.get(Sources)` will return the same `PythonSources` instance.
        """
        result = self.field_values.get(field, None)
        if result is not None:
            return cast(_F, result)
        field_subclass = self._find_registered_field_subclass(
            field, registered_fields=self.field_types
        )
        if field_subclass is not None:
            return cast(_F, self.field_values[field_subclass])
        raise KeyError(
            f"The target `{self}` does not have a field `{field}`. Before calling "
            f"`my_tgt.get({field.__name__})`, call `my_tgt.has_field({field.__name__})` to "
            "filter out any irrelevant Targets."
        )

    @final
    @classmethod
    def _has_fields(
        cls, fields: Iterable[Type[Field]], *, registered_fields: Iterable[Type[Field]]
    ) -> bool:
        unrecognized_fields = [field for field in fields if field not in registered_fields]
        if not unrecognized_fields:
            return True
        for unrecognized_field in unrecognized_fields:
            maybe_subclass = cls._find_registered_field_subclass(
                unrecognized_field, registered_fields=registered_fields
            )
            if maybe_subclass is None:
                return False
        return True

    @final
    def has_field(self, field: Type[Field]) -> bool:
        """Check that this target has registered the requested field.

        This works with subclasses of `Field`s. For example, if you subclass `Sources` to define a
        custom subclass `PythonSources`, both `python_tgt.has_field(PythonSources)` and
        `python_tgt.has_field(Sources)` will return True.
        """
        return self.has_fields([field])

    @final
    def has_fields(self, fields: Iterable[Type[Field]]) -> bool:
        """Check that this target has registered all of the requested fields.

        This works with subclasses of `Field`s. For example, if you subclass `Sources` to define a
        custom subclass `PythonSources`, both `python_tgt.has_fields([PythonSources])` and
        `python_tgt.has_fields([Sources])` will return True.
        """
        return self._has_fields(fields, registered_fields=self.field_types)

    @final
    @classmethod
    def class_has_field(cls, field: Type[Field], *, union_membership: UnionMembership) -> bool:
        """Behaves like `Target.has_field()`, but works as a classmethod rather than an instance
        method."""
        return cls.class_has_fields([field], union_membership=union_membership)

    @final
    @classmethod
    def class_has_fields(
        cls, fields: Iterable[Type[Field]], *, union_membership: UnionMembership
    ) -> bool:
        """Behaves like `Target.has_fields()`, but works as a classmethod rather than an instance
        method."""
        return cls._has_fields(
            fields, registered_fields=(*cls.core_fields, *cls._find_plugin_fields(union_membership))
        )


@dataclass(frozen=True)
class WrappedTarget:
    """A light wrapper to encapsulate all the distinct `Target` subclasses into a single type.

    This is necessary when using a single target in a rule because the engine expects exact types
    and does not work with subtypes.
    """

    target: Target


@dataclass(frozen=True)
class RegisteredTargetTypes:
    # TODO: add `FrozenDict` as a light-weight wrapper around `dict` that de-registers the
    #  mutation entry points.
    aliases_to_types: Dict[str, Type[Target]]

    @classmethod
    def create(cls, target_types: Iterable[Type[Target]]) -> "RegisteredTargetTypes":
        return cls(
            {
                target_type.alias: target_type
                for target_type in sorted(target_types, key=lambda target_type: target_type.alias)
            }
        )

    @property
    def aliases(self) -> Tuple[str, ...]:
        return tuple(self.aliases_to_types.keys())

    @property
    def types(self) -> Tuple[Type[Target], ...]:
        return tuple(self.aliases_to_types.values())


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

    def request(self) -> Any:
        raise NotImplementedError("Hydration of the Dependencies field is not yet implemented.")


COMMON_TARGET_FIELDS = (Dependencies, Tags)


class Sources(AsyncField):
    alias: ClassVar = "sources"
    default_globs: ClassVar[Optional[Tuple[str, ...]]] = None
    sanitized_raw_value: Optional[Tuple[str, ...]]

    def sanitize_raw_value(self, raw_value: Optional[Iterable[str]]) -> Optional[Tuple[str, ...]]:
        if raw_value is None:
            return None
        return tuple(raw_value)

    def validate_snapshot(self, _: Snapshot) -> None:
        """Perform any validation on the resulting snapshot, e.g. ensuring that all files end in
        `.py`."""

    @final
    @property
    def request(self) -> "HydrateSourcesRequest":
        return HydrateSourcesRequest(self)

    @final
    def prefix_glob_with_address(self, glob: str) -> str:
        if glob.startswith("!"):
            return f"!{PurePath(self.address.spec_path, glob[1:])}"
        return str(PurePath(self.address.spec_path, glob))


@dataclass(frozen=True)
class HydrateSourcesRequest:
    field: Sources


@dataclass(frozen=True)
class HydratedSources:
    snapshot: Snapshot


@rule
async def hydrate_sources(
    request: HydrateSourcesRequest, glob_match_error_behavior: GlobMatchErrorBehavior
) -> HydratedSources:
    sources_field = request.field
    globs: Iterable[str]
    if sources_field.sanitized_raw_value is not None:
        globs = ensure_str_list(sources_field.sanitized_raw_value)
        conjunction = GlobExpansionConjunction.all_match
    else:
        if sources_field.default_globs is None:
            return HydratedSources(EMPTY_SNAPSHOT)
        globs = sources_field.default_globs
        conjunction = GlobExpansionConjunction.any_match

    snapshot = await Get[Snapshot](
        PathGlobs(
            (sources_field.prefix_glob_with_address(glob) for glob in globs),
            conjunction=conjunction,
            glob_match_error_behavior=glob_match_error_behavior,
            # TODO(#9012): add line number referring to the sources field. When doing this, we'll
            # likely need to `await Get[BuildFileAddress](Address)`.
            description_of_origin=(
                f"{sources_field.address}'s `{sources_field.alias}` field"
                if glob_match_error_behavior != GlobMatchErrorBehavior.ignore
                else None
            ),
        )
    )
    sources_field.validate_snapshot(snapshot)
    return HydratedSources(snapshot)


def rules():
    return [hydrate_sources, RootRule(HydrateSourcesRequest)]
