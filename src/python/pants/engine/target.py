# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections.abc
import dataclasses
import itertools
import logging
import os.path
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
    Iterator,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from typing_extensions import final

from pants.base.deprecated import warn_or_error
from pants.engine.addresses import Address, UnparsedAddressInputs, assert_single_address
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    PathGlobs,
    Paths,
    Snapshot,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.global_options import FilesNotFoundBehavior
from pants.source.filespec import Filespec, matches_filespec
from pants.util.collections import ensure_list, ensure_str_list
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_classproperty, memoized_method, memoized_property
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Core Field abstractions
# -----------------------------------------------------------------------------------------------

# Type alias to express the intent that the type should be immutable and hashable. There's nothing
# to actually enforce this, outside of convention. Maybe we could develop a MyPy plugin?
ImmutableValue = Any


@frozen_after_init
class Field:
    """A Field.

    The majority of fields should use field templates like `BoolField`, `StringField`, and
    `StringSequenceField`. These subclasses will provide sensible type hints and validation
    automatically.

    If you are directly subclassing `Field`, you should likely override `compute_value()`
    to perform any custom hydration and/or validation, such as converting unhashable types to
    hashable types or checking for banned values. The returned value must be hashable
    (and should be immutable) so that this Field may be used by the engine. This means, for
    example, using tuples rather than lists and using `FrozenOrderedSet` rather than `set`.

    If you plan to use the engine to fully hydrate the value, you can also inherit
    `AsyncFieldMixin`, which will store an `address: Address` property on the `Field` instance.

    Subclasses should also override the type hints for `value` and `raw_value` to be more precise
    than `Any`. The type hint for `raw_value` is used to generate documentation, e.g. for
    `./pants help $target_type`.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.

    Example:

        # NB: Really, this should subclass IntField. We only use Field as an example.
        class Timeout(Field):
            alias = "timeout"
            value: Optional[int]
            default = None
            help = "A timeout field.\n\nMore information."

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

    # Subclasses must define these.
    alias: ClassVar[str]
    help: ClassVar[str]

    # Subclasses must define at least one of these two.
    default: ClassVar[ImmutableValue]
    required: ClassVar[bool] = False

    # Subclasses may define these.
    removal_version: ClassVar[str | None] = None
    removal_hint: ClassVar[str | None] = None

    @final
    def __init__(self, raw_value: Optional[Any], address: Address) -> None:
        self._check_deprecated(raw_value, address)
        self.value: Optional[ImmutableValue] = self.compute_value(raw_value, address)

    @classmethod
    def compute_value(cls, raw_value: Optional[Any], address: Address) -> ImmutableValue:
        """Convert the `raw_value` into `self.value`.

        You should perform any optional validation and/or hydration here. For example, you may want
        to check that an integer is > 0 or convert an `Iterable[str]` to `List[str]`.

        The resulting value must be hashable (and should be immutable).
        """
        if raw_value is None:
            if cls.required:
                raise RequiredFieldMissingException(address, cls.alias)
            return cls.default
        return raw_value

    @classmethod
    def _check_deprecated(cls, raw_value: Optional[Any], address: Address) -> None:
        if not cls.removal_version or address.is_file_target or raw_value is None:
            return
        if not cls.removal_hint:
            raise ValueError(
                f"You specified `removal_version` for {cls}, but not the class property "
                "`removal_hint`."
            )
        warn_or_error(
            cls.removal_version,
            entity=f"the {repr(cls.alias)} field",
            hint=(f"Using the `{cls.alias}` field in the target {address}. " f"{cls.removal_hint}"),
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__}(alias={repr(self.alias)}, value={repr(self.value)}, "
            f"default={repr(self.default)})"
        )

    def __str__(self) -> str:
        return f"{self.alias}={self.value}"

    def __hash__(self) -> int:
        return hash((self.__class__, self.value))

    def __eq__(self, other: Union[Any, Field]) -> bool:
        if not isinstance(other, Field):
            return NotImplemented
        return (self.__class__, self.value) == (other.__class__, other.value)


# NB: By subclassing `Field`, MyPy understands our type hints, and it means it doesn't matter which
# order you use for inheriting the field template vs. the mixin.
class AsyncFieldMixin(Field):
    """A mixin to store the field's original `Address` for use during hydration by the engine.

    Typically, you should also create a dataclass representing the hydrated value and another for
    the request, then a rule to go from the request to the hydrated value. The request class should
    store the async field as a property.

    (Why use the request class as the rule input, rather than the field itself? It's a wrapper so
    that subclasses of the async field work properly, given that the engine uses exact type IDs.
    This is like WrappedTarget.)

    For example:

        class Sources(StringSequenceField, AsyncFieldMixin):
            alias = "sources"

            # Often, async fields will want to define entry points like this to allow subclasses to
            # change behavior.
            def validate_resolved_files(self, files: Sequence[str]) -> None:
                pass


        @dataclass(frozen=True)
        class HydrateSourcesRequest:
            field: Sources


        @dataclass(frozen=True)
        class HydratedSources:
            snapshot: Snapshot


        @rule
        def hydrate_sources(request: HydrateSourcesRequest) -> HydratedSources:
            result = await Get(Snapshot, PathGlobs(request.field.value))
            request.field.validate_resolved_files(result.files)
            ...
            return HydratedSources(result)

    Then, call sites can `await Get` if they need to hydrate the field, even if they subclassed
    the original async field to have custom behavior:

        sources1 = await Get(HydratedSources, HydrateSourcesRequest(my_tgt.get(Sources)))
        sources2 = await Get(HydratedSources, HydrateSourcesRequest(custom_tgt.get(CustomSources)))
    """

    @final  # type: ignore[misc]
    def __init__(self, raw_value: Optional[Any], address: Address) -> None:
        super().__init__(raw_value, address)
        # We must temporarily unfreeze the field, but then we refreeze to continue avoiding
        # subclasses from adding arbitrary fields.
        self._unfreeze_instance()  # type: ignore[attr-defined]
        # N.B.: We store the address here and not in the Field base class, because the memory usage
        # of storing this value in every field was shown to be excessive / lead to performance
        # issues.
        self.address = address
        self._freeze_instance()  # type: ignore[attr-defined]

    def __repr__(self) -> str:
        return (
            f"{self.__class__}(alias={repr(self.alias)}, address={self.address}, "
            "value={repr(self.value)}, default={repr(self.default)})"
        )

    def __hash__(self) -> int:
        return hash((self.__class__, self.value, self.address))

    def __eq__(self, other: Union[Any, AsyncFieldMixin]) -> bool:
        if not isinstance(other, AsyncFieldMixin):
            return NotImplemented
        return (self.__class__, self.value, self.address) == (
            other.__class__,
            other.value,
            other.address,
        )


# -----------------------------------------------------------------------------------------------
# Core Target abstractions
# -----------------------------------------------------------------------------------------------

# NB: This TypeVar is what allows `Target.get()` to properly work with MyPy so that MyPy knows
# the precise Field returned.
_F = TypeVar("_F", bound=Field)


@frozen_after_init
class Target:
    """A Target represents a combination of fields that are valid _together_.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.
    """

    # Subclasses must define these
    alias: ClassVar[str]
    core_fields: ClassVar[tuple[type[Field], ...]]
    help: ClassVar[str]

    # Subclasses may define these.
    removal_version: ClassVar[str | None] = None
    removal_hint: ClassVar[str | None] = None

    # These get calculated in the constructor
    address: Address
    plugin_fields: tuple[type[Field], ...]
    field_values: FrozenDict[type[Field], Field]

    @final
    def __init__(
        self,
        unhydrated_values: dict[str, Any],
        address: Address,
        *,
        # NB: `union_membership` is only optional to facilitate tests. In production, we should
        # always provide this parameter. This should be safe to do because production code should
        # rarely directly instantiate Targets and should instead use the engine to request them.
        union_membership: UnionMembership | None = None,
    ) -> None:
        if self.removal_version and not address.is_file_target:
            if not self.removal_hint:
                raise ValueError(
                    f"You specified `removal_version` for {self.__class__}, but not "
                    "the class property `removal_hint`."
                )
            warn_or_error(
                self.removal_version,
                entity=f"the {repr(self.alias)} target type",
                hint=(
                    f"Using the `{self.alias}` target type for {address}. " f"{self.removal_hint}"
                ),
            )

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
            field_values[field_type] = field_type(value, address)
        # For undefined fields, mark the raw value as None.
        for field_type in set(self.field_types) - set(field_values.keys()):
            field_values[field_type] = field_type(None, address)
        self.field_values = FrozenDict(
            sorted(
                field_values.items(),
                key=lambda field_type_to_val_pair: field_type_to_val_pair[0].alias,
            )
        )

    @final
    @property
    def field_types(self) -> tuple[type[Field], ...]:
        return (*self.core_fields, *self.plugin_fields)

    @final
    @memoized_classproperty
    def _plugin_field_cls(cls) -> type:
        # NB: We ensure that each Target subtype has its own `PluginField` class so that
        # registering a plugin field doesn't leak across target types.

        @union
        class PluginField:
            pass

        return PluginField

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

    def __hash__(self) -> int:
        return hash((self.__class__, self.address, self.field_values))

    def __eq__(self, other: Union[Target, Any]) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return (self.__class__, self.address, self.field_values) == (
            other.__class__,
            other.address,
            other.field_values,
        )

    @final
    @classmethod
    def _find_plugin_fields(cls, union_membership: UnionMembership) -> Tuple[Type[Field], ...]:
        return cast(Tuple[Type[Field], ...], tuple(union_membership.get(cls._plugin_field_cls)))

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
        `InterpreterConstraints`, `Sources`, `EntryPoint`, etc. Usually, you will want to grab the
        `Field`'s inner value, e.g. `tgt.get(Compatibility).value`. (For async fields like
        `Sources`, you may need to hydrate the value.).

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
        return field(default_raw_value, self.address)

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
    def class_has_field(cls, field: Type[Field], union_membership: UnionMembership) -> bool:
        """Behaves like `Target.has_field()`, but works as a classmethod rather than an instance
        method."""
        return cls.class_has_fields([field], union_membership)

    @final
    @classmethod
    def class_has_fields(
        cls, fields: Iterable[Type[Field]], union_membership: UnionMembership
    ) -> bool:
        """Behaves like `Target.has_fields()`, but works as a classmethod rather than an instance
        method."""
        return cls._has_fields(fields, registered_fields=cls.class_field_types(union_membership))

    @final
    @classmethod
    def class_get_field(cls, field: Type[_F], union_membership: UnionMembership) -> Type[_F]:
        """Get the requested Field type registered with this target type.

        This will error if the field is not registered, so you should call Target.class_has_field()
        first.
        """
        class_fields = cls.class_field_types(union_membership)
        result = next(
            (
                registered_field
                for registered_field in class_fields
                if issubclass(registered_field, field)
            ),
            None,
        )
        if result is None:
            raise KeyError(
                f"The target type `{cls.alias}` does not have a field `{field.__name__}`. Before "
                f"calling `TargetType.class_get_field({field.__name__})`, call "
                f"`TargetType.class_has_field({field.__name__})`."
            )
        return result

    @final
    @classmethod
    def register_plugin_field(cls, field: Type[Field]) -> UnionRule:
        """Register a new field on the target type.

        In the `rules()` register.py entry-point, include
        `MyTarget.register_plugin_field(NewField)`. This will register `NewField` as a first-class
        citizen. Plugins can use this new field like any other.
        """
        return UnionRule(cls._plugin_field_cls, field)


@dataclass(frozen=True)
class Subtargets:
    # The BUILD target from which the subtargets were extracted.
    base: Target
    # The subtargets, one per file that was owned by the BUILD target.
    subtargets: Tuple[Target, ...]


@dataclass(frozen=True)
class WrappedTarget:
    """A light wrapper to encapsulate all the distinct `Target` subclasses into a single type.

    This is necessary when using a single target in a rule because the engine expects exact types
    and does not work with subtypes.
    """

    target: Target


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


class UnexpandedTargets(Collection[Target]):
    """Like `Targets`, but will not contain the expansion of `TargetAlias` instances."""

    def expect_single(self) -> Target:
        assert_single_address([tgt.address for tgt in self])
        return self[0]


@dataclass(frozen=True)
class TransitiveTargets:
    """A set of Target roots, and their transitive, flattened, de-duped dependencies.

    If a target root is a dependency of another target root, then it will show up both in `roots`
    and in `dependencies`.
    """

    roots: Tuple[Target, ...]
    dependencies: FrozenOrderedSet[Target]

    @memoized_property
    def closure(self) -> FrozenOrderedSet[Target]:
        """The roots and the dependencies combined."""
        return FrozenOrderedSet([*self.roots, *self.dependencies])


@frozen_after_init
@dataclass(unsafe_hash=True)
class TransitiveTargetsRequest:
    """A request to get the transitive dependencies of the input roots.

    Resolve the transitive targets with `await Get(TransitiveTargets,
    TransitiveTargetsRequest([addr1, addr2])`.
    """

    roots: Tuple[Address, ...]
    include_special_cased_deps: bool

    def __init__(
        self, roots: Iterable[Address], *, include_special_cased_deps: bool = False
    ) -> None:
        self.roots = tuple(roots)
        self.include_special_cased_deps = include_special_cased_deps


@frozen_after_init
@dataclass(unsafe_hash=True)
class RegisteredTargetTypes:
    aliases_to_types: FrozenDict[str, Type[Target]]

    def __init__(self, aliases_to_types: Mapping[str, Type[Target]]) -> None:
        self.aliases_to_types = FrozenDict(aliases_to_types)

    @classmethod
    def create(cls, target_types: Iterable[Type[Target]]) -> RegisteredTargetTypes:
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
# Generated subtargets
# -----------------------------------------------------------------------------------------------


def generate_subtarget_address(build_target_address: Address, *, full_file_name: str) -> Address:
    """Return the address for a new target based on the BUILD target, but with a more precise
    `sources` field.

    The address's target name will be the relativized file, such as `:app.json`, or `:subdir/f.txt`.

    See generate_subtarget().
    """
    if build_target_address.is_file_target:
        raise ValueError(f"Cannot generate file targets for a file Address: {build_target_address}")
    original_spec_path = build_target_address.spec_path
    relative_file_path = PurePath(full_file_name).relative_to(original_spec_path).as_posix()
    return Address(
        spec_path=original_spec_path,
        target_name=build_target_address.target_name,
        relative_file_path=relative_file_path,
    )


_Tgt = TypeVar("_Tgt", bound=Target)


def generate_subtarget(
    build_target: _Tgt,
    *,
    full_file_name: str,
    # NB: `union_membership` is only optional to facilitate tests. In production, we should
    # always provide this parameter. This should be safe to do because production code should
    # rarely directly instantiate Targets and should instead use the engine to request them.
    union_membership: Optional[UnionMembership] = None,
) -> _Tgt:
    """Generate a new target with the exact same metadata as the BUILD target, except for the
    `sources` field only referring to the single file `full_file_name` and with a new address.

    This is used for greater precision when using dependency inference and file arguments. When we
    are able to deduce specifically which files are being used, we can use only the files we care
    about, rather than the entire `sources` field.
    """
    if not build_target.has_field(Dependencies) or not build_target.has_field(Sources):
        raise ValueError(
            f"Target {build_target.address.spec} of type {type(build_target).__qualname__} does "
            "not have both a `dependencies` and `sources` field, and thus cannot generate a "
            f"subtarget for the file {full_file_name}."
        )

    relativized_file_name = (
        PurePath(full_file_name).relative_to(build_target.address.spec_path).as_posix()
    )

    generated_target_fields = {}
    for field in build_target.field_values.values():
        value: Optional[ImmutableValue]
        if isinstance(field, Sources):
            if not bool(matches_filespec(field.filespec, paths=[full_file_name])):
                raise ValueError(
                    f"Target {build_target.address.spec}'s `sources` field does not match a file "
                    f"{full_file_name}."
                )
            value = (relativized_file_name,)
        else:
            value = field.value
        generated_target_fields[field.alias] = value

    target_cls = type(build_target)
    return target_cls(
        generated_target_fields,
        generate_subtarget_address(build_target.address, full_file_name=full_file_name),
        union_membership=union_membership,
    )


# -----------------------------------------------------------------------------------------------
# FieldSet
# -----------------------------------------------------------------------------------------------


def _get_field_set_fields_from_target(
    field_set: type[FieldSet], target: Target
) -> dict[str, Field]:
    all_expected_fields: dict[str, type[Field]] = {
        dataclass_field.name: dataclass_field.type
        for dataclass_field in dataclasses.fields(field_set)
        if isinstance(dataclass_field.type, type) and issubclass(dataclass_field.type, Field)
    }
    return {
        dataclass_field_name: (
            target[field_cls] if field_cls in field_set.required_fields else target.get(field_cls)
        )
        for dataclass_field_name, field_cls in all_expected_fields.items()
    }


_FS = TypeVar("_FS", bound="FieldSet")


@dataclass(frozen=True)
class FieldSet(EngineAwareParameter, metaclass=ABCMeta):
    """An ad hoc set of fields from a target which are used by rules.

    Subclasses should declare all the fields they consume as dataclass attributes. They should also
    indicate which of these are required, rather than optional, through the class property
    `required_fields`. When a field is optional, the default constructor for the field will be used
    for any targets that do not have that field registered.

    Subclasses must set `@dataclass(frozen=True)` for their declared fields to be recognized.

    You can optionally set implement the classmethod `opt_out` so that targets have a
    mechanism to not match with the FieldSet even if they have the `required_fields` registered.

    For example:

        @dataclass(frozen=True)
        class FortranTestFieldSet(FieldSet):
            required_fields = (FortranSources,)

            sources: FortranSources
            fortran_version: FortranVersion

            @classmethod
            def opt_out(cls, tgt: Target) -> bool:
                return tgt.get(MaybeSkipFortranTestsField).value

    This field set may then created from a `Target` through the `is_applicable()` and `create()`
    class methods:

        field_sets = [
            FortranTestFieldSet.create(tgt) for tgt in targets
            if FortranTestFieldSet.is_applicable(tgt)
        ]

    FieldSets are consumed like any normal dataclass:

        print(field_set.address)
        print(field_set.sources)
    """

    required_fields: ClassVar[tuple[type[Field], ...]]

    address: Address

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        """If `True`, the target will not match with the field set, even if it has the FieldSet's
        `required_fields`.

        Note: this method is not intended to categorically opt out a target type from a
        FieldSet, i.e. to always opt out based solely on the target type. While it is possible to
        do, some error messages will incorrectly suggest that that target is compatible with the
        FieldSet. Instead, if you need this feature, please ask us to implement it. See
        https://github.com/pantsbuild/pants/pull/12002 for discussion.
        """
        return False

    @final
    @classmethod
    def is_applicable(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields) and not cls.opt_out(tgt)

    @final
    @classmethod
    def applicable_target_types(
        cls, target_types: Iterable[Type[Target]], union_membership: UnionMembership
    ) -> tuple[type[Target], ...]:
        return tuple(
            tgt_type
            for tgt_type in target_types
            if tgt_type.class_has_fields(cls.required_fields, union_membership)
        )

    @final
    @classmethod
    def create(cls: type[_FS], tgt: Target) -> _FS:
        return cls(  # type: ignore[call-arg]
            address=tgt.address, **_get_field_set_fields_from_target(cls, tgt)
        )

    def debug_hint(self) -> str:
        return self.address.spec

    def __repr__(self) -> str:
        # We use a short repr() because this often shows up in stack traces. We don't need any of
        # the field information because we can ask a user to send us their BUILD file.
        return f"{self.__class__.__name__}(address={self.address})"


@frozen_after_init
@dataclass(unsafe_hash=True)
class TargetRootsToFieldSets(Generic[_FS]):
    mapping: FrozenDict[Target, tuple[_FS, ...]]

    def __init__(self, mapping: Mapping[Target, Iterable[_FS]]) -> None:
        self.mapping = FrozenDict({tgt: tuple(field_sets) for tgt, field_sets in mapping.items()})

    @memoized_property
    def field_sets(self) -> tuple[_FS, ...]:
        return tuple(
            itertools.chain.from_iterable(
                field_sets_per_target for field_sets_per_target in self.mapping.values()
            )
        )

    @memoized_property
    def targets(self) -> tuple[Target, ...]:
        return tuple(self.mapping.keys())


class NoApplicableTargetsBehavior(Enum):
    ignore = "ignore"
    warn = "warn"
    error = "error"


@frozen_after_init
@dataclass(unsafe_hash=True)
class TargetRootsToFieldSetsRequest(Generic[_FS]):
    field_set_superclass: type[_FS]
    goal_description: str
    no_applicable_targets_behavior: NoApplicableTargetsBehavior
    expect_single_field_set: bool
    # TODO: Add a `require_sources` field. To do this, figure out the dependency cycle with
    #  `util_rules/filter_empty_sources.py`.

    def __init__(
        self,
        field_set_superclass: type[_FS],
        *,
        goal_description: str,
        no_applicable_targets_behavior: NoApplicableTargetsBehavior,
        expect_single_field_set: bool = False,
    ) -> None:
        self.field_set_superclass = field_set_superclass
        self.goal_description = goal_description
        self.no_applicable_targets_behavior = no_applicable_targets_behavior
        self.expect_single_field_set = expect_single_field_set


@frozen_after_init
@dataclass(unsafe_hash=True)
class FieldSetsPerTarget(Generic[_FS]):
    # One tuple of FieldSet instances per input target.
    collection: tuple[tuple[_FS, ...], ...]

    def __init__(self, collection: Iterable[Iterable[_FS]]):
        self.collection = tuple(tuple(iterable) for iterable in collection)

    @memoized_property
    def field_sets(self) -> tuple[_FS, ...]:
        return tuple(itertools.chain.from_iterable(self.collection))


@frozen_after_init
@dataclass(unsafe_hash=True)
class FieldSetsPerTargetRequest(Generic[_FS]):
    field_set_superclass: type[_FS]
    targets: tuple[Target, ...]

    def __init__(self, field_set_superclass: type[_FS], targets: Iterable[Target]):
        self.field_set_superclass = field_set_superclass
        self.targets = tuple(targets)


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
        for_address = f" for address {address}" if address else ""
        super().__init__(
            f"Target type {repr(target_type)} is not registered{for_address}.\n\nAll valid target "
            f"types: {sorted(registered_target_types.aliases)}\n\n(If {repr(target_type)} is a "
            "custom target type, refer to "
            "https://groups.google.com/forum/#!topic/pants-devel/WsRFODRLVZI for instructions on "
            "writing a light-weight Target API binding.)"
        )


# -----------------------------------------------------------------------------------------------
# Field templates
# -----------------------------------------------------------------------------------------------

T = TypeVar("T")


class ScalarField(Generic[T], Field):
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
    def compute_value(cls, raw_value: Optional[Any], address: Address) -> Optional[T]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default is not None and not isinstance(value_or_default, cls.expected_type):
            raise InvalidFieldTypeException(
                address,
                cls.alias,
                raw_value,
                expected_type=cls.expected_type_description,
            )
        return value_or_default


class BoolField(Field):
    """A field whose value is a boolean.

    Subclasses must either set `default: bool` or `required = True` so that the value is always
    defined.
    """

    value: bool
    default: ClassVar[bool]

    @classmethod
    def compute_value(cls, raw_value: bool, address: Address) -> bool:  # type: ignore[override]
        value_or_default = super().compute_value(raw_value, address)
        if not isinstance(value_or_default, bool):
            raise InvalidFieldTypeException(
                address, cls.alias, raw_value, expected_type="a boolean"
            )
        return value_or_default


class TriBoolField(ScalarField[bool]):
    """A field whose value is a boolean or None, which is meant to represent a tri-state."""

    expected_type = bool
    expected_type_description = "a boolean or None"

    @classmethod
    def compute_value(cls, raw_value: Optional[bool], address: Address) -> Optional[bool]:
        return super().compute_value(raw_value, address)


class IntField(ScalarField[int]):
    expected_type = int
    expected_type_description = "an integer"

    @classmethod
    def compute_value(cls, raw_value: Optional[int], address: Address) -> Optional[int]:
        return super().compute_value(raw_value, address)


class FloatField(ScalarField[float]):
    expected_type = float
    expected_type_description = "a float"

    @classmethod
    def compute_value(cls, raw_value: Optional[float], address: Address) -> Optional[float]:
        return super().compute_value(raw_value, address)


class StringField(ScalarField[str]):
    """A field whose value is a string.

    If you expect the string to only be one of several values, set the class property
    `valid_choices`.
    """

    expected_type = str
    expected_type_description = "a string"
    valid_choices: ClassVar[Optional[Union[Type[Enum], Tuple[str, ...]]]] = None

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address)
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


class SequenceField(Generic[T], Field):
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
        cls, raw_value: Optional[Iterable[Any]], address: Address
    ) -> Optional[Tuple[T, ...]]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default is None:
            return None
        try:
            ensure_list(value_or_default, expected_type=cls.expected_element_type)
        except ValueError:
            raise InvalidFieldTypeException(
                address,
                cls.alias,
                raw_value,
                expected_type=cls.expected_type_description,
            )
        return tuple(value_or_default)


class StringSequenceField(SequenceField[str]):
    expected_element_type = str
    expected_type_description = "an iterable of strings (e.g. a list of strings)"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Optional[Tuple[str, ...]]:
        return super().compute_value(raw_value, address)


class DictStringToStringField(Field):
    value: Optional[FrozenDict[str, str]]
    default: ClassVar[Optional[FrozenDict[str, str]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, str]], address: Address
    ) -> Optional[FrozenDict[str, str]]:
        value_or_default = super().compute_value(raw_value, address)
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


class DictStringToStringSequenceField(Field):
    value: Optional[FrozenDict[str, Tuple[str, ...]]]
    default: ClassVar[Optional[FrozenDict[str, Tuple[str, ...]]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, Iterable[str]]], address: Address
    ) -> Optional[FrozenDict[str, Tuple[str, ...]]]:
        value_or_default = super().compute_value(raw_value, address)
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


class Sources(StringSequenceField, AsyncFieldMixin):
    alias = "sources"
    expected_file_extensions: ClassVar[tuple[str, ...] | None] = None
    expected_num_files: ClassVar[int | range | None] = None
    uses_source_roots: ClassVar[bool] = True
    help = (
        "A list of files and globs that belong to this target.\n\nPaths are relative to the BUILD "
        "file's directory. You can ignore files/globs by prefixing them with `!`.\n\nExample: "
        "`sources=['example.py', 'test_*.py', '!test_ignore.py']`."
    )

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        """Perform any additional validation on the resulting source files, e.g. ensuring that
        certain banned files are not used.

        To enforce that the resulting files end in certain extensions, such as `.py` or `.java`, set
        the class property `expected_file_extensions`.

        To enforce that there are only a certain number of resulting files, such as binary targets
        checking for only 0-1 sources, set the class property `expected_num_files`.
        """
        if self.expected_file_extensions is not None:
            bad_files = [
                fp for fp in files if not PurePath(fp).suffix in self.expected_file_extensions
            ]
            if bad_files:
                expected = (
                    f"one of {sorted(self.expected_file_extensions)}"
                    if len(self.expected_file_extensions) > 1
                    else repr(self.expected_file_extensions[0])
                )
                raise InvalidFieldException(
                    f"The {repr(self.alias)} field in target {self.address} can only contain "
                    f"files that end in {expected}, but it had these files: {sorted(bad_files)}."
                    f"\n\nMaybe create a `resources()` or `files()` target and include it in the "
                    f"`dependencies` field?"
                )
        if self.expected_num_files is not None:
            num_files = len(files)
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

    @staticmethod
    def prefix_glob_with_dirpath(dirpath: str, glob: str) -> str:
        if glob.startswith("!"):
            return f"!{os.path.join(dirpath, glob[1:])}"
        return os.path.join(dirpath, glob)

    @final
    def _prefix_glob_with_address(self, glob: str) -> str:
        return self.prefix_glob_with_dirpath(self.address.spec_path, glob)

    @final
    def path_globs(self, files_not_found_behavior: FilesNotFoundBehavior) -> PathGlobs:
        globs = self.value or ()
        error_behavior = files_not_found_behavior.to_glob_match_error_behavior()
        conjunction = (
            GlobExpansionConjunction.all_match
            if not self.default or (set(globs) != set(self.default))
            else GlobExpansionConjunction.any_match
        )
        return PathGlobs(
            (self._prefix_glob_with_address(glob) for glob in globs),
            conjunction=conjunction,
            glob_match_error_behavior=error_behavior,
            # TODO(#9012): add line number referring to the sources field. When doing this, we'll
            # likely need to `await Get(BuildFileAddress, Address)`.
            description_of_origin=(
                f"{self.address}'s `{self.alias}` field"
                if error_behavior != GlobMatchErrorBehavior.ignore
                else None
            ),
        )

    @final
    @property
    def filespec(self) -> Filespec:
        """The original globs, returned in the Filespec dict format.

        The globs will be relativized to the build root.
        """
        includes = []
        excludes = []
        for glob in self.value or ():
            if glob.startswith("!"):
                excludes.append(os.path.join(self.address.spec_path, glob[1:]))
            else:
                includes.append(os.path.join(self.address.spec_path, glob))
        result: Filespec = {"includes": includes}
        if excludes:
            result["excludes"] = excludes
        return result

    @final
    @classmethod
    def can_generate(cls, output_type: Type["Sources"], union_membership: UnionMembership) -> bool:
        """Can this Sources field be used to generate the output_type?

        Generally, this method does not need to be used. Most call sites can simply use the below,
        and the engine will generate the sources if possible or will return an instance of
        HydratedSources with an empty snapshot if not possible:

            await Get(
                HydratedSources,
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
class HydrateSourcesRequest(EngineAwareParameter):
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

    def debug_hint(self) -> str:
        return self.field.address.spec


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


@union
@dataclass(frozen=True)
class GenerateSourcesRequest(EngineAwareParameter):
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

    def debug_hint(self) -> str:
        return "{self.protocol_target.address.spec}"


@dataclass(frozen=True)
class GeneratedSources:
    snapshot: Snapshot


class SourcesPaths(Paths):
    """The resolved file names of the `sources` field.

    This does not consider codegen, and only captures the files from the `sources` field.
    """


@dataclass(frozen=True)
class SourcesPathsRequest(EngineAwareParameter):
    """A request to resolve the file names of the `sources` field.

    Use via `Get(SourcesPaths, SourcesPathRequest(tgt.get(Sources))`.

    This is faster than `Get(HydratedSources, HydrateSourcesRequest)` because it does not snapshot
    the files and it only resolves the file names.

    This does not consider codegen, and only captures the files from the `sources` field. Use
    `HydrateSourcesRequest` to use codegen.
    """

    field: Sources

    def debug_hint(self) -> str:
        return self.field.address.spec


class SecondaryOwnerMixin(ABC):
    """Add to a Field for the target to work with file arguments and `--changed-since`, without it
    needing a `Sources` field.

    Why use this? In a dependency inference world, multiple targets including the same file in the
    `sources` field causes issues due to ambiguity over which target to use. So, only one target
    should have "primary ownership" of the file. However, you may still want other targets to be
    used when that file is included in file arguments. For example, a `python_library` target
    being the primary owner of the `.py` file, but a `pex_binary` still working with file
    arguments for that file. Secondary ownership means that the target won't be used for things like
    dependency inference and hydrating sources, but file arguments will still work.

    There should be a primary owner of the file(s), e.g. the `python_library` in the above example.
    Typically, you will want to add a dependency injection rule to infer a dep on that primary
    owner.

    All associated files must live in the BUILD target's directory or a subdirectory to work
    properly, like the `sources` field.
    """

    @property
    @abstractmethod
    def filespec(self) -> Filespec:
        """A dictionary in the form {'globs': ['full/path/to/f.ext']} representing the field's
        associated files.

        Typically, users should use a file name/glob relative to the BUILD file, like the `sources`
        field. Then, you can use `os.path.join(self.address.spec_path, self.value)` to relative to
        the build root.
        """


def targets_with_sources_types(
    sources_types: Iterable[type[Sources]],
    targets: Iterable[Target],
    union_membership: UnionMembership,
) -> tuple[Target, ...]:
    """Return all targets either with the specified sources subclass(es) or which can generate those
    sources."""
    return tuple(
        tgt
        for tgt in targets
        if any(
            tgt.has_field(sources_type)
            or tgt.get(Sources).can_generate(sources_type, union_membership)
            for sources_type in sources_types
        )
    )


# -----------------------------------------------------------------------------------------------
# `Dependencies` field
# -----------------------------------------------------------------------------------------------


class Dependencies(StringSequenceField, AsyncFieldMixin):
    """The dependencies field.

    To resolve all dependencies—including the results of dependency injection and inference—use
    either `await Get(Addresses, DependenciesRequest(tgt[Dependencies])` or `await Get(Targets,
    DependenciesRequest(tgt[Dependencies])`.
    """

    alias = "dependencies"
    help = (
        "Addresses to other targets that this target depends on, e.g. ['helloworld/subdir:lib']."
        "\n\nAlternatively, you may include file names. Pants will find which target owns that "
        "file, and create a new target from that which only includes the file in its `sources` "
        "field. For files relative to the current BUILD file, prefix with `./`; otherwise, put the "
        "full path, e.g. ['./sibling.txt', 'resources/demo.json'].\n\nYou may exclude dependencies "
        "by prefixing with `!`, e.g. `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are "
        "intended for false positives with dependency inference; otherwise, simply leave off the "
        "dependency from the BUILD file."
    )
    supports_transitive_excludes = False

    @memoized_property
    def unevaluated_transitive_excludes(self) -> UnparsedAddressInputs:
        if not self.supports_transitive_excludes or not self.value:
            return UnparsedAddressInputs((), owning_address=self.address)
        return UnparsedAddressInputs(
            (v[2:] for v in self.value if v.startswith("!!")),
            owning_address=self.address,
        )


@dataclass(frozen=True)
class DependenciesRequest(EngineAwareParameter):
    field: Dependencies
    include_special_cased_deps: bool = False

    def debug_hint(self) -> str:
        return self.field.address.spec


@dataclass(frozen=True)
class ExplicitlyProvidedDependencies:
    """The literal addresses from a BUILD file `dependencies` field.

    Almost always, you should use `await Get(Addresses, DependenciesRequest)` instead, which will
    consider dependency injection and inference and apply ignores. However, this type can be
    useful particularly within inference/injection rules to see if a user already explicitly
    provided a dependency.

    Resolve using `await Get(ExplicitlyProvidedDependencies, DependenciesRequest)`.

    Note that the `includes` are not filtered based on the `ignores`: this type preserves exactly
    what was in the BUILD file.
    """

    includes: FrozenOrderedSet[Address]
    ignores: FrozenOrderedSet[Address]

    @memoized_method
    def any_are_covered_by_includes(self, addresses: tuple[Address, ...]) -> bool:
        """Return True if every address is in the explicitly provided includes.

        Note that if the input addresses are file addresses, they will still be marked as covered if
        their original BUILD target is in the explicitly provided includes.
        """
        return any(
            addr in self.includes or addr.maybe_convert_to_build_target() in self.includes
            for addr in addresses
        )

    @memoized_method
    def remaining_after_ignores(self, addresses: tuple[Address, ...]) -> frozenset[Address]:
        """All addresses that are not covered by the explicitly provided ignores.

        Note that if the input addresses are file addresses, they will still be marked as covered if
        their original BUILD target is in the explicitly provided ignores.
        """
        return frozenset(
            addr
            for addr in addresses
            if (
                addr not in self.ignores
                and addr.maybe_convert_to_build_target() not in self.ignores
            )
        )

    def maybe_warn_of_ambiguous_dependency_inference(
        self,
        ambiguous_addresses: tuple[Address, ...],
        original_address: Address,
        *,
        context: str,
        import_reference: str,
    ) -> None:
        """If the module is ambiguous and the user did not disambiguate via explicitly provided
        dependencies, warn that dependency inference will not be used."""
        if not ambiguous_addresses or self.any_are_covered_by_includes(ambiguous_addresses):
            return
        remaining_after_ignores = self.remaining_after_ignores(ambiguous_addresses)
        if len(remaining_after_ignores) <= 1:
            return
        logger.warning(
            f"{context}, but Pants cannot safely infer a dependency because more than one target "
            f"owns this {import_reference}, so it is ambiguous which to use: "
            f"{sorted(addr.spec for addr in remaining_after_ignores)}."
            f"\n\nPlease explicitly include the dependency you want in the `dependencies` "
            f"field of {original_address}, or ignore the ones you do not want by prefixing "
            f"with `!` or `!!` so that one or no targets are left."
            f"\n\nAlternatively, you can remove the ambiguity by deleting/changing some of the "
            f"targets so that only 1 target owns this {import_reference}. Refer to "
            f"{doc_url('troubleshooting#import-errors-and-missing-dependencies')}."
        )

    def disambiguated_via_ignores(self, ambiguous_addresses: tuple[Address, ...]) -> Address | None:
        """If exactly one of the input addresses remains after considering the explicitly provided
        ignores, return it because it is disambiguated."""
        if not ambiguous_addresses or self.any_are_covered_by_includes(ambiguous_addresses):
            return None
        remaining_after_ignores = self.remaining_after_ignores(ambiguous_addresses)
        return list(remaining_after_ignores)[0] if len(remaining_after_ignores) == 1 else None


@union
@dataclass(frozen=True)
class InjectDependenciesRequest(EngineAwareParameter, ABC):
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
        async def inject_fortran_dependencies(
            request: InjectFortranDependencies
        ) -> InjectedDependencies:
            addresses = await Get(
                Addresses, UnparsedAddressInputs(["//:injected"], owning_address=None)
            )
            return InjectedDependencies(addresses)

        def rules():
            return [
                *collect_rules(),
                UnionRule(InjectDependenciesRequest, InjectFortranDependencies),
            ]
    """

    dependencies_field: Dependencies
    inject_for: ClassVar[Type[Dependencies]]

    def debug_hint(self) -> str:
        return self.dependencies_field.address.spec


class InjectedDependencies(DeduplicatedCollection[Address]):
    sort_input = True


@union
@dataclass(frozen=True)
class InferDependenciesRequest(EngineAwareParameter):
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
            hydrated_sources = await Get(HydratedSources, HydrateSources(request.sources_field))
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

    def debug_hint(self) -> str:
        return self.sources_field.address.spec


@frozen_after_init
@dataclass(unsafe_hash=True)
class InferredDependencies:
    dependencies: FrozenOrderedSet[Address]
    sibling_dependencies_inferrable: bool

    def __init__(
        self, dependencies: Iterable[Address], *, sibling_dependencies_inferrable: bool
    ) -> None:
        """The result of inferring dependencies.

        If the inference implementation is able to infer file-level dependencies on sibling files
        belonging to the same target, set sibling_dependencies_inferrable=True. This allows for
        finer-grained caching because the dependency rule will not automatically add a dependency on
        all sibling files.
        """
        self.dependencies = FrozenOrderedSet(sorted(dependencies))
        self.sibling_dependencies_inferrable = sibling_dependencies_inferrable

    def __bool__(self) -> bool:
        return bool(self.dependencies)

    def __iter__(self) -> Iterator[Address]:
        return iter(self.dependencies)


class SpecialCasedDependencies(StringSequenceField, AsyncFieldMixin):
    """Subclass this for fields that act similarly to the `dependencies` field, but are handled
    differently than normal dependencies.

    For example, you might have a field for package/binary dependencies, which you will call
    the equivalent of `./pants package` on. While you could put these in the normal
    `dependencies` field, it is often clearer to the user to call out this magic through a
    dedicated field.

    This type will ensure that the dependencies show up in project introspection,
    like `dependencies` and `dependees`, but not show up when you call `Get(TransitiveTargets,
    TransitiveTargetsRequest)` and `Get(Addresses, DependenciesRequest)`.

    To hydrate this field's dependencies, use `await Get(Addresses, UnparsedAddressInputs,
    tgt.get(MyField).to_unparsed_address_inputs()`.
    """

    def to_unparsed_address_inputs(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.value or (), owning_address=self.address)


# -----------------------------------------------------------------------------------------------
# Other common Fields used across most targets
# -----------------------------------------------------------------------------------------------


class Tags(StringSequenceField):
    alias = "tags"
    help = (
        "Arbitrary strings to describe a target.\n\nFor example, you may tag some test targets "
        "with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` "
        "to only run on targets with that tag."
    )


class DescriptionField(StringField):
    alias = "description"
    help = (
        "A human-readable description of the target.\n\nUse `./pants list --documented ::` to see "
        "all targets with descriptions."
    )


COMMON_TARGET_FIELDS = (Tags, DescriptionField)


# TODO: figure out what support looks like for this with the Target API. The expected value is an
#  Artifact, there is no common Artifact interface.
class ProvidesField(Field):
    """An `artifact` that describes how to represent this target to the outside world."""

    alias = "provides"
    default: ClassVar[Optional[Any]] = None
