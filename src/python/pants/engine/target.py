# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from typing_extensions import final

from pants.base.specs import OriginSpec
from pants.build_graph.address import Address
from pants.build_graph.app_base import Bundle
from pants.engine.addressable import assert_single_address
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    PathGlobs,
    Snapshot,
)
from pants.engine.legacy.structs import BundleAdaptor
from pants.engine.objects import Collection
from pants.engine.rules import RootRule, UnionMembership, rule
from pants.engine.selectors import Get
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper, Filespec
from pants.util.collections import ensure_list, ensure_str_list
from pants.util.frozendict import FrozenDict
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
    `./pants target-types2`. If the field is required, do not use `Optional` for the type hint of
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


# Type alias to express the intent that the type should be a new Request class created to
# correspond with its AsyncField.
AsyncFieldRequest = Any


@frozen_after_init
@dataclass(unsafe_hash=True)  # type: ignore[misc]   # https://github.com/python/mypy/issues/5374
class AsyncField(Field, metaclass=ABCMeta):
    """A field that needs the engine in order to be hydrated.

    You should implement `sanitize_raw_value()` to convert the `raw_value` into a type that is
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
        assert_single_address([tgt.address for tgt in self.dependencies])
        return self.dependencies[0]


class TargetsWithOrigins(Collection[TargetWithOrigin]):
    """A heterogeneous collection of instances of Target subclasses with the original Spec used to
    resolve the target.

    See the docstring for `Targets` for an explanation of the `Target`s being heterogeneous and how
    you should filter out the targets you care about.
    """

    def expect_single(self) -> TargetWithOrigin:
        assert_single_address(
            [tgt_with_origin.target.address for tgt_with_origin in self.dependencies]
        )
        return self.dependencies[0]


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

    Subclasses must define the class property `default`.

        class ZipSafe(BoolField):
            alias = "zip_safe"
            default = True
    """

    value: bool
    default: ClassVar[bool]

    @classmethod
    def compute_value(cls, raw_value: Optional[bool], *, address: Address) -> bool:
        value_or_default = super().compute_value(raw_value, address=address)
        if not isinstance(value_or_default, bool):
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
        if not isinstance(value_or_default, dict):
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
        if not isinstance(value_or_default, dict):
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
# Common Fields used across most targets
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


# NB: To hydrate the dependencies into Targets, use
# `await Get[Targets](Addresses(tgt[Dependencies].value)`.
class Dependencies(PrimitiveField):
    """Addresses to other targets that this target depends on, e.g. `['src/python/project:lib']`."""

    alias = "dependencies"
    value: Optional[Tuple[Address, ...]]
    default = None

    # NB: The type hint for `raw_value` is a lie. While we do expect end-users to use
    # Iterable[str], the Struct and Addressable code will have already converted those strings
    # into a List[Address]. But, that's an implementation detail and we don't want our
    # documentation, which is auto-generated from these type hints, to leak that.
    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Optional[Tuple[Address, ...]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is None:
            return None
        return tuple(sorted(value_or_default))


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
    @property
    def request(self) -> "HydrateSourcesRequest":
        return HydrateSourcesRequest(self)

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


@dataclass(frozen=True)
class HydrateSourcesRequest:
    field: Sources


@dataclass(frozen=True)
class HydratedSources:
    snapshot: Snapshot
    filespec: Filespec

    def eager_fileset_with_spec(self, *, address: Address) -> EagerFilesetWithSpec:
        return EagerFilesetWithSpec(address.spec_path, self.filespec, self.snapshot)


@rule
async def hydrate_sources(
    request: HydrateSourcesRequest, glob_match_error_behavior: GlobMatchErrorBehavior
) -> HydratedSources:
    sources_field = request.field
    globs = sources_field.sanitized_raw_value

    if globs is None:
        return HydratedSources(EMPTY_SNAPSHOT, sources_field.filespec)

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
    return HydratedSources(snapshot, sources_field.filespec)


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
    return [hydrate_sources, RootRule(HydrateSourcesRequest)]
