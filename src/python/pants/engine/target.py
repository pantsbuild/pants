# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
import dataclasses
import itertools
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import (
    Any,
    ClassVar,
    Dict,
    Generic,
    Iterable,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from typing_extensions import final

from pants.base.specs import OriginSpec
from pants.build_graph.bundle import Bundle
from pants.engine.addresses import Address, Addresses, assert_single_address
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    PathGlobs,
    Snapshot,
)
from pants.engine.legacy.structs import BundleAdaptor
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.unions import UnionMembership, union
from pants.option.global_options import GlobalOptions
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper, Filespec
from pants.util.collections import ensure_list, ensure_str_list
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

# -----------------------------------------------------------------------------------------------
# Core Field abstractions
# -----------------------------------------------------------------------------------------------

# Type alias to express the intent that the type should be immutable and hashable. There's nothing
# to actually enforce this, outside of convention. Maybe we could develop a MyPy plugin?
ImmutableValue = Any


class Field(ABC):
    # Subclasses must define these.
    alias: ClassVar[str]
    default: ClassVar[ImmutableValue]
    # Subclasses may define these.
    required: ClassVar[bool] = False
    v1_only: ClassVar[bool] = False

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
@dataclass(unsafe_hash=True)
class PrimitiveField(Field, metaclass=ABCMeta):
    """A Field that does not need the engine in order to be hydrated.

    The majority of fields should use subclasses of `PrimitiveField`, e.g. use `BoolField`,
    `StringField`, or `StringSequenceField`. These subclasses will provide sane type hints and
    hydration/validation automatically.

    If you are directly subclassing `PrimitiveField`, you should likely override `compute_value()`
    to perform any custom hydration and/or validation, such as converting unhashable types to
    hashable types or checking for banned values. The returned value must be hashable
    (and should be immutable) so that this Field may be used by the V2 engine. This means, for
    example, using tuples rather than lists and using `FrozenOrderedSet` rather than `set`.

    All hydration and/or validation happens eagerly in the constructor. If the
    hydration is particularly expensive, use `AsyncField` instead to get the benefits of the
    engine's caching.

    Subclasses should also override the type hints for `value` and `raw_value` to be more precise
    than `Any`. The type hint for `raw_value` is used to generate documentation, e.g. for
    `./pants target-types`. If the field is required, do not use `Optional` for the type hint of
    `raw_value`.

    Example:

        # NB: Really, this should subclass IntField. We only use PrimitiveField as an example.
        class Timeout(PrimitiveField):
            alias = "timeout"
            value: Optional[int]
            default = None

            @classmethod
            def compute_value(cls, raw_value: Optional[int], *, address: Address) -> Optional[int:
                value_or_default = super().compute_value(raw_value, address=address)
                if value_or_default is not None and not isinstance(value_or_default, int):
                    raise ValueError(
                        "The `timeout` field expects an integer, but was given"
                        f"{value_or_default} for target {address}."
                    )
                return value_or_default
    """

    value: ImmutableValue

    @final
    def __init__(self, raw_value: Optional[Any], *, address: Address) -> None:
        # NB: We neither store the `address` or `raw_value` as attributes on this dataclass:
        # * Don't store `raw_value` because it very often is mutable and/or unhashable, which means
        #   this Field could not be passed around in the engine.
        # * Don't store `address` to avoid the cost in memory of storing `Address` on every single
        #   field encountered by Pants in a run.
        self.value = self.compute_value(raw_value, address=address)

    @classmethod
    def compute_value(cls, raw_value: Optional[Any], *, address: Address) -> ImmutableValue:
        """Convert the `raw_value` into `self.value`.

        You should perform any optional validation and/or hydration here. For example, you may want
        to check that an integer is > 0 or convert an Iterable[str] to List[str].

        The resulting value must be hashable (and should be immutable).
        """
        if raw_value is None:
            if cls.required:
                raise RequiredFieldMissingException(address, cls.alias)
            return cls.default
        return raw_value

    def __repr__(self) -> str:
        return (
            f"{self.__class__}(alias={repr(self.alias)}, value={repr(self.value)}, "
            f"default={repr(self.default)})"
        )

    def __str__(self) -> str:
        return f"{self.alias}={self.value}"


@frozen_after_init
@dataclass(unsafe_hash=True)
class AsyncField(Field, metaclass=ABCMeta):
    """A field that needs the engine in order to be hydrated.

    You should implement `sanitize_raw_value()` to convert the `raw_value` into a type that is
    immutable and hashable so that this Field may be used by the V2 engine. This means, for example,
    using tuples rather than lists and using `FrozenOrderedSet` rather than `set`.

    You should also create corresponding HydratedField and HydrateFieldRequest classes and define a
    rule to go from this HydrateFieldRequest to HydratedField. The HydrateFieldRequest type should
    have an attribute storing the underlying AsyncField; it also must be registered as a RootRule.

    For example:

        class Sources(AsyncField):
            alias: ClassVar = "sources"
            sanitized_raw_value: Optional[Tuple[str, ...]]

            def sanitize_raw_value(
                raw_value: Optional[List[str]], *, address: Address
            ) -> Optional[Tuple[str, ...]]:
                ...

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

        sources1 = await Get[HydratedSources](HydrateSourcesRequest(my_tgt.get(Sources)))
        sources2 = await Get[HydratedSources[(HydrateSourcesRequest(custom_tgt.get(CustomSources)))
    """

    address: Address
    sanitized_raw_value: ImmutableValue

    @final
    def __init__(self, raw_value: Optional[Any], *, address: Address) -> None:
        self.address = address
        self.sanitized_raw_value = self.sanitize_raw_value(raw_value, address=address)

    @classmethod
    def sanitize_raw_value(cls, raw_value: Optional[Any], *, address: Address) -> ImmutableValue:
        """Sanitize the `raw_value` into a type that is safe for the V2 engine to use.

        The resulting type should be immutable and hashable.

        You may also do light-weight validation in this method, such as ensuring that all
        elements of a list are strings.
        """
        if raw_value is None:
            if cls.required:
                raise RequiredFieldMissingException(address, cls.alias)
            return cls.default
        return raw_value

    def __repr__(self) -> str:
        return (
            f"{self.__class__}(alias={repr(self.alias)}, "
            f"sanitized_raw_value={repr(self.sanitized_raw_value)}, default={repr(self.default)})"
        )

    def __str__(self) -> str:
        return f"{self.alias}={self.sanitized_raw_value}"


# -----------------------------------------------------------------------------------------------
# Core Target abstractions
# -----------------------------------------------------------------------------------------------

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
    # Subclasses may define these
    v1_only: ClassVar[bool] = False

    # These get calculated in the constructor
    address: Address
    plugin_fields: Tuple[Type[Field], ...]
    field_values: FrozenDict[Type[Field], Field]

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

        field_values = {}
        aliases_to_field_types = {field_type.alias: field_type for field_type in self.field_types}
        for alias, value in unhydrated_values.items():
            if alias not in aliases_to_field_types:
                raise InvalidFieldException(
                    f"Unrecognized field `{alias}={value}` in target {address}. Valid fields for "
                    f"the target type `{self.alias}`: {sorted(aliases_to_field_types.keys())}.",
                )
            field_type = aliases_to_field_types[alias]
            field_values[field_type] = field_type(value, address=address)
        # For undefined fields, mark the raw value as None.
        for field_type in set(self.field_types) - set(field_values.keys()):
            field_values[field_type] = field_type(raw_value=None, address=address)
        self.field_values = FrozenDict(field_values)

    @final
    @property
    def field_types(self) -> Tuple[Type[Field], ...]:
        return (*self.core_fields, *self.plugin_fields)

    @union
    @final
    class PluginField:
        """A sentinel class to allow plugin authors to add additional fields to this target type.

        Plugin authors may add additional fields by simply registering UnionRules between the
        `Target.PluginField` and the custom field, e.g. `UnionRule(PythonLibrary.PluginField,
        TypeChecked)`. The `Target` will then treat `TypeChecked` as a first-class citizen and
        plugins can use that Field like any other Field.
        """

    def __repr__(self) -> str:
        fields = ", ".join(str(field) for field in self.field_values.values())
        return (
            f"{self.__class__}("
            f"address={self.address}, "
            f"alias={repr(self.alias)}, "
            f"{fields})"
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
    def _maybe_get(self, field: Type[_F]) -> Optional[_F]:
        result = self.field_values.get(field, None)
        if result is not None:
            return cast(_F, result)
        field_subclass = self._find_registered_field_subclass(
            field, registered_fields=self.field_types
        )
        if field_subclass is not None:
            return cast(_F, self.field_values[field_subclass])
        return None

    @final
    def __getitem__(self, field: Type[_F]) -> _F:
        """Get the requested `Field` instance belonging to this target.

        If the `Field` is not registered on this `Target` type, this method will raise a
        `KeyError`. To avoid this, you should first call `tgt.has_field()` or `tgt.has_fields()`
        to ensure that the field is registered, or, alternatively, use `Target.get()`.

        See the docstring for `Target.get()` for how this method handles subclasses of the
        requested Field and for tips on how to use the returned value.
        """
        result = self._maybe_get(field)
        if result is not None:
            return result
        raise KeyError(
            f"The target `{self}` does not have a field `{field.__name__}`. Before calling "
            f"`my_tgt[{field.__name__}]`, call `my_tgt.has_field({field.__name__})` to "
            f"filter out any irrelevant Targets or call `my_tgt.get({field.__name__})` to use the "
            f"default Field value."
        )

    @final
    def get(self, field: Type[_F], *, default_raw_value: Optional[Any] = None) -> _F:
        """Get the requested `Field` instance belonging to this target.

        This will return an instance of the requested field type, e.g. an instance of
        `Compatibility`, `Sources`, `EntryPoint`, etc. Usually, you will want to grab the
        `Field`'s inner value, e.g. `tgt.get(Compatibility).value`. (For `AsyncField`s, you would
        call `await Get[SourcesResult](SourcesRequest, tgt.get(Sources).request)`).

        This works with subclasses of `Field`s. For example, if you subclass `Sources` to define a
        custom subclass `PythonSources`, both `python_tgt.get(PythonSources)` and
        `python_tgt.get(Sources)` will return the same `PythonSources` instance.

        If the `Field` is not registered on this `Target` type, this will return an instance of
        the requested Field by using `default_raw_value` to create the instance. Alternatively,
        first call `tgt.has_field()` or `tgt.has_fields()` to ensure that the field is registered,
        or, alternatively, use indexing (e.g. `tgt[Compatibility]`) to raise a KeyError when the
        field is not registered.
        """
        result = self._maybe_get(field)
        if result is not None:
            return result
        return field(raw_value=default_raw_value, address=self.address)

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
    def class_field_types(cls, union_membership: UnionMembership) -> Tuple[Type[Field], ...]:
        """Return all registered Fields belonging to this target type.

        You can also use the instance property `tgt.field_types` to avoid having to pass the
        parameter UnionMembership.
        """
        return (*cls.core_fields, *cls._find_plugin_fields(union_membership))

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
            fields, registered_fields=cls.class_field_types(union_membership=union_membership)
        )


@dataclass(frozen=True)
class WrappedTarget:
    """A light wrapper to encapsulate all the distinct `Target` subclasses into a single type.

    This is necessary when using a single target in a rule because the engine expects exact types
    and does not work with subtypes.
    """

    target: Target


@dataclass(frozen=True)
class TargetWithOrigin:
    target: Target
    origin: OriginSpec


class Targets(Collection[Target]):
    """A heterogeneous collection of instances of Target subclasses.

    While every element will be a subclass of `Target`, there may be many different `Target` types
    in this collection, e.g. some `Files` targets and some `PythonLibrary` targets.

    Often, you will want to filter out the relevant targets by looking at what fields they have
    registered, e.g.:

        valid_tgts = [tgt for tgt in tgts if tgt.has_fields([Compatibility, PythonSources])]

    You should not check the Target's actual type because this breaks custom target types;
    for example, prefer `tgt.has_field(PythonTestsSources)` to `isinstance(tgt, PythonTests)`.
    """

    def expect_single(self) -> Target:
        assert_single_address([tgt.address for tgt in self])
        return self[0]


class TargetsWithOrigins(Collection[TargetWithOrigin]):
    """A heterogeneous collection of instances of Target subclasses with the original Spec used to
    resolve the target.

    See the docstring for `Targets` for an explanation of the `Target`s being heterogeneous and how
    you should filter out the targets you care about.
    """

    def expect_single(self) -> TargetWithOrigin:
        assert_single_address([tgt_with_origin.target.address for tgt_with_origin in self])
        return self[0]

    @memoized_property
    def targets(self) -> Tuple[Target, ...]:
        return tuple(tgt_with_origin.target for tgt_with_origin in self)


@dataclass(frozen=True)
class TransitiveTarget:
    """A recursive structure wrapping a Target root and TransitiveTarget deps."""

    root: Target
    dependencies: Tuple["TransitiveTarget", ...]


@dataclass(frozen=True)
class TransitiveTargets:
    """A set of Target roots, and their transitive, flattened, de-duped closure."""

    roots: Tuple[Target, ...]
    closure: FrozenOrderedSet[Target]


@frozen_after_init
@dataclass(unsafe_hash=True)
class RegisteredTargetTypes:
    aliases_to_types: FrozenDict[str, Type[Target]]

    def __init__(self, aliases_to_types: Mapping[str, Type[Target]]) -> None:
        self.aliases_to_types = FrozenDict(aliases_to_types)

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


# -----------------------------------------------------------------------------------------------
# FieldSet
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _AbstractFieldSet(ABC):
    required_fields: ClassVar[Tuple[Type[Field], ...]]

    address: Address

    @final
    @classmethod
    def is_valid(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields)

    @final
    @classmethod
    def valid_target_types(
        cls, target_types: Iterable[Type[Target]], *, union_membership: UnionMembership
    ) -> Tuple[Type[Target], ...]:
        return tuple(
            target_type
            for target_type in target_types
            if target_type.class_has_fields(cls.required_fields, union_membership=union_membership)
        )


def _get_field_set_fields_from_target(
    field_set: Type[_AbstractFieldSet], target: Target
) -> Dict[str, Field]:
    all_expected_fields: Dict[str, Type[Field]] = {
        dataclass_field.name: dataclass_field.type
        for dataclass_field in dataclasses.fields(field_set)
        if isinstance(dataclass_field.type, type) and issubclass(dataclass_field.type, Field)  # type: ignore[unreachable]
    }
    return {
        dataclass_field_name: (
            target[field_cls] if field_cls in field_set.required_fields else target.get(field_cls)
        )
        for dataclass_field_name, field_cls in all_expected_fields.items()
    }


_FS = TypeVar("_FS", bound="FieldSet")


class FieldSet(_AbstractFieldSet, metaclass=ABCMeta):
    """An ad hoc set of fields from a target which are used by rules.

    Subclasses should declare all the fields they consume as dataclass attributes. They should also
    indicate which of these are required, rather than optional, through the class property
    `required_fields`. When a field is optional, the default constructor for the field will be used
    for any targets that do not have that field registered.

    Subclasses must set `@dataclass(frozen=True)` for their declared fields to be recognized.

    For example:

        @dataclass(frozen=True)
        class FortranTestFieldSet(FieldSet):
            required_fields = (FortranSources,)

            sources: FortranSources
            fortran_version: FortranVersion

    This field set may then created from a `Target` through the `is_valid()` and `create()`
    class methods:

        field_sets = [
            FortranTestFieldSet.create(tgt) for tgt in targets
            if FortranTestFieldSet.is_valid(tgt)
        ]

    FieldSets are consumed like any normal dataclass:

        print(field_set.address)
        print(field_set.sources)
    """

    @classmethod
    def create(cls: Type[_FS], tgt: Target) -> _FS:
        return cls(  # type: ignore[call-arg]
            address=tgt.address, **_get_field_set_fields_from_target(cls, tgt)
        )


_FSWO = TypeVar("_FSWO", bound="FieldSetWithOrigin")


@dataclass(frozen=True)
class FieldSetWithOrigin(_AbstractFieldSet, metaclass=ABCMeta):
    """An ad hoc set of fields from a target which are used by rules, along with the original spec
    used to find the original target.

    See FieldSet for documentation on how subclasses should use this base class.
    """

    origin: OriginSpec

    @classmethod
    def create(cls: Type[_FSWO], target_with_origin: TargetWithOrigin) -> _FSWO:
        tgt = target_with_origin.target
        return cls(  # type: ignore[call-arg]
            address=tgt.address,
            origin=target_with_origin.origin,
            **_get_field_set_fields_from_target(cls, tgt),
        )


_AFS = TypeVar("_AFS", bound=_AbstractFieldSet)


@frozen_after_init
@dataclass(unsafe_hash=True)
class TargetsToValidFieldSets(Generic[_AFS]):
    mapping: FrozenDict[TargetWithOrigin, Tuple[_AFS, ...]]

    def __init__(self, mapping: Mapping[TargetWithOrigin, Iterable[_AFS]]) -> None:
        self.mapping = FrozenDict(
            {tgt_with_origin: tuple(field_sets) for tgt_with_origin, field_sets in mapping.items()}
        )

    @memoized_property
    def field_sets(self) -> Tuple[_AFS, ...]:
        return tuple(
            itertools.chain.from_iterable(
                field_sets_per_target for field_sets_per_target in self.mapping.values()
            )
        )

    @memoized_property
    def targets(self) -> Tuple[Target, ...]:
        return tuple(tgt_with_origin.target for tgt_with_origin in self.targets_with_origins)

    @memoized_property
    def targets_with_origins(self) -> Tuple[TargetWithOrigin, ...]:
        return tuple(self.mapping.keys())


@frozen_after_init
@dataclass(unsafe_hash=True)
class TargetsToValidFieldSetsRequest(Generic[_AFS]):
    field_set_superclass: Type[_AFS]
    goal_description: str
    error_if_no_valid_targets: bool
    expect_single_field_set: bool
    # TODO: Add a `require_sources` field. To do this, figure out the dependency cycle with
    #  `util_rules/filter_empty_sources.py`.

    def __init__(
        self,
        field_set_superclass: Type[_AFS],
        *,
        goal_description: str,
        error_if_no_valid_targets: bool,
        expect_single_field_set: bool = False,
    ) -> None:
        self.field_set_superclass = field_set_superclass
        self.goal_description = goal_description
        self.error_if_no_valid_targets = error_if_no_valid_targets
        self.expect_single_field_set = expect_single_field_set


@rule
def find_valid_field_sets(
    request: TargetsToValidFieldSetsRequest,
    targets_with_origins: TargetsWithOrigins,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> TargetsToValidFieldSets:
    field_set_types: Iterable[
        Union[Type[FieldSet], Type[FieldSetWithOrigin]]
    ] = union_membership.union_rules[request.field_set_superclass]
    targets_to_valid_field_sets = {}
    for tgt_with_origin in targets_with_origins:
        valid_field_sets = [
            (
                field_set_type.create(tgt_with_origin)
                if issubclass(field_set_type, FieldSetWithOrigin)
                else field_set_type.create(tgt_with_origin.target)
            )
            for field_set_type in field_set_types
            if field_set_type.is_valid(tgt_with_origin.target)
        ]
        if valid_field_sets:
            targets_to_valid_field_sets[tgt_with_origin] = valid_field_sets
    if request.error_if_no_valid_targets and not targets_to_valid_field_sets:
        raise NoValidTargetsException.create_from_field_sets(
            targets_with_origins,
            field_set_types=field_set_types,
            goal_description=request.goal_description,
            union_membership=union_membership,
            registered_target_types=registered_target_types,
        )
    result = TargetsToValidFieldSets(targets_to_valid_field_sets)
    if not request.expect_single_field_set:
        return result
    if len(result.targets) > 1:
        raise TooManyTargetsException(result.targets, goal_description=request.goal_description)
    if len(result.field_sets) > 1:
        raise AmbiguousImplementationsException(
            result.targets[0], result.field_sets, goal_description=request.goal_description
        )
    return result


# -----------------------------------------------------------------------------------------------
# Exception messages
# -----------------------------------------------------------------------------------------------


class InvalidFieldException(Exception):
    """Use when there's an issue with a particular field.

    Suggested template:

         f"The {repr(alias)} field in target {address} must ..., but ..."
    """


class InvalidFieldTypeException(InvalidFieldException):
    """This is used to ensure that the field's value conforms with the expected type for the field,
    e.g. `a boolean` or `a string` or `an iterable of strings and integers`."""

    def __init__(
        self, address: Address, field_alias: str, raw_value: Optional[Any], *, expected_type: str
    ) -> None:
        super().__init__(
            f"The {repr(field_alias)} field in target {address} must be {expected_type}, but was "
            f"`{repr(raw_value)}` with type `{type(raw_value).__name__}`."
        )


class RequiredFieldMissingException(InvalidFieldException):
    def __init__(self, address: Address, field_alias: str) -> None:
        super().__init__(f"The {repr(field_alias)} field in target {address} must be defined.")


class InvalidFieldChoiceException(InvalidFieldException):
    def __init__(
        self,
        address: Address,
        field_alias: str,
        raw_value: Optional[Any],
        *,
        valid_choices: Iterable[Any],
    ) -> None:
        super().__init__(
            f"The {repr(field_alias)} field in target {address} must be one of "
            f"{sorted(valid_choices)}, but was {repr(raw_value)}."
        )


class UnrecognizedTargetTypeException(Exception):
    def __init__(
        self,
        target_type: str,
        registered_target_types: RegisteredTargetTypes,
        *,
        address: Optional[Address] = None,
    ) -> None:
        for_address = f"for address {address}" if address else ""
        super().__init__(
            f"Target type {repr(target_type)} is not registered{for_address}.\n\nAll valid target "
            f"types: {sorted(registered_target_types.aliases)}\n\n(If {repr(target_type)} is a "
            "custom target type, refer to "
            "https://groups.google.com/forum/#!topic/pants-devel/WsRFODRLVZI for instructions on "
            "writing a light-weight Target API binding.)"
        )


# NB: This has a tight coupling to goals. Feel free to change this if necessary.
class NoValidTargetsException(Exception):
    def __init__(
        self,
        targets_with_origins: TargetsWithOrigins,
        *,
        valid_target_types: Iterable[Type[Target]],
        goal_description: str,
    ) -> None:
        valid_target_aliases = sorted({target_type.alias for target_type in valid_target_types})
        invalid_target_aliases = sorted({tgt.alias for tgt in targets_with_origins.targets})
        specs = sorted(
            {
                target_with_origin.origin.to_spec_string()
                for target_with_origin in targets_with_origins
            }
        )
        bulleted_list_sep = "\n  * "
        super().__init__(
            f"{goal_description.capitalize()} only works with the following target types:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(valid_target_aliases)}\n\n"
            f"You specified `{' '.join(specs)}`, which only included the following target types:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(invalid_target_aliases)}"
        )

    @classmethod
    def create_from_field_sets(
        cls,
        targets_with_origins: TargetsWithOrigins,
        *,
        field_set_types: Iterable[Type[_AbstractFieldSet]],
        goal_description: str,
        union_membership: UnionMembership,
        registered_target_types: RegisteredTargetTypes,
    ) -> "NoValidTargetsException":
        valid_target_types = {
            target_type
            for field_set_type in field_set_types
            for target_type in field_set_type.valid_target_types(
                registered_target_types.types, union_membership=union_membership
            )
        }
        return cls(
            targets_with_origins,
            valid_target_types=valid_target_types,
            goal_description=goal_description,
        )


# NB: This has a tight coupling to goals. Feel free to change this if necessary.
class TooManyTargetsException(Exception):
    def __init__(self, targets: Iterable[Target], *, goal_description: str) -> None:
        bulleted_list_sep = "\n  * "
        addresses = sorted(tgt.address.spec for tgt in targets)
        super().__init__(
            f"{goal_description.capitalize()} only works with one valid target, but was given "
            f"multiple valid targets:{bulleted_list_sep}{bulleted_list_sep.join(addresses)}\n\n"
            "Please select one of these targets to run."
        )


# NB: This has a tight coupling to goals. Feel free to change this if necessary.
class AmbiguousImplementationsException(Exception):
    """Exception for when a single target has multiple valid FieldSets, but the goal only expects
    there to be one FieldSet."""

    def __init__(
        self, target: Target, field_sets: Iterable[_AbstractFieldSet], *, goal_description: str,
    ) -> None:
        # TODO: improve this error message. A better error message would explain to users how they
        #  can resolve the issue.
        possible_field_sets_types = sorted(field_set.__class__.__name__ for field_set in field_sets)
        bulleted_list_sep = "\n  * "
        super().__init__(
            f"Multiple of the registered implementations for {goal_description} work for "
            f"{target.address} (target type {repr(target.alias)}). It is ambiguous which "
            "implementation to use.\n\nPossible implementations:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(possible_field_sets_types)}"
        )


class AmbiguousCodegenImplementationsException(Exception):
    """Exception for when there are multiple codegen implementations and it is ambiguous which to
    use."""

    def __init__(
        self,
        generators: Iterable[Type["GenerateSourcesRequest"]],
        *,
        for_sources_types: Iterable[Type["Sources"]],
    ) -> None:
        bulleted_list_sep = "\n  * "
        all_same_generator_paths = (
            len(set((generator.input, generator.output) for generator in generators)) == 1
        )
        example_generator = list(generators)[0]
        input = example_generator.input.__name__
        if all_same_generator_paths:
            output = example_generator.output.__name__
            possible_generators = sorted(generator.__name__ for generator in generators)
            super().__init__(
                f"Multiple of the registered code generators can generate {output} from {input}. "
                "It is ambiguous which implementation to use.\n\nPossible implementations:"
                f"{bulleted_list_sep}{bulleted_list_sep.join(possible_generators)}"
            )
        else:
            possible_output_types = sorted(
                generator.output.__name__
                for generator in generators
                if issubclass(generator.output, tuple(for_sources_types))
            )
            possible_generators_with_output = [
                f"{generator.__name__} -> {generator.output.__name__}"
                for generator in sorted(generators, key=lambda generator: generator.output.__name__)
            ]
            super().__init__(
                f"Multiple of the registered code generators can generate one of "
                f"{possible_output_types} from {input}. It is ambiguous which implementation to "
                f"use. This can happen when the call site requests too many different output types "
                f"from the same original protocol sources.\n\nPossible implementations with their "
                f"output type: {bulleted_list_sep}"
                f"{bulleted_list_sep.join(possible_generators_with_output)}"
            )


class AmbiguousDependencyInferenceException(Exception):
    """Exception for when there are multiple dependency inference implementations and it is
    ambiguous which to use."""

    def __init__(
        self,
        implementations: Iterable[Type["InferDependenciesRequest"]],
        *,
        from_sources_type: Type["Sources"],
    ) -> None:
        bulleted_list_sep = "\n  * "
        possible_implementations = sorted(impl.__name__ for impl in implementations)
        super().__init__(
            f"Multiple of the registered dependency inference implementations can infer "
            f"dependencies from {from_sources_type.__name__}. It is ambiguous which "
            "implementation to use.\n\nPossible implementations:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(possible_implementations)}"
        )


# -----------------------------------------------------------------------------------------------
# Field templates
# -----------------------------------------------------------------------------------------------

T = TypeVar("T")


class ScalarField(Generic[T], PrimitiveField, metaclass=ABCMeta):
    """A field with a scalar value (vs. a compound value like a sequence or dict).

    Subclasses must define the class properties `expected_type` and `expected_type_description`.
    They should also override the type hints for the classmethod `compute_value` so that we use the
    correct type annotation in generated documentation.

        class Example(ScalarField):
            alias = "example"
            expected_type = MyPluginObject
            expected_type_description = "a `my_plugin` object"

            @classmethod
            def compute_value(
                cls, raw_value: Optional[MyPluginObject], *, address: Address
            ) -> Optional[MyPluginObject]:
                return super().compute_value(raw_value, address=address)
    """

    expected_type: ClassVar[Type[T]]
    expected_type_description: ClassVar[str]
    value: Optional[T]
    default: ClassVar[Optional[T]] = None

    @classmethod
    def compute_value(cls, raw_value: Optional[Any], *, address: Address) -> Optional[T]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is not None and not isinstance(value_or_default, cls.expected_type):
            raise InvalidFieldTypeException(
                address, cls.alias, raw_value, expected_type=cls.expected_type_description,
            )
        return value_or_default


class BoolField(PrimitiveField, metaclass=ABCMeta):
    """A field whose value is a boolean.

    If subclasses do not set the class property `required = True` or `default`, the value will
    default to None. This can be useful to represent three states: unspecified, False, and True.

        class ZipSafe(BoolField):
            alias = "zip_safe"
            default = True
    """

    value: Optional[bool]
    default: ClassVar[Optional[bool]] = None

    @classmethod
    def compute_value(cls, raw_value: Optional[bool], *, address: Address) -> Optional[bool]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is not None and not isinstance(value_or_default, bool):
            raise InvalidFieldTypeException(
                address, cls.alias, raw_value, expected_type="a boolean",
            )
        return value_or_default


class IntField(ScalarField, metaclass=ABCMeta):
    expected_type = int
    expected_type_description = "an integer"

    @classmethod
    def compute_value(cls, raw_value: Optional[int], *, address: Address) -> Optional[int]:
        return super().compute_value(raw_value, address=address)


class FloatField(ScalarField, metaclass=ABCMeta):
    expected_type = float
    expected_type_description = "a float"

    @classmethod
    def compute_value(cls, raw_value: Optional[float], *, address: Address) -> Optional[float]:
        return super().compute_value(raw_value, address=address)


class StringField(ScalarField, metaclass=ABCMeta):
    """A field whose value is a string.

    If you expect the string to only be one of several values, set the class property
    `valid_choices`.
    """

    expected_type = str
    expected_type_description = "a string"
    valid_choices: ClassVar[Optional[Union[Type[Enum], Tuple[str, ...]]]] = None

    @classmethod
    def compute_value(cls, raw_value: Optional[str], *, address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is not None and cls.valid_choices is not None:
            valid_choices = set(
                cls.valid_choices
                if isinstance(cls.valid_choices, tuple)
                else (choice.value for choice in cls.valid_choices)
            )
            if value_or_default not in valid_choices:
                raise InvalidFieldChoiceException(
                    address, cls.alias, value_or_default, valid_choices=valid_choices
                )
        return value_or_default


class SequenceField(Generic[T], PrimitiveField, metaclass=ABCMeta):
    """A field whose value is a homogeneous sequence.

    Subclasses must define the class properties `expected_element_type` and
    `expected_type_description`. They should also override the type hints for the classmethod
    `compute_value` so that we use the correct type annotation in generated documentation.

        class Example(SequenceField):
            alias = "example"
            expected_element_type = MyPluginObject
            expected_type_description = "an iterable of `my_plugin` objects"

            @classmethod
            def compute_value(
                cls, raw_value: Optional[Iterable[MyPluginObject]], *, address: Address
            ) -> Optional[Tuple[MyPluginObject, ...]]:
                return super().compute_value(raw_value, address=address)
    """

    expected_element_type: ClassVar[Type[T]]
    expected_type_description: ClassVar[str]
    value: Optional[Tuple[T, ...]]
    default: ClassVar[Optional[Tuple[T, ...]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[Any]], *, address: Address
    ) -> Optional[Tuple[T, ...]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is None:
            return None
        try:
            ensure_list(value_or_default, expected_type=cls.expected_element_type)
        except ValueError:
            raise InvalidFieldTypeException(
                address, cls.alias, raw_value, expected_type=cls.expected_type_description,
            )
        return tuple(value_or_default)


class StringSequenceField(SequenceField, metaclass=ABCMeta):
    value: Optional[Tuple[str, ...]]
    default: ClassVar[Optional[Tuple[str, ...]]] = None

    expected_element_type = str
    expected_type_description = "an iterable of strings (e.g. a list of strings)"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Optional[Tuple[str, ...]]:
        return super().compute_value(raw_value, address=address)


class StringOrStringSequenceField(SequenceField, metaclass=ABCMeta):
    """The raw_value may either be a string or be an iterable of strings.

    This is syntactic sugar that we use for certain fields to make BUILD files simpler when the user
    has no need for more than one element.

    Generally, this should not be used by any new Fields. This mechanism is a misfeature.
    """

    value: Optional[Tuple[str, ...]]
    default: ClassVar[Optional[Tuple[str, ...]]] = None

    expected_element_type = str
    expected_type_description = (
        "either a single string or an iterable of strings (e.g. a list of strings)"
    )

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Union[str, Iterable[str]]], *, address: Address
    ) -> Optional[Tuple[str, ...]]:
        if isinstance(raw_value, str):
            return (raw_value,)
        return super().compute_value(raw_value, address=address)


class DictStringToStringField(PrimitiveField, metaclass=ABCMeta):
    value: Optional[FrozenDict[str, str]]
    default: ClassVar[Optional[FrozenDict[str, str]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, str]], *, address: Address
    ) -> Optional[FrozenDict[str, str]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is None:
            return None
        invalid_type_exception = InvalidFieldTypeException(
            address, cls.alias, raw_value, expected_type="a dictionary of string -> string"
        )
        if not isinstance(value_or_default, collections.abc.Mapping):
            raise invalid_type_exception
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in value_or_default.items()):
            raise invalid_type_exception
        return FrozenDict(value_or_default)


class DictStringToStringSequenceField(PrimitiveField, metaclass=ABCMeta):
    value: Optional[FrozenDict[str, Tuple[str, ...]]]
    default: ClassVar[Optional[FrozenDict[str, Tuple[str, ...]]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, Iterable[str]]], *, address: Address
    ) -> Optional[FrozenDict[str, Tuple[str, ...]]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is None:
            return None
        invalid_type_exception = InvalidFieldTypeException(
            address,
            cls.alias,
            raw_value,
            expected_type="a dictionary of string -> an iterable of strings",
        )
        if not isinstance(value_or_default, collections.abc.Mapping):
            raise invalid_type_exception
        result = {}
        for k, v in value_or_default.items():
            if not isinstance(k, str):
                raise invalid_type_exception
            try:
                result[k] = tuple(ensure_str_list(v))
            except ValueError:
                raise invalid_type_exception
        return FrozenDict(result)


# -----------------------------------------------------------------------------------------------
# Sources and codegen
# -----------------------------------------------------------------------------------------------


class Sources(AsyncField):
    """A list of files and globs that belong to this target.

    Paths are relative to the BUILD file's directory. You can ignore files/globs by prefixing them
    with `!`. Example: `sources=['example.py', 'test_*.py', '!test_ignore.py']`.
    """

    alias = "sources"
    sanitized_raw_value: Optional[Tuple[str, ...]]
    default: ClassVar[Optional[Tuple[str, ...]]] = None
    expected_file_extensions: ClassVar[Optional[Tuple[str, ...]]] = None
    expected_num_files: ClassVar[Optional[Union[int, range]]] = None

    @classmethod
    def sanitize_raw_value(
        cls, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Optional[Tuple[str, ...]]:
        value_or_default = super().sanitize_raw_value(raw_value, address=address)
        if value_or_default is None:
            return None
        try:
            ensure_str_list(value_or_default)
        except ValueError:
            raise InvalidFieldTypeException(
                address,
                cls.alias,
                value_or_default,
                expected_type="an iterable of strings (e.g. a list of strings)",
            )
        return tuple(sorted(value_or_default))

    def validate_snapshot(self, snapshot: Snapshot) -> None:
        """Perform any additional validation on the resulting snapshot, e.g. ensuring that certain
        banned files are not used.

        To enforce that the resulting files end in certain extensions, such as `.py` or `.java`, set
        the class property `expected_file_extensions`.

        To enforce that there are only a certain number of resulting files, such as binary targets
        checking for only 0-1 sources, set the class property `expected_num_files`.
        """
        if self.expected_file_extensions is not None:
            bad_files = [
                fp
                for fp in snapshot.files
                if not PurePath(fp).suffix in self.expected_file_extensions
            ]
            if bad_files:
                expected = (
                    f"one of {sorted(self.expected_file_extensions)}"
                    if len(self.expected_file_extensions) > 1
                    else repr(self.expected_file_extensions[0])
                )
                raise InvalidFieldException(
                    f"The {repr(self.alias)} field in target {self.address} must only contain "
                    f"files that end in {expected}, but it had these files: {sorted(bad_files)}."
                    f"\n\nMaybe create a `resources()` or `files()` target and include it in the "
                    f"`dependencies` field?"
                )
        if self.expected_num_files is not None:
            num_files = len(snapshot.files)
            is_bad_num_files = (
                num_files not in self.expected_num_files
                if isinstance(self.expected_num_files, range)
                else num_files != self.expected_num_files
            )
            if is_bad_num_files:
                if isinstance(self.expected_num_files, range):
                    if len(self.expected_num_files) == 2:
                        expected_str = (
                            " or ".join(str(n) for n in self.expected_num_files) + " files"
                        )
                    else:
                        expected_str = f"a number of files in the range `{self.expected_num_files}`"
                else:
                    expected_str = pluralize(self.expected_num_files, "file")
                raise InvalidFieldException(
                    f"The {repr(self.alias)} field in target {self.address} must have "
                    f"{expected_str}, but it had {pluralize(num_files, 'file')}."
                )

    @final
    def prefix_glob_with_address(self, glob: str) -> str:
        if glob.startswith("!"):
            return f"!{PurePath(self.address.spec_path, glob[1:])}"
        return str(PurePath(self.address.spec_path, glob))

    @final
    @property
    def filespec(self) -> Filespec:
        """The original globs, returned in the Filespec dict format.

        The globs will be relativized to the build root.
        """
        includes = []
        excludes = []
        for glob in self.sanitized_raw_value or ():
            if glob.startswith("!"):
                excludes.append(glob[1:])
            else:
                includes.append(glob)
        return FilesetRelPathWrapper.to_filespec(
            args=includes, exclude=[excludes], root=self.address.spec_path
        )

    @final
    @classmethod
    def can_generate(cls, output_type: Type["Sources"], union_membership: UnionMembership) -> bool:
        """Can this Sources field be used to generate the output_type?

        Generally, this method does not need to be used. Most call sites can simply use the below,
        and the engine will generate the sources if possible or will return an instance of
        HydratedSources with an empty snapshot if not possible:

            await Get[HydratedSources](
                HydrateSourcesRequest(
                    sources_field,
                    for_sources_types=[FortranSources],
                    enable_codegen=True,
                )
            )

        This method is useful when you need to filter targets before hydrating them, such as how
        you may filter targets via `tgt.has_field(MyField)`.
        """
        generate_request_types = union_membership.get(GenerateSourcesRequest)
        return any(
            issubclass(cls, generate_request_type.input)
            and issubclass(generate_request_type.output, output_type)
            for generate_request_type in generate_request_types
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class HydrateSourcesRequest:
    field: Sources
    for_sources_types: Tuple[Type[Sources], ...]
    enable_codegen: bool

    def __init__(
        self,
        field: Sources,
        *,
        for_sources_types: Iterable[Type[Sources]] = (Sources,),
        enable_codegen: bool = False,
    ) -> None:
        """Convert raw sources globs into an instance of HydratedSources.

        If you only want to handle certain Sources fields, such as only PythonSources, set
        `for_sources_types`. Any invalid sources will return a `HydratedSources` instance with an
        empty snapshot and `sources_type = None`.

        If `enable_codegen` is set to `True`, any codegen sources will try to be converted to one
        of the `for_sources_types`.
        """
        self.field = field
        self.for_sources_types = tuple(for_sources_types)
        self.enable_codegen = enable_codegen
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.enable_codegen and self.for_sources_types == (Sources,):
            raise ValueError(
                "When setting `enable_codegen=True` on `HydrateSourcesRequest`, you must also "
                "explicitly set `for_source_types`. Why? `for_source_types` is used to "
                "determine which language(s) to try to generate. For example, "
                "`for_source_types=(PythonSources,)` will hydrate `PythonSources` like normal, "
                "and, if it encounters codegen sources that can be converted into Python, it will "
                "generate Python files."
            )


@dataclass(frozen=True)
class HydratedSources:
    """The result of hydrating a SourcesField.

    The `sources_type` will indicate which of the `HydrateSourcesRequest.for_sources_type` the
    result corresponds to, e.g. if the result comes from `FilesSources` vs. `PythonSources`. If this
    value is None, then the input `Sources` field was not one of the expected types; or, when
    codegen was enabled in the request, there was no valid code generator to generate the requested
    language from the original input. This property allows for switching on the result, e.g.
    handling hydrated files() sources differently than hydrated Python sources.
    """

    snapshot: Snapshot
    filespec: Filespec
    sources_type: Optional[Type[Sources]]

    def eager_fileset_with_spec(self, *, address: Address) -> EagerFilesetWithSpec:
        return EagerFilesetWithSpec(address.spec_path, self.filespec, self.snapshot)


@union
@dataclass(frozen=True)
class GenerateSourcesRequest:
    """A request to go from protocol sources -> a particular language.

    This should be subclassed for each distinct codegen implementation. The subclasses must define
    the class properties `input` and `output`. The subclass must also be registered via
    `UnionRule(GenerateSourcesRequest, GenerateFortranFromAvroRequest)`, for example.

    The rule to actually implement the codegen should take the subclass as input, and it must
    return `GeneratedSources`.

    For example:

        class GenerateFortranFromAvroRequest:
            input = AvroSources
            output = FortranSources

        @rule
        def generate_fortran_from_avro(request: GenerateFortranFromAvroRequest) -> GeneratedSources:
            ...

        def rules():
            return [
                generate_fortran_from_avro,
                UnionRule(GenerateSourcesRequest, GenerateFortranFromAvroRequest),
            ]
    """

    protocol_sources: Snapshot
    protocol_target: Target

    input: ClassVar[Type[Sources]]
    output: ClassVar[Type[Sources]]


@dataclass(frozen=True)
class GeneratedSources:
    snapshot: Snapshot


@rule
async def hydrate_sources(
    request: HydrateSourcesRequest,
    glob_match_error_behavior: GlobMatchErrorBehavior,
    union_membership: UnionMembership,
) -> HydratedSources:
    sources_field = request.field

    # First, find if there are any code generators for the input `sources_field`. This will be used
    # to determine if the sources_field is valid or not.
    # We could alternatively use `sources_field.can_generate()`, but we want to error if there are
    # 2+ generators due to ambiguity.
    generate_request_types = union_membership.get(GenerateSourcesRequest)
    relevant_generate_request_types = [
        generate_request_type
        for generate_request_type in generate_request_types
        if isinstance(sources_field, generate_request_type.input)
        and issubclass(generate_request_type.output, request.for_sources_types)
    ]
    if request.enable_codegen and len(relevant_generate_request_types) > 1:
        raise AmbiguousCodegenImplementationsException(
            relevant_generate_request_types, for_sources_types=request.for_sources_types
        )
    generate_request_type = next(iter(relevant_generate_request_types), None)

    # Now, determine if any of the `for_sources_types` may be used, either because the
    # sources_field is a direct subclass or can be generated into one of the valid types.
    def compatible_with_sources_field(valid_type: Type[Sources]) -> bool:
        is_instance = isinstance(sources_field, valid_type)
        can_be_generated = (
            request.enable_codegen
            and generate_request_type is not None
            and issubclass(generate_request_type.output, valid_type)
        )
        return is_instance or can_be_generated

    sources_type = next(
        (
            valid_type
            for valid_type in request.for_sources_types
            if compatible_with_sources_field(valid_type)
        ),
        None,
    )
    if sources_type is None:
        return HydratedSources(EMPTY_SNAPSHOT, sources_field.filespec, sources_type=None)

    # Now, hydrate the `globs`. Even if we are going to use codegen, we will need the original
    # protocol sources to be hydrated.
    globs = sources_field.sanitized_raw_value
    if globs is None:
        return HydratedSources(EMPTY_SNAPSHOT, sources_field.filespec, sources_type=sources_type)

    conjunction = (
        GlobExpansionConjunction.all_match
        if not sources_field.default or (set(globs) != set(sources_field.default))
        else GlobExpansionConjunction.any_match
    )
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

    # Finally, return if codegen is not in use; otherwise, run the relevant code generator.
    if not request.enable_codegen or generate_request_type is None:
        return HydratedSources(snapshot, sources_field.filespec, sources_type=sources_type)
    wrapped_protocol_target = await Get[WrappedTarget](Address, sources_field.address)
    generated_sources = await Get[GeneratedSources](
        GenerateSourcesRequest, generate_request_type(snapshot, wrapped_protocol_target.target)
    )
    return HydratedSources(
        generated_sources.snapshot, sources_field.filespec, sources_type=sources_type
    )


# -----------------------------------------------------------------------------------------------
# `Dependencies` field
# -----------------------------------------------------------------------------------------------

# NB: To hydrate the dependencies, use one of:
#   await Get[Addresses](DependenciesRequest(tgt[Dependencies])
#   await Get[Targets](DependenciesRequest(tgt[Dependencies])
#   await Get[TransitiveTargets](DependenciesRequest(tgt[Dependencies])
class Dependencies(AsyncField):
    """Addresses to other targets that this target depends on, e.g. `['helloworld/subdir:lib']`."""

    alias = "dependencies"
    sanitized_raw_value: Optional[Tuple[Address, ...]]
    default = None

    # NB: The type hint for `raw_value` is a lie. While we do expect end-users to use
    # Iterable[str], the Struct and Addressable code will have already converted those strings
    # into a List[Address]. But, that's an implementation detail and we don't want our
    # documentation, which is auto-generated from these type hints, to leak that.
    @classmethod
    def sanitize_raw_value(
        cls, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Optional[Tuple[Address, ...]]:
        value_or_default = super().sanitize_raw_value(raw_value, address=address)
        if value_or_default is None:
            return None
        return tuple(sorted(value_or_default))


@dataclass(frozen=True)
class DependenciesRequest:
    field: Dependencies


@union
@dataclass(frozen=True)
class InjectDependenciesRequest(ABC):
    """A request to inject dependencies, in addition to those explicitly provided.

    To set up a new injection, subclass this class. Set the class property `inject_for` to the
    type of `Dependencies` field you want to inject for, such as `FortranDependencies`. This will
    cause the class, and any subclass, to have the injection. Register this subclass with
    `UnionRule(InjectDependenciesRequest, InjectFortranDependencies)`, for example.

    Then, create a rule that takes the subclass as a parameter and returns `InjectedDependencies`.

    For example:

        class FortranDependencies(Dependencies):
            pass

        class InjectFortranDependencies(InjectDependenciesRequest):
            inject_for = FortranDependencies

        @rule
        def inject_fortran_dependencies(request: InjectFortranDependencies) -> InjectedDependencies:
            return InjectedDependencies([Address.parse("//:injected")]

        def rules():
            return [
                inject_fortran_dependencies,
                UnionRule(InjectDependenciesRequest, InjectFortranDependencies),
            ]
    """

    dependencies_field: Dependencies
    inject_for: ClassVar[Type[Dependencies]]


class InjectedDependencies(DeduplicatedCollection[Address]):
    sort_input = True


@union
@dataclass(frozen=True)
class InferDependenciesRequest:
    """A request to infer dependencies by analyzing source files.

    To set up a new inference implementation, subclass this class. Set the class property
    `infer_from` to the type of `Sources` field you are able to infer from, such as
    `FortranSources`. This will cause the class, and any subclass, to use your inference
    implementation. Note that there cannot be more than one implementation for a particular
    `Sources` class. Register this subclass with
    `UnionRule(InferDependenciesRequest, InferFortranDependencies)`, for example.

    Then, create a rule that takes the subclass as a parameter and returns `InferredDependencies`.

    For example:

        class InferFortranDependencies(InferDependenciesRequest):
            from_sources = FortranSources

        @rule
        def infer_fortran_dependencies(request: InferFortranDependencies) -> InferredDependencies:
            hydrated_sources = await Get[HydratedSources](HydrateSources(request.sources_field))
            ...
            return InferredDependencies(...)

        def rules():
            return [
                infer_fortran_dependencies,
                UnionRule(InferDependenciesRequest, InferFortranDependencies),
            ]
    """

    sources_field: Sources
    infer_from: ClassVar[Type[Sources]]


class InferredDependencies(DeduplicatedCollection[Address]):
    sort_input = True


@rule
async def resolve_dependencies(
    request: DependenciesRequest, union_membership: UnionMembership, global_options: GlobalOptions
) -> Addresses:
    provided = request.field.sanitized_raw_value or ()

    # Inject any dependencies. This is determined by the `request.field` class. For example, if
    # there is a rule to inject for FortranDependencies, then FortranDependencies and any subclass
    # of FortranDependencies will use that rule.
    inject_request_types = union_membership.get(InjectDependenciesRequest)
    injected = await MultiGet(
        Get[InjectedDependencies](InjectDependenciesRequest, inject_request_type(request.field))
        for inject_request_type in inject_request_types
        if isinstance(request.field, inject_request_type.inject_for)
    )

    inference_request_types = union_membership.get(InferDependenciesRequest)
    inferred = InferredDependencies()
    if global_options.options.dependency_inference and inference_request_types:
        # Dependency inference is solely determined by the `Sources` field for a Target, so we
        # re-resolve the original target to inspect its `Sources` field, if any.
        wrapped_tgt = await Get[WrappedTarget](Address, request.field.address)
        sources_field = wrapped_tgt.target.get(Sources)
        relevant_inference_request_types = [
            inference_request_type
            for inference_request_type in inference_request_types
            if isinstance(sources_field, inference_request_type.infer_from)
        ]
        if relevant_inference_request_types:
            if len(relevant_inference_request_types) > 1:
                raise AmbiguousDependencyInferenceException(
                    relevant_inference_request_types, from_sources_type=type(sources_field)
                )
            inference_request_type = relevant_inference_request_types[0]
            inferred = await Get[InferredDependencies](
                InferDependenciesRequest, inference_request_type(sources_field)
            )

    return Addresses(sorted([*provided, *itertools.chain.from_iterable(injected), *inferred]))


# -----------------------------------------------------------------------------------------------
# Other common Fields used across most targets
# -----------------------------------------------------------------------------------------------


class Tags(StringSequenceField):
    """Arbitrary strings that you can use to describe a target.

    For example, you may tag some test targets with 'integration_test' so that you could run
    `./pants --tags='integration_test' test ::` to only run on targets with that tag.
    """

    alias = "tags"


class DescriptionField(StringField):
    """A human-readable description of the target.

    Use `./pants list --documented ::` to see all targets with descriptions.
    """

    alias = "description"


# TODO(#9388): remove? We don't want this in V2, but maybe keep it for V1.
class NoCacheField(BoolField):
    """If True, don't store results for this target in the V1 cache."""

    alias = "no_cache"
    default = False
    v1_only = True


# TODO(#9388): remove?
class ScopeField(StringField):
    """A V1-only field for the scope of the target, which is used by the JVM to determine the
    target's inclusion in the class path.

    See `pants.build_graph.target_scopes.Scopes`.
    """

    alias = "scope"
    v1_only = True


# TODO(#9388): Remove.
class IntransitiveField(BoolField):
    alias = "_transitive"
    default = False
    v1_only = True


COMMON_TARGET_FIELDS = (Tags, DescriptionField, NoCacheField, ScopeField, IntransitiveField)


# TODO: figure out what support looks like for this with the Target API. The expected value is an
#  Artifact, but V1 has no common Artifact interface.
class ProvidesField(PrimitiveField):
    """An `artifact`, such as `setup_py` or `scala_artifact`, that describes how to represent this
    target to the outside world."""

    alias = "provides"
    default: ClassVar[Optional[Any]] = None


# TODO: Add logic to hydrate this and convert it into V1 + work with `filedeps2`.
class BundlesField(AsyncField):
    """One or more `bundle` objects that describe "extra files" that should be included with this
    app (e.g. config files, startup scripts)."""

    alias = "bundles"
    # TODO: What should this type be? Our goal is to get rid of `TargetAdaptor`, so
    #  `BundleAdaptor` should likely go away. This also results in a dependency cycle..
    sanitized_raw_value: Optional[Tuple[BundleAdaptor, ...]]
    default = None

    # NB: The type hint for `raw_value` is a lie. While we do expect end-users to use
    # Iterable[Bundle], the TargetAdaptor code will have already converted those strings
    # into a List[BundleAdaptor]. But, that's an implementation detail and we don't want our
    # documentation, which is auto-generated from these type hints, to leak that.
    @classmethod
    def sanitize_raw_value(
        cls, raw_value: Optional[Iterable[Bundle]], *, address: Address
    ) -> Optional[Tuple[BundleAdaptor, ...]]:
        value_or_default = super().sanitize_raw_value(raw_value, address=address)
        if value_or_default is None:
            return None
        try:
            ensure_list(value_or_default, expected_type=BundleAdaptor)
        except ValueError:
            raise InvalidFieldTypeException(
                address,
                cls.alias,
                value_or_default,
                expected_type="an iterable of `bundle` objects (e.g. a list)",
            )
        return cast(Tuple[BundleAdaptor, ...], tuple(value_or_default))

    @final
    @property
    def request(self):
        raise NotImplementedError


def rules():
    return [
        find_valid_field_sets,
        hydrate_sources,
        resolve_dependencies,
        RootRule(TargetsToValidFieldSetsRequest),
        RootRule(HydrateSourcesRequest),
        RootRule(DependenciesRequest),
        RootRule(InjectDependenciesRequest),
        RootRule(InferDependenciesRequest),
    ]
