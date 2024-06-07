# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections.abc
import dataclasses
import enum
import glob as glob_stdlib
import itertools
import logging
import os.path
import textwrap
import zlib
from abc import ABC, ABCMeta, abstractmethod
from collections import deque
from dataclasses import dataclass
from enum import Enum
from operator import attrgetter
from pathlib import PurePath
from typing import (
    AbstractSet,
    Any,
    Callable,
    ClassVar,
    Dict,
    Generic,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    get_type_hints,
)

from typing_extensions import Self, final

from pants.base.deprecated import warn_or_error
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs, assert_single_address
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    PathGlobs,
    Paths,
    Snapshot,
)
from pants.engine.internals.dep_rules import (
    DependencyRuleActionDeniedError,
    DependencyRuleApplication,
)
from pants.engine.internals.native_engine import NO_VALUE as NO_VALUE  # noqa: F401
from pants.engine.internals.native_engine import Field as Field  # noqa: F401
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.global_options import UnmatchedBuildFileGlobs
from pants.source.filespec import Filespec, FilespecMatcher
from pants.util.collections import ensure_list, ensure_str_list
from pants.util.dirutil import fast_relpath
from pants.util.docutil import bin_name, doc_url
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_classproperty, memoized_method, memoized_property
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import bullet_list, help_text, pluralize, softwrap

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Core Field abstractions
# -----------------------------------------------------------------------------------------------

# Type alias to express the intent that the type should be immutable and hashable. There's nothing
# to actually enforce this, outside of convention. Maybe we could develop a MyPy plugin?
ImmutableValue = Any


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

    address: Address

    @final
    def __new__(cls, raw_value: Optional[Any], address: Address) -> Self:
        obj = super().__new__(cls, raw_value, address)  # type: ignore[call-arg]
        # N.B.: We store the address here and not in the Field base class, because the memory usage
        # of storing this value in every field was shown to be excessive / lead to performance
        # issues.
        object.__setattr__(obj, "address", address)
        return obj

    def __repr__(self) -> str:
        params = [
            f"alias={self.alias!r}",
            f"address={self.address}",
            f"value={self.value!r}",
        ]
        if hasattr(self, "default"):
            params.append(f"default={self.default!r}")
        return f"{self.__class__}({', '.join(params)})"

    def __hash__(self) -> int:
        return hash((self.__class__, self.value, self.address))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, AsyncFieldMixin):
            return False
        return (
            self.__class__ == other.__class__
            and self.value == other.value
            and self.address == other.address
        )

    def __ne__(self, other: Any) -> bool:
        return not (self == other)


@union
@dataclass(frozen=True)
class FieldDefaultFactoryRequest:
    """Registers a dynamic default for a Field.

    See `FieldDefaults`.
    """

    field_type: ClassVar[type[Field]]


# TODO: Workaround for https://github.com/python/mypy/issues/5485, because we cannot directly use
# a Callable.
class FieldDefaultFactory(Protocol):
    def __call__(self, field: Field) -> Any:
        pass


@dataclass(frozen=True)
class FieldDefaultFactoryResult:
    """A wrapper for a function which computes the default value of a Field."""

    default_factory: FieldDefaultFactory


@dataclass(frozen=True)
class FieldDefaults:
    """Generic Field default values. To install a default, see `FieldDefaultFactoryRequest`.

    TODO: This is to work around the fact that Field value defaulting cannot have arbitrary
    subsystem requirements, and so e.g. `JvmResolveField` and `PythonResolveField` have methods
    which compute the true value of the field given a subsystem argument. Consumers need to
    be type aware, and `@rules` cannot have dynamic requirements.

    Additionally, `__defaults__` should mean that computed default Field values should become
    more rare: i.e. `JvmResolveField` and `PythonResolveField` could potentially move to
    hardcoded default values which users override with `__defaults__` if they'd like to change
    the default resolve names.

    See https://github.com/pantsbuild/pants/issues/12934 about potentially allowing unions
    (including Field registrations) to have `@rule_helper` methods, which would allow the
    computation of an AsyncField to directly require a subsystem. Since
    https://github.com/pantsbuild/pants/pull/17947 rules may use any methods as rule helpers without
    special decoration so this should now be possible to implement.
    """

    _factories: FrozenDict[type[Field], FieldDefaultFactory]

    @memoized_method
    def factory(self, field_type: type[Field]) -> FieldDefaultFactory:
        """Looks up a Field default factory in a subclass-aware way."""
        factory = self._factories.get(field_type, None)
        if factory is not None:
            return factory

        for ft, factory in self._factories.items():
            if issubclass(field_type, ft):
                return factory

        return lambda f: f.value

    def value_or_default(self, field: Field) -> Any:
        return (self.factory(type(field)))(field)


# -----------------------------------------------------------------------------------------------
# Core Target abstractions
# -----------------------------------------------------------------------------------------------


# NB: This TypeVar is what allows `Target.get()` to properly work with MyPy so that MyPy knows
# the precise Field returned.
_F = TypeVar("_F", bound=Field)


@dataclass(frozen=True)
class Target:
    """A Target represents an addressable set of metadata.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.
    """

    # Subclasses must define these
    alias: ClassVar[str]
    core_fields: ClassVar[Tuple[Type[Field], ...]]
    help: ClassVar[str | Callable[[], str]]

    removal_version: ClassVar[str | None] = None
    removal_hint: ClassVar[str | None] = None

    deprecated_alias: ClassVar[str | None] = None
    deprecated_alias_removal_version: ClassVar[str | None] = None

    # These get calculated in the constructor
    address: Address
    field_values: FrozenDict[type[Field], Field]
    residence_dir: str
    name_explicitly_set: bool
    description_of_origin: str

    @final
    def __init__(
        self,
        unhydrated_values: Mapping[str, Any],
        address: Address,
        # NB: `union_membership` is only optional to facilitate tests. In production, we should
        # always provide this parameter. This should be safe to do because production code should
        # rarely directly instantiate Targets and should instead use the engine to request them.
        union_membership: UnionMembership | None = None,
        *,
        name_explicitly_set: bool = True,
        residence_dir: str | None = None,
        ignore_unrecognized_fields: bool = False,
        description_of_origin: str | None = None,
    ) -> None:
        """Create a target.

        :param unhydrated_values: A mapping of field aliases to their raw values. Any left off
            fields will either use their default or error if required=True.
        :param address: How to uniquely identify this target.
        :param union_membership: Used to determine plugin fields. This must be set in production!
        :param residence_dir: Where this target "lives". If unspecified, will be the `spec_path`
            of the `address`, i.e. where the target was either explicitly defined or where its
            target generator was explicitly defined. Target generators can, however, set this to
            the directory where the generated target provides metadata for. For example, a
            file-based target like `python_source` should set this to the parent directory of
            its file. A file-less target like `go_third_party_package` should keep the default of
            `address.spec_path`. This field impacts how command line specs work, so that globs
            like `dir:` know whether to match the target or not.
        :param ignore_unrecognized_fields: Don't error if fields are not recognized. This is only
            intended for when Pants is bootstrapping itself.
        :param description_of_origin: Where this target was declared, such as a path to BUILD file
            and line number.
        """
        if self.removal_version and not address.is_generated_target:
            if not self.removal_hint:
                raise ValueError(
                    f"You specified `removal_version` for {self.__class__}, but not "
                    "the class property `removal_hint`."
                )
            warn_or_error(
                self.removal_version,
                entity=f"the {repr(self.alias)} target type",
                hint=f"Using the `{self.alias}` target type for {address}. {self.removal_hint}",
            )

        object.__setattr__(
            self, "residence_dir", residence_dir if residence_dir is not None else address.spec_path
        )
        object.__setattr__(self, "address", address)
        object.__setattr__(
            self, "description_of_origin", description_of_origin or self.residence_dir
        )
        object.__setattr__(self, "name_explicitly_set", name_explicitly_set)
        try:
            object.__setattr__(
                self,
                "field_values",
                self._calculate_field_values(
                    unhydrated_values,
                    address,
                    union_membership,
                    ignore_unrecognized_fields=ignore_unrecognized_fields,
                ),
            )

            self.validate()
        except Exception as e:
            raise InvalidTargetException(
                str(e), description_of_origin=self.description_of_origin
            ) from e

    @final
    def _calculate_field_values(
        self,
        unhydrated_values: Mapping[str, Any],
        address: Address,
        # See `__init__`.
        union_membership: UnionMembership | None,
        *,
        ignore_unrecognized_fields: bool,
    ) -> FrozenDict[type[Field], Field]:
        all_field_types = self.class_field_types(union_membership)
        field_values = {}
        aliases_to_field_types = self._get_field_aliases_to_field_types(all_field_types)

        for alias, value in unhydrated_values.items():
            if alias not in aliases_to_field_types:
                if ignore_unrecognized_fields:
                    continue
                valid_aliases = set(aliases_to_field_types.keys())
                if isinstance(self, TargetGenerator):
                    # Even though moved_fields don't live on the target generator, they are valid
                    # for users to specify. It's intentional that these are only used for
                    # `InvalidFieldException` and are not stored as normal fields with
                    # `aliases_to_field_types`.
                    for field_type in self.moved_fields:
                        valid_aliases.add(field_type.alias)
                        if field_type.deprecated_alias is not None:
                            valid_aliases.add(field_type.deprecated_alias)
                raise InvalidFieldException(
                    f"Unrecognized field `{alias}={value}` in target {address}. Valid fields for "
                    f"the target type `{self.alias}`: {sorted(valid_aliases)}.",
                )
            field_type = aliases_to_field_types[alias]
            field_values[field_type] = field_type(value, address)

        # For undefined fields, mark the raw value as missing.
        for field_type in all_field_types:
            if field_type in field_values:
                continue
            field_values[field_type] = field_type(NO_VALUE, address)
        return FrozenDict(
            sorted(
                field_values.items(),
                key=lambda field_type_to_val_pair: field_type_to_val_pair[0].alias,
            )
        )

    @final
    @classmethod
    def _get_field_aliases_to_field_types(
        cls, field_types: Iterable[type[Field]]
    ) -> dict[str, type[Field]]:
        aliases_to_field_types = {}
        for field_type in field_types:
            aliases_to_field_types[field_type.alias] = field_type
            if field_type.deprecated_alias is not None:
                aliases_to_field_types[field_type.deprecated_alias] = field_type
        return aliases_to_field_types

    @final
    @property
    def field_types(self) -> KeysView[Type[Field]]:
        return self.field_values.keys()

    @distinct_union_type_per_subclass
    class PluginField:
        pass

    def __repr__(self) -> str:
        fields = ", ".join(str(field) for field in self.field_values.values())
        return (
            f"{self.__class__}("
            f"address={self.address}, "
            f"alias={self.alias!r}, "
            f"residence_dir={self.residence_dir!r}, "
            f"origin={self.description_of_origin}, "
            f"{fields})"
        )

    def __str__(self) -> str:
        fields = ", ".join(str(field) for field in self.field_values.values())
        address = f"address=\"{self.address}\"{', ' if fields else ''}"
        return f"{self.alias}({address}{fields})"

    def __hash__(self) -> int:
        return hash((self.__class__, self.address, self.residence_dir, self.field_values))

    def __eq__(self, other: Union[Target, Any]) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return (self.__class__, self.address, self.residence_dir, self.field_values) == (
            other.__class__,
            other.address,
            other.residence_dir,
            other.field_values,
        )

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return self.address < other.address

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return self.address > other.address

    @classmethod
    @memoized_method
    def _find_plugin_fields(cls, union_membership: UnionMembership) -> tuple[type[Field], ...]:
        result: set[type[Field]] = set()
        classes = [cls]
        while classes:
            cls = classes.pop()
            classes.extend(cls.__bases__)
            if issubclass(cls, Target):
                result.update(cast("set[type[Field]]", union_membership.get(cls.PluginField)))

        return tuple(sorted(result, key=attrgetter("alias")))

    @final
    @classmethod
    def _find_registered_field_subclass(
        cls, requested_field: Type[_F], *, registered_fields: Iterable[Type[Field]]
    ) -> Optional[Type[_F]]:
        """Check if the Target has registered a subclass of the requested Field.

        This is necessary to allow targets to override the functionality of common fields. For
        example, you could subclass `Tags` to define `CustomTags` with a different default. At the
        same time, we still want to be able to call `tgt.get(Tags)`, in addition to
        `tgt.get(CustomTags)`.
        """
        subclass = next(
            (
                registered_field
                for registered_field in registered_fields
                if issubclass(registered_field, requested_field)
            ),
            None,
        )
        return subclass

    @final
    def _maybe_get(self, field: Type[_F]) -> Optional[_F]:
        result = self.field_values.get(field, None)
        if result is not None:
            return cast(_F, result)
        field_subclass = self._find_registered_field_subclass(
            field, registered_fields=self.field_values.keys()
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
        `InterpreterConstraints`, `SourcesField`, `EntryPoint`, etc. Usually, you will want to
        grab the `Field`'s inner value, e.g. `tgt.get(Compatibility).value`. (For async fields like
        `SourcesField`, you may need to hydrate the value.).

        This works with subclasses of `Field`. For example, if you subclass `Tags`
        to define a custom subclass `CustomTags`, both `tgt.get(Tags)` and
        `tgt.get(CustomTags)` will return the same `CustomTags` instance.

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
        cls, fields: Iterable[Type[Field]], *, registered_fields: AbstractSet[Type[Field]]
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

        This works with subclasses of `Field`. For example, if you subclass `Tags` to define a
        custom subclass `CustomTags`, both `tgt.has_field(Tags)` and
        `python_tgt.has_field(CustomTags)` will return True.
        """
        return self.has_fields([field])

    @final
    def has_fields(self, fields: Iterable[Type[Field]]) -> bool:
        """Check that this target has registered all of the requested fields.

        This works with subclasses of `Field`. For example, if you subclass `Tags` to define a
        custom subclass `CustomTags`, both `tgt.has_fields([Tags])` and
        `python_tgt.has_fields([CustomTags])` will return True.
        """
        return self._has_fields(fields, registered_fields=self.field_values.keys())

    @final
    @classmethod
    @memoized_method
    def class_field_types(
        cls, union_membership: UnionMembership | None
    ) -> FrozenOrderedSet[Type[Field]]:
        """Return all registered Fields belonging to this target type.

        You can also use the instance property `tgt.field_types` to avoid having to pass the
        parameter UnionMembership.
        """
        if union_membership is None:
            return FrozenOrderedSet(cls.core_fields)
        else:
            return FrozenOrderedSet((*cls.core_fields, *cls._find_plugin_fields(union_membership)))

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

    @classmethod
    def register_plugin_field(cls, field: Type[Field]) -> UnionRule:
        """Register a new field on the target type.

        In the `rules()` register.py entry-point, include
        `MyTarget.register_plugin_field(NewField)`. This will register `NewField` as a first-class
        citizen. Plugins can use this new field like any other.
        """
        return UnionRule(cls.PluginField, field)

    def validate(self) -> None:
        """Validate the target, such as checking for mutually exclusive fields.

        N.B.: The validation should only be of properties intrinsic to the associated files in any
        context. If the validation only makes sense for certain goals acting on targets; those
        validations should be done in the associated rules.
        """


@dataclass(frozen=True)
class WrappedTargetRequest:
    """Used with `WrappedTarget` to get the Target corresponding to an address.

    `description_of_origin` is used for error messages when the address does not actually exist. If
    you are confident this cannot happen, set the string to something like `<infallible>`.
    """

    address: Address
    description_of_origin: str = dataclasses.field(hash=False, compare=False)


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
    in this collection, e.g. some `FileTarget` and some `PythonTestTarget`.

    Often, you will want to filter out the relevant targets by looking at what fields they have
    registered, e.g.:

        valid_tgts = [tgt for tgt in tgts if tgt.has_fields([Compatibility, PythonSources])]

    You should not check the Target's actual type because this breaks custom target types;
    for example, prefer `tgt.has_field(PythonTestsSourcesField)` to
    `isinstance(tgt, PythonTestsTarget)`.
    """

    def expect_single(self) -> Target:
        assert_single_address([tgt.address for tgt in self])
        return self[0]


# This distinct type is necessary because of https://github.com/pantsbuild/pants/issues/14977.
#
# NB: We still proactively apply filtering inside `AddressSpecs` and `FilesystemSpecs`, which is
# earlier in the rule pipeline of `RawSpecs -> Addresses -> UnexpandedTargets -> Targets ->
# FilteredTargets`. That is necessary so that project-introspection goals like `list` which don't
# use `FilteredTargets` still have filtering applied.
class FilteredTargets(Collection[Target]):
    """A heterogeneous collection of Target instances that have been filtered with the global
    options `--tag` and `--exclude-target-regexp`.

    Outside of the extra filtering, this type is identical to `Targets`, including its handling of
    target generators.
    """

    def expect_single(self) -> Target:
        assert_single_address([tgt.address for tgt in self])
        return self[0]


class UnexpandedTargets(Collection[Target]):
    """Like `Targets`, but will not replace target generators with their generated targets (e.g.
    replace `python_sources` "BUILD targets" with generated `python_source` "file targets")."""

    def expect_single(self) -> Target:
        assert_single_address([tgt.address for tgt in self])
        return self[0]


class DepsTraversalBehavior(Enum):
    """The return value for ShouldTraverseDepsPredicate.

    NB: This only indicates whether to traverse the deps of a target;
    It does not control the inclusion of the target itself (though that
    might be added in the future). By the time the predicate is called,
    the target itself was already included.
    """

    INCLUDE = "include"
    EXCLUDE = "exclude"


@dataclass(frozen=True)
class ShouldTraverseDepsPredicate(metaclass=ABCMeta):
    """This callable determines whether to traverse through deps of a given Target + Field.

    This is a callable dataclass instead of a function to avoid issues with hashing closures.
    Only the id is used when hashing a function; any closure vars are NOT accounted for.

    NB: When subclassing a dataclass (like this one), you do not need to add the @dataclass
    decorator unless the subclass has additional fields. The @dataclass decorator only inspects
    the current class (not any parents from __mro__) to determine if any methods were explicitly
    defined. So, any typically-generated methods explicitly added on this parent class would NOT
    be inherited by @dataclass decorated subclasses. To avoid these issues, this parent class
    uses __post_init__ and relies on the generated __init__ and __hash__ methods.
    """

    # NB: This _callable field ensures that __call__ is included in the __hash__ method generated by @dataclass.
    # That is extremely important because two predicates with different implementations but the same data
    # (or no data) need to have different hashes and compare unequal.
    _callable: Callable[
        [Any, Target, Dependencies | SpecialCasedDependencies], DepsTraversalBehavior
    ] = dataclasses.field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "_callable", type(self).__call__)

    @abstractmethod
    def __call__(
        self, target: Target, field: Dependencies | SpecialCasedDependencies
    ) -> DepsTraversalBehavior:
        """This predicate decides when to INCLUDE or EXCLUDE the target's field's deps."""


class TraverseIfDependenciesField(ShouldTraverseDepsPredicate):
    """This is the default ShouldTraverseDepsPredicate implementation.

    This skips resolving dependencies for fields (like SpecialCasedDependencies) that are not
    subclasses of Dependencies.
    """

    def __call__(
        self, target: Target, field: Dependencies | SpecialCasedDependencies
    ) -> DepsTraversalBehavior:
        if isinstance(field, Dependencies):
            return DepsTraversalBehavior.INCLUDE
        return DepsTraversalBehavior.EXCLUDE


class AlwaysTraverseDeps(ShouldTraverseDepsPredicate):
    """A predicate to use when a request needs all deps.

    This includes deps from fields like SpecialCasedDependencies which are ignored in most cases.
    """

    def __call__(
        self, target: Target, field: Dependencies | SpecialCasedDependencies
    ) -> DepsTraversalBehavior:
        return DepsTraversalBehavior.INCLUDE


class CoarsenedTarget(EngineAwareParameter):
    def __init__(self, members: Iterable[Target], dependencies: Iterable[CoarsenedTarget]) -> None:
        """A set of Targets which cyclically reach one another, and are thus indivisible.

        Instances of this class form a structure-shared DAG, and so a hashcode is pre-computed for the
        recursive portion.

        :param members: The members of the cycle.
        :param dependencies: The deduped direct (not transitive) dependencies of all Targets in
            the cycle. Dependencies between members of the cycle are excluded.
        """
        self.members = FrozenOrderedSet(members)
        self.dependencies = FrozenOrderedSet(dependencies)
        self._hashcode = hash((self.members, self.dependencies))

    def debug_hint(self) -> str:
        return str(self)

    def metadata(self) -> Dict[str, Any]:
        return {"addresses": [t.address.spec for t in self.members]}

    @property
    def representative(self) -> Target:
        """A stable "representative" target in the cycle."""
        return next(iter(self.members))

    def bullet_list(self) -> str:
        """The addresses and type aliases of all members of the cycle."""
        return bullet_list(sorted(f"{t.address.spec}\t({type(t).alias})" for t in self.members))

    def closure(self, visited: Set[CoarsenedTarget] | None = None) -> Iterator[Target]:
        """All Targets reachable from this root."""
        return (t for ct in self.coarsened_closure(visited) for t in ct.members)

    def coarsened_closure(
        self, visited: Set[CoarsenedTarget] | None = None
    ) -> Iterator[CoarsenedTarget]:
        """All CoarsenedTargets reachable from this root."""

        visited = set() if visited is None else visited
        queue = deque([self])
        while queue:
            ct = queue.popleft()
            if ct in visited:
                continue
            visited.add(ct)
            yield ct
            queue.extend(ct.dependencies)

    def __hash__(self) -> int:
        return self._hashcode

    def _eq_helper(self, other: CoarsenedTarget, equal_items: set[tuple[int, int]]) -> bool:
        key = (id(self), id(other))
        if key[0] == key[1] or key in equal_items:
            return True

        is_eq = (
            self._hashcode == other._hashcode
            and self.members == other.members
            and len(self.dependencies) == len(other.dependencies)
            and all(
                l._eq_helper(r, equal_items) for l, r in zip(self.dependencies, other.dependencies)
            )
        )

        # NB: We only track equal items because any non-equal item will cause the entire
        # operation to shortcircuit.
        if is_eq:
            equal_items.add(key)
        return is_eq

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, CoarsenedTarget):
            return NotImplemented
        return self._eq_helper(other, set())

    def __str__(self) -> str:
        if len(self.members) > 1:
            others = len(self.members) - 1
            return f"{self.representative.address.spec} (and {others} more)"
        return self.representative.address.spec

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)})"


class CoarsenedTargets(Collection[CoarsenedTarget]):
    """The CoarsenedTarget roots of a transitive graph walk for some addresses.

    To collect all reachable CoarsenedTarget members, use `def closure`.
    """

    def by_address(self) -> dict[Address, CoarsenedTarget]:
        """Compute a mapping from Address to containing CoarsenedTarget."""
        return {t.address: ct for ct in self for t in ct.members}

    def closure(self) -> Iterator[Target]:
        """All Targets reachable from these CoarsenedTarget roots."""
        visited: Set[CoarsenedTarget] = set()
        return (t for root in self for t in root.closure(visited))

    def coarsened_closure(self) -> Iterator[CoarsenedTarget]:
        """All CoarsenedTargets reachable from these CoarsenedTarget roots."""
        visited: Set[CoarsenedTarget] = set()
        return (ct for root in self for ct in root.coarsened_closure(visited))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, CoarsenedTargets):
            return NotImplemented
        equal_items: set[tuple[int, int]] = set()
        return len(self) == len(other) and all(
            l._eq_helper(r, equal_items) for l, r in zip(self, other)
        )

    __hash__ = Tuple.__hash__


@dataclass(frozen=True)
class CoarsenedTargetsRequest:
    """A request to get CoarsenedTargets for input roots."""

    roots: Tuple[Address, ...]
    expanded_targets: bool
    should_traverse_deps_predicate: ShouldTraverseDepsPredicate

    def __init__(
        self,
        roots: Iterable[Address],
        *,
        expanded_targets: bool = False,
        should_traverse_deps_predicate: ShouldTraverseDepsPredicate = TraverseIfDependenciesField(),
    ) -> None:
        object.__setattr__(self, "roots", tuple(roots))
        object.__setattr__(self, "expanded_targets", expanded_targets)
        object.__setattr__(self, "should_traverse_deps_predicate", should_traverse_deps_predicate)


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


@dataclass(frozen=True)
class TransitiveTargetsRequest:
    """A request to get the transitive dependencies of the input roots.

    Resolve the transitive targets with `await Get(TransitiveTargets,
    TransitiveTargetsRequest([addr1, addr2]))`.
    """

    roots: Tuple[Address, ...]
    should_traverse_deps_predicate: ShouldTraverseDepsPredicate

    def __init__(
        self,
        roots: Iterable[Address],
        *,
        should_traverse_deps_predicate: ShouldTraverseDepsPredicate = TraverseIfDependenciesField(),
    ) -> None:
        object.__setattr__(self, "roots", tuple(roots))
        object.__setattr__(self, "should_traverse_deps_predicate", should_traverse_deps_predicate)


@dataclass(frozen=True)
class RegisteredTargetTypes:
    aliases_to_types: FrozenDict[str, Type[Target]]

    def __init__(self, aliases_to_types: Mapping[str, Type[Target]]) -> None:
        object.__setattr__(self, "aliases_to_types", FrozenDict(aliases_to_types))

    @classmethod
    def create(cls, target_types: Iterable[Type[Target]]) -> RegisteredTargetTypes:
        result = {}
        for target_type in sorted(target_types, key=lambda tt: tt.alias):
            result[target_type.alias] = target_type
            if target_type.deprecated_alias is not None:
                result[target_type.deprecated_alias] = target_type
        return cls(result)

    @property
    def aliases(self) -> FrozenOrderedSet[str]:
        return FrozenOrderedSet(self.aliases_to_types.keys())

    @property
    def types(self) -> FrozenOrderedSet[type[Target]]:
        return FrozenOrderedSet(self.aliases_to_types.values())


class AllTargets(Collection[Target]):
    """All targets in the project, but with target generators replaced by their generated targets,
    unlike `AllUnexpandedTargets`."""


class AllUnexpandedTargets(Collection[Target]):
    """All targets in the project, including generated targets.

    This should generally be avoided because it is relatively expensive to compute and is frequently
    invalidated, but it can be necessary for things like dependency inference to build a global
    mapping of imports to targets.
    """


# -----------------------------------------------------------------------------------------------
# Target generation
# -----------------------------------------------------------------------------------------------


class TargetGenerator(Target):
    """A Target type which generates other Targets via installed `@rule` logic.

    To act as a generator, a Target type should subclass this base class and install generation
    `@rule`s which consume a corresponding GenerateTargetsRequest subclass to produce
    GeneratedTargets.
    """

    # The generated Target class.
    #
    # If this is not provided, consider checking for the default values that applies to the target
    # types being generated manually. The applicable defaults are available on the `AddressFamily`
    # which you can get using:
    #
    #    family = await Get(AddressFamily, AddressFamilyDir(address.spec_path))
    #    target_defaults = family.defaults.get(MyTarget.alias, {})
    generated_target_cls: ClassVar[type[Target]]

    # Fields which have their values copied from the generator Target to the generated Target.
    #
    # Must be a subset of `core_fields`.
    #
    # Fields should be copied from the generator to the generated when their semantic meaning is
    # the same for both Target types, and when it is valuable for them to be introspected on
    # either the generator or generated target (such as by `peek`, or in `filter`).
    copied_fields: ClassVar[Tuple[Type[Field], ...]]

    # Fields which are specified to instances of the generator Target, but which are propagated
    # to generated Targets rather than being stored on the generator Target.
    #
    # Must be disjoint from `core_fields`.
    #
    # Only Fields which are moved to the generated Target are allowed to be `parametrize`d. But
    # it can also be the case that a Field only makes sense semantically when it is applied to
    # the generated Target (for example, for an individual file), and the generator Target is just
    # acting as a convenient place for them to be specified.
    moved_fields: ClassVar[Tuple[Type[Field], ...]]

    @distinct_union_type_per_subclass
    class MovedPluginField:
        """A plugin field that should be moved into the generated targets."""

    def validate(self) -> None:
        super().validate()

        copied_dependencies_field_types = [
            field_type.__name__
            for field_type in type(self).copied_fields
            if issubclass(field_type, Dependencies)
        ]
        if copied_dependencies_field_types:
            raise InvalidTargetException(
                f"Using a `Dependencies` field subclass ({copied_dependencies_field_types}) as a "
                "`TargetGenerator.copied_field`. `Dependencies` fields should be "
                "`TargetGenerator.moved_field`s, to avoid redundant graph edges."
            )

    @classmethod
    def register_plugin_field(cls, field: Type[Field], *, as_moved_field=False) -> UnionRule:
        if as_moved_field:
            return UnionRule(cls.MovedPluginField, field)
        else:
            return super().register_plugin_field(field)

    @classmethod
    @memoized_method
    def _find_plugin_fields(cls, union_membership: UnionMembership) -> tuple[type[Field], ...]:
        return (
            *cls._find_copied_plugin_fields(union_membership),
            *cls._find_moved_plugin_fields(union_membership),
        )

    @final
    @classmethod
    @memoized_method
    def _find_moved_plugin_fields(
        cls, union_membership: UnionMembership
    ) -> tuple[type[Field], ...]:
        result: set[type[Field]] = set()
        classes = [cls]
        while classes:
            cls = classes.pop()
            classes.extend(cls.__bases__)
            if issubclass(cls, TargetGenerator):
                result.update(cast("set[type[Field]]", union_membership.get(cls.MovedPluginField)))

        return tuple(result)

    @final
    @classmethod
    @memoized_method
    def _find_copied_plugin_fields(
        cls, union_membership: UnionMembership
    ) -> tuple[type[Field], ...]:
        return super()._find_plugin_fields(union_membership)


class TargetFilesGenerator(TargetGenerator):
    """A TargetGenerator which generates a Target per file matched by the generator.

    Unlike TargetGenerator, no additional `@rules` are required to be installed, because generation
    is implemented declaratively. But an optional `settings_request_cls` can be declared to
    dynamically control some settings of generation.
    """

    settings_request_cls: ClassVar[type[TargetFilesGeneratorSettingsRequest] | None] = None

    def validate(self) -> None:
        super().validate()

        if self.has_field(MultipleSourcesField) and not self[MultipleSourcesField].value:
            raise InvalidTargetException(
                f"The `{self.alias}` target generator at {self.address} has an empty "
                f"`{self[MultipleSourcesField].alias}` field; so it will not generate any targets. "
                "If its purpose is to act as an alias for its dependencies, then it should be "
                "declared as a `target(..)` generic target instead. If it is unused, then it "
                "should be removed."
            )


@union(in_scope_types=[EnvironmentName])
class TargetFilesGeneratorSettingsRequest:
    """An optional union to provide dynamic settings for a `TargetFilesGenerator`.

    See `TargetFilesGenerator`.
    """


@dataclass
class TargetFilesGeneratorSettings:
    # Set `add_dependencies_on_all_siblings` to True so that each file-level target depends on all
    # other generated targets from the target generator. This is useful if both are true:
    #
    # a) file-level targets usually need their siblings to be present to work. Most target types
    #   (Python, Java, Shell, etc) meet this, except for `files` and `resources` which have no
    #   concept of "imports"
    # b) dependency inference cannot infer dependencies on sibling files.
    #
    # Otherwise, set `add_dependencies_on_all_siblings` to `False` so that dependencies are
    # finer-grained.
    add_dependencies_on_all_siblings: bool = False


_TargetGenerator = TypeVar("_TargetGenerator", bound=TargetGenerator)


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class GenerateTargetsRequest(Generic[_TargetGenerator]):
    generate_from: ClassVar[type[_TargetGenerator]]  # type: ignore[misc]

    # The TargetGenerator instance to generate targets for.
    generator: _TargetGenerator
    # The base Address to generate for. Note that due to parametrization, this may not
    # always be the Address of the underlying target.
    template_address: Address
    # The `TargetGenerator.moved_field/copied_field` Field values that the generator
    # should generate targets with.
    template: Mapping[str, Any] = dataclasses.field(hash=False)
    # Per-generated-Target overrides, with an additional `template_address` to be applied. The
    # per-instance Address might not match the base `template_address` if parametrization was
    # applied within overrides.
    overrides: Mapping[str, Mapping[Address, Mapping[str, Any]]] = dataclasses.field(hash=False)

    def require_unparametrized_overrides(self) -> dict[str, Mapping[str, Any]]:
        """Flattens overrides for `GenerateTargetsRequest` impls which don't support `parametrize`.

        If `parametrize` has been used in overrides, this will raise an error indicating that that is
        not yet supported for the generator target type.

        TODO: https://github.com/pantsbuild/pants/issues/14430 covers porting implementations and
        removing this method.
        """
        if any(len(templates) != 1 for templates in self.overrides.values()):
            raise ValueError(
                f"Target generators of type `{self.generate_from.alias}` (defined at "
                f"`{self.generator.address}`) do not (yet) support use of the `parametrize(..)` "
                f"builtin in their `{OverridesField.alias}=` field."
            )
        return {name: next(iter(templates.values())) for name, templates in self.overrides.items()}


class GeneratedTargets(FrozenDict[Address, Target]):
    """A mapping of the address of generated targets to the targets themselves."""

    def __init__(self, generator: Target, generated_targets: Iterable[Target]) -> None:
        expected_spec_path = generator.address.spec_path
        expected_tgt_name = generator.address.target_name
        mapping = {}
        for tgt in sorted(generated_targets, key=lambda t: t.address):
            if tgt.address.spec_path != expected_spec_path:
                raise InvalidGeneratedTargetException(
                    "All generated targets must have the same `Address.spec_path` as their "
                    f"target generator. Expected {generator.address.spec_path}, but got "
                    f"{tgt.address.spec_path} for target generated from {generator.address}: {tgt}"
                    "\n\nConsider using `request.generator.address.create_generated()`."
                )
            if tgt.address.target_name != expected_tgt_name:
                raise InvalidGeneratedTargetException(
                    "All generated targets must have the same `Address.target_name` as their "
                    f"target generator. Expected {generator.address.target_name}, but got "
                    f"{tgt.address.target_name} for target generated from {generator.address}: "
                    f"{tgt}\n\n"
                    "Consider using `request.generator.address.create_generated()`."
                )
            if not tgt.address.is_generated_target:
                raise InvalidGeneratedTargetException(
                    "All generated targets must set `Address.generator_name` or "
                    "`Address.relative_file_path`. Invalid for target generated from "
                    f"{generator.address}: {tgt}\n\n"
                    "Consider using `request.generator.address.create_generated()`."
                )
            mapping[tgt.address] = tgt
        super().__init__(mapping)


class TargetTypesToGenerateTargetsRequests(
    FrozenDict[Type[TargetGenerator], Type[GenerateTargetsRequest]]
):
    def is_generator(self, tgt: Target) -> bool:
        """Does this target type generate other targets?"""
        return isinstance(tgt, TargetGenerator) and bool(self.request_for(type(tgt)))

    def request_for(self, tgt_cls: type[TargetGenerator]) -> type[GenerateTargetsRequest] | None:
        """Return the request type for the given Target, or None."""
        if issubclass(tgt_cls, TargetFilesGenerator):
            return self.get(TargetFilesGenerator)
        return self.get(tgt_cls)


def _generate_file_level_targets(
    generated_target_cls: type[Target],
    generator: Target,
    paths: Sequence[str],
    template_address: Address,
    template: Mapping[str, Any],
    overrides: Mapping[str, Mapping[Address, Mapping[str, Any]]],
    # NB: Should only ever be set to `None` in tests.
    union_membership: UnionMembership | None,
    *,
    add_dependencies_on_all_siblings: bool,
) -> GeneratedTargets:
    """Generate one new target for each path, using the same fields as the generator target except
    for the `sources` field only referring to the path and using a new address.

    Set `add_dependencies_on_all_siblings` to True so that each file-level target depends on all
    other generated targets from the target generator. This is useful if both are true:

        a) file-level targets usually need their siblings to be present to work. Most target types
          (Python, Java, Shell, etc) meet this, except for `files` and `resources` which have no
          concept of "imports"
        b) dependency inference cannot infer dependencies on sibling files.

    Otherwise, set `add_dependencies_on_all_siblings` to `False` so that dependencies are
    finer-grained.

    `overrides` allows changing the fields for particular targets. It expects the full file path
     as the key.
    """

    # Paths will have already been globbed, so they should be escaped. See
    # https://github.com/pantsbuild/pants/issues/15381.
    paths = [glob_stdlib.escape(path) for path in paths]

    normalized_overrides = dict(overrides or {})

    all_generated_items: list[tuple[Address, str, dict[str, Any]]] = []
    for fp in paths:
        relativized_fp = fast_relpath(fp, template_address.spec_path)

        generated_overrides = normalized_overrides.pop(fp, None)
        if generated_overrides is None:
            # No overrides apply.
            all_generated_items.append(
                (template_address.create_file(relativized_fp), fp, dict(template))
            )
        else:
            # At least one override applies. Generate a target per set of fields.
            all_generated_items.extend(
                (
                    overridden_address.create_file(relativized_fp),
                    fp,
                    {**template, **override_fields},
                )
                for overridden_address, override_fields in generated_overrides.items()
            )

    # TODO: Parametrization in overrides will result in some unusual internal dependencies when
    # `add_dependencies_on_all_siblings`. Similar to inference, `add_dependencies_on_all_siblings`
    # should probably be field value aware.
    all_generated_address_specs = (
        FrozenOrderedSet(addr.spec for addr, _, _ in all_generated_items)
        if add_dependencies_on_all_siblings
        else FrozenOrderedSet()
    )

    def gen_tgt(address: Address, full_fp: str, generated_target_fields: dict[str, Any]) -> Target:
        if add_dependencies_on_all_siblings:
            if union_membership and not generated_target_cls.class_has_field(
                Dependencies, union_membership
            ):
                raise AssertionError(
                    f"The {type(generator).__name__} target class generates "
                    f"{generated_target_cls.__name__} targets, which do not "
                    f"have a `{Dependencies.alias}` field, and thus cannot "
                    "`add_dependencies_on_all_siblings`."
                )
            original_deps = generated_target_fields.get(Dependencies.alias, ())
            generated_target_fields[Dependencies.alias] = tuple(original_deps) + tuple(
                all_generated_address_specs - {address.spec}
            )

        generated_target_fields[SingleSourceField.alias] = fast_relpath(full_fp, address.spec_path)
        return generated_target_cls(
            generated_target_fields,
            address,
            union_membership=union_membership,
            residence_dir=os.path.dirname(full_fp),
        )

    result = tuple(
        gen_tgt(address, full_fp, fields) for address, full_fp, fields in all_generated_items
    )

    if normalized_overrides:
        unused_relative_paths = sorted(
            fast_relpath(fp, template_address.spec_path) for fp in normalized_overrides
        )
        all_valid_relative_paths = sorted(
            cast(str, tgt.address.relative_file_path or tgt.address.generated_name)
            for tgt in result
        )
        raise InvalidFieldException(
            f"Unused file paths in the `overrides` field for {template_address}: "
            f"{sorted(unused_relative_paths)}"
            f"\n\nDid you mean one of these valid paths?\n\n"
            f"{all_valid_relative_paths}"
        )

    return GeneratedTargets(generator, result)


# -----------------------------------------------------------------------------------------------
# FieldSet
# -----------------------------------------------------------------------------------------------
def _get_field_set_fields_from_target(
    field_set: Type[FieldSet], target: Target
) -> Dict[str, Field]:
    return {
        dataclass_field_name: (
            target[field_cls] if field_cls in field_set.required_fields else target.get(field_cls)
        )
        for dataclass_field_name, field_cls in field_set.fields.items()
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

    You can optionally implement the classmethod `opt_out` so that targets have a
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

    This field set may then be created from a `Target` through the `is_applicable()` and `create()`
    class methods:

        field_sets = [
            FortranTestFieldSet.create(tgt) for tgt in targets
            if FortranTestFieldSet.is_applicable(tgt)
        ]

    FieldSets are consumed like any normal dataclass:

        print(field_set.address)
        print(field_set.sources)
    """

    required_fields: ClassVar[Tuple[Type[Field], ...]]

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
    ) -> Tuple[Type[Target], ...]:
        return tuple(
            tgt_type
            for tgt_type in target_types
            if tgt_type.class_has_fields(cls.required_fields, union_membership)
        )

    @final
    @classmethod
    def create(cls: Type[_FS], tgt: Target) -> _FS:
        return cls(address=tgt.address, **_get_field_set_fields_from_target(cls, tgt))

    @final
    @memoized_classproperty
    def fields(cls) -> FrozenDict[str, Type[Field]]:
        return FrozenDict(
            (
                (name, field_type)
                for name, field_type in get_type_hints(cls).items()
                if isinstance(field_type, type) and issubclass(field_type, Field)
            )
        )

    def debug_hint(self) -> str:
        return self.address.spec

    def metadata(self) -> Dict[str, Any]:
        return {"address": self.address.spec}

    def __repr__(self) -> str:
        # We use a short repr() because this often shows up in stack traces. We don't need any of
        # the field information because we can ask a user to send us their BUILD file.
        return f"{self.__class__.__name__}(address={self.address})"


@dataclass(frozen=True)
class TargetRootsToFieldSets(Generic[_FS]):
    mapping: FrozenDict[Target, Tuple[_FS, ...]]

    def __init__(self, mapping: Mapping[Target, Iterable[_FS]]) -> None:
        object.__setattr__(
            self,
            "mapping",
            FrozenDict({tgt: tuple(field_sets) for tgt, field_sets in mapping.items()}),
        )

    @memoized_property
    def field_sets(self) -> Tuple[_FS, ...]:
        return tuple(
            itertools.chain.from_iterable(
                field_sets_per_target for field_sets_per_target in self.mapping.values()
            )
        )

    @memoized_property
    def targets(self) -> Tuple[Target, ...]:
        return tuple(self.mapping.keys())


class NoApplicableTargetsBehavior(Enum):
    ignore = "ignore"
    warn = "warn"
    error = "error"


def parse_shard_spec(shard_spec: str, origin: str = "") -> Tuple[int, int]:
    def invalid():
        origin_str = f" from {origin}" if origin else ""
        return ValueError(
            f"Invalid shard specification {shard_spec}{origin_str}. Use a string of the form "
            '"k/N" where k and N are integers, and 0 <= k < N .'
        )

    if not shard_spec:
        return 0, -1
    shard_str, _, num_shards_str = shard_spec.partition("/")
    try:
        shard, num_shards = int(shard_str), int(num_shards_str)
    except ValueError:
        raise invalid()
    if shard < 0 or shard >= num_shards:
        raise invalid()
    return shard, num_shards


def get_shard(key: str, num_shards: int) -> int:
    # Note: hash() is not guaranteed to be stable across processes, and adler32 is not
    # well-distributed for small strings, so we use crc32. It's faster to compute than
    # a cryptographic hash, which would be overkill.
    return zlib.crc32(key.encode()) % num_shards


@dataclass(frozen=True)
class TargetRootsToFieldSetsRequest(Generic[_FS]):
    field_set_superclass: Type[_FS]
    goal_description: str
    no_applicable_targets_behavior: NoApplicableTargetsBehavior
    shard: int
    num_shards: int

    def __init__(
        self,
        field_set_superclass: Type[_FS],
        *,
        goal_description: str,
        no_applicable_targets_behavior: NoApplicableTargetsBehavior,
        shard: int = 0,
        num_shards: int = -1,
    ) -> None:
        object.__setattr__(self, "field_set_superclass", field_set_superclass)
        object.__setattr__(self, "goal_description", goal_description)
        object.__setattr__(self, "no_applicable_targets_behavior", no_applicable_targets_behavior)
        object.__setattr__(self, "shard", shard)
        object.__setattr__(self, "num_shards", num_shards)

    def is_in_shard(self, key: str) -> bool:
        return get_shard(key, self.num_shards) == self.shard


@dataclass(frozen=True)
class FieldSetsPerTarget(Generic[_FS]):
    # One tuple of FieldSet instances per input target.
    collection: Tuple[Tuple[_FS, ...], ...]

    def __init__(self, collection: Iterable[Iterable[_FS]]):
        object.__setattr__(self, "collection", tuple(tuple(iterable) for iterable in collection))

    @memoized_property
    def field_sets(self) -> Tuple[_FS, ...]:
        return tuple(itertools.chain.from_iterable(self.collection))


@dataclass(frozen=True)
class FieldSetsPerTargetRequest(Generic[_FS]):
    field_set_superclass: Type[_FS]
    targets: Tuple[Target, ...]

    def __init__(self, field_set_superclass: Type[_FS], targets: Iterable[Target]):
        object.__setattr__(self, "field_set_superclass", field_set_superclass)
        object.__setattr__(self, "targets", tuple(targets))


# -----------------------------------------------------------------------------------------------
# Exception messages
# -----------------------------------------------------------------------------------------------


class InvalidTargetException(Exception):
    """Use when there's an issue with the target, e.g. mutually exclusive fields set.

    Suggested template:

         f"The `{alias!r}` target {address} ..."
    """

    def __init__(self, message: Any, *, description_of_origin: str | None = None) -> None:
        self.description_of_origin = description_of_origin
        super().__init__(message)

    def __str__(self) -> str:
        if not self.description_of_origin:
            return super().__str__()
        return f"{self.description_of_origin}: {super().__str__()}"

    def __repr__(self) -> str:
        if not self.description_of_origin:
            return super().__repr__()
        return f"{self.description_of_origin}: {super().__repr__()}"


class InvalidGeneratedTargetException(InvalidTargetException):
    pass


class InvalidFieldException(Exception):
    """Use when there's an issue with a particular field.

    Suggested template:

         f"The {alias!r} field in target {address} must ..., but ..."
    """

    def __init__(self, message: Any, *, description_of_origin: str | None = None) -> None:
        self.description_of_origin = description_of_origin
        super().__init__(message)

    def __str__(self) -> str:
        if not self.description_of_origin:
            return super().__str__()
        return f"{self.description_of_origin}: {super().__str__()}"

    def __repr__(self) -> str:
        if not self.description_of_origin:
            return super().__repr__()
        return f"{self.description_of_origin}: {super().__repr__()}"


class InvalidFieldTypeException(InvalidFieldException):
    """This is used to ensure that the field's value conforms with the expected type for the field,
    e.g. `a boolean` or `a string` or `an iterable of strings and integers`."""

    def __init__(
        self,
        address: Address,
        field_alias: str,
        raw_value: Optional[Any],
        *,
        expected_type: str,
        description_of_origin: str | None = None,
    ) -> None:
        raw_type = f"with type `{type(raw_value).__name__}`"
        super().__init__(
            f"The {repr(field_alias)} field in target {address} must be {expected_type}, but was "
            f"`{repr(raw_value)}` {raw_type}.",
            description_of_origin=description_of_origin,
        )


class RequiredFieldMissingException(InvalidFieldException):
    def __init__(
        self, address: Address, field_alias: str, *, description_of_origin: str | None = None
    ) -> None:
        super().__init__(
            f"The {repr(field_alias)} field in target {address} must be defined.",
            description_of_origin=description_of_origin,
        )


class InvalidFieldChoiceException(InvalidFieldException):
    def __init__(
        self,
        address: Address,
        field_alias: str,
        raw_value: Optional[Any],
        *,
        valid_choices: Iterable[Any],
        description_of_origin: str | None = None,
    ) -> None:
        super().__init__(
            f"Values for the {repr(field_alias)} field in target {address} must be one of "
            f"{sorted(valid_choices)}, but {repr(raw_value)} was provided.",
            description_of_origin=description_of_origin,
        )


class UnrecognizedTargetTypeException(InvalidTargetException):
    def __init__(
        self,
        target_type: str,
        registered_target_types: RegisteredTargetTypes,
        address: Address | None = None,
        description_of_origin: str | None = None,
    ) -> None:
        for_address = f" for address {address}" if address else ""
        super().__init__(
            softwrap(
                f"""
                Target type {target_type!r} is not registered{for_address}.

                All valid target types: {sorted(registered_target_types.aliases)}

                (If {target_type!r} is a custom target type, refer to
                {doc_url('docs/writing-plugins/the-target-api/concepts')} for getting it registered with Pants.)

                """
            ),
            description_of_origin=description_of_origin,
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
                cls, raw_value: Optional[MyPluginObject], address: Address
            ) -> Optional[MyPluginObject]:
                return super().compute_value(raw_value, address=address)
    """

    expected_type: ClassVar[Type[T]]  # type: ignore[misc]
    expected_type_description: ClassVar[str]
    value: Optional[T]
    default: ClassVar[Optional[T]] = None  # type: ignore[misc]

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


class ValidNumbers(Enum):
    """What range of numbers are allowed for IntField and FloatField."""

    positive_only = enum.auto()
    positive_and_zero = enum.auto()
    all = enum.auto()

    def validate(self, num: float | int | None, alias: str, address: Address) -> None:
        if num is None or self == self.all:  # type: ignore[comparison-overlap]
            return
        if self == self.positive_and_zero:  # type: ignore[comparison-overlap]
            if num < 0:
                raise InvalidFieldException(
                    f"The {repr(alias)} field in target {address} must be greater than or equal to "
                    f"zero, but was set to `{num}`."
                )
            return
        if num <= 0:
            raise InvalidFieldException(
                f"The {repr(alias)} field in target {address} must be greater than zero, but was "
                f"set to `{num}`."
            )


class IntField(ScalarField[int]):
    expected_type = int
    expected_type_description = "an integer"
    valid_numbers: ClassVar[ValidNumbers] = ValidNumbers.all

    @classmethod
    def compute_value(cls, raw_value: Optional[int], address: Address) -> Optional[int]:
        value_or_default = super().compute_value(raw_value, address)
        cls.valid_numbers.validate(value_or_default, cls.alias, address)
        return value_or_default


class FloatField(ScalarField[float]):
    expected_type = float
    expected_type_description = "a float"
    valid_numbers: ClassVar[ValidNumbers] = ValidNumbers.all

    @classmethod
    def compute_value(cls, raw_value: Optional[float], address: Address) -> Optional[float]:
        value_or_default = super().compute_value(raw_value, address)
        cls.valid_numbers.validate(value_or_default, cls.alias, address)
        return value_or_default


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
            _validate_choices(
                address, cls.alias, [value_or_default], valid_choices=cls.valid_choices
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
                cls, raw_value: Optional[Iterable[MyPluginObject]], address: Address
            ) -> Optional[Tuple[MyPluginObject, ...]]:
                return super().compute_value(raw_value, address=address)
    """

    expected_element_type: ClassVar[Type]
    expected_type_description: ClassVar[str]
    value: Optional[Tuple[T, ...]]
    default: ClassVar[Optional[Tuple[T, ...]]] = None  # type: ignore[misc]

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
    valid_choices: ClassVar[Optional[Union[Type[Enum], Tuple[str, ...]]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Optional[Tuple[str, ...]]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default and cls.valid_choices is not None:
            _validate_choices(address, cls.alias, value_or_default, valid_choices=cls.valid_choices)
        return value_or_default


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


class ListOfDictStringToStringField(Field):
    value: Optional[Tuple[FrozenDict[str, str]]]
    default: ClassVar[Optional[list[FrozenDict[str, str]]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[list[Dict[str, str]]], address: Address
    ) -> Optional[Tuple[FrozenDict[str, str], ...]]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default is None:
            return None
        invalid_type_exception = InvalidFieldTypeException(
            address,
            cls.alias,
            raw_value,
            expected_type="a list of dictionaries (or a single dictionary) of string -> string",
        )

        # Also support passing in a single dictionary by wrapping it
        if not isinstance(value_or_default, list):
            value_or_default = [value_or_default]

        result_lst: list[FrozenDict[str, str]] = []
        for item in value_or_default:
            if not isinstance(item, collections.abc.Mapping):
                raise invalid_type_exception
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in item.items()):
                raise invalid_type_exception
            result_lst.append(FrozenDict(item))

        return tuple(result_lst)


class NestedDictStringToStringField(Field):
    value: Optional[FrozenDict[str, FrozenDict[str, str]]]
    default: ClassVar[Optional[FrozenDict[str, FrozenDict[str, str]]]] = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, Dict[str, str]]], address: Address
    ) -> Optional[FrozenDict[str, FrozenDict[str, str]]]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default is None:
            return None
        invalid_type_exception = InvalidFieldTypeException(
            address,
            cls.alias,
            raw_value,
            expected_type="dict[str, dict[str, str]]",
        )
        if not isinstance(value_or_default, collections.abc.Mapping):
            raise invalid_type_exception
        for key, nested_value in value_or_default.items():
            if not isinstance(key, str) or not isinstance(nested_value, collections.abc.Mapping):
                raise invalid_type_exception
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in nested_value.items()):
                raise invalid_type_exception
        return FrozenDict(
            {key: FrozenDict(nested_value) for key, nested_value in value_or_default.items()}
        )


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


def _validate_choices(
    address: Address,
    field_alias: str,
    values: Iterable[Any],
    *,
    valid_choices: Union[Type[Enum], Tuple[Any, ...]],
) -> None:
    _valid_choices = set(
        valid_choices
        if isinstance(valid_choices, tuple)
        else (choice.value for choice in valid_choices)
    )
    for choice in values:
        if choice not in _valid_choices:
            raise InvalidFieldChoiceException(
                address, field_alias, choice, valid_choices=_valid_choices
            )


# -----------------------------------------------------------------------------------------------
# Sources and codegen
# -----------------------------------------------------------------------------------------------


class SourcesField(AsyncFieldMixin, Field):
    """A field for the sources that a target owns.

    When defining a new sources field, you should subclass `MultipleSourcesField` or
    `SingleSourceField`, which set up the field's `alias` and data type / parsing. However, you
    should use `tgt.get(SourcesField)` when you need to operate on all sources types, such as
    with `HydrateSourcesRequest`, so that both subclasses work.

    Subclasses may set the following class properties:

    - `expected_file_extensions` -- A tuple of strings containing the expected file extensions for
        source files. The default is no expected file extensions.
    - `expected_num_files` -- An integer or range stating the expected total number of source
        files. The default is no limit on the number of source files.
    - `uses_source_roots` -- Whether the concept of "source root" pertains to the source files
        referenced by this field.
    - `default` -- A default value for this field.
    - `default_glob_match_error_behavior` -- Advanced option, should very rarely be used. Override
        glob match error behavior when using the default value. If setting this to
        `GlobMatchErrorBehavior.ignore`, make sure you have other validation in place in case the
        default glob doesn't match any files, if required, to alert the user appropriately.
    """

    expected_file_extensions: ClassVar[tuple[str, ...] | None] = None
    expected_num_files: ClassVar[int | range | None] = None
    uses_source_roots: ClassVar[bool] = True

    default: ClassVar[ImmutableValue] = None
    default_glob_match_error_behavior: ClassVar[GlobMatchErrorBehavior | None] = None

    @property
    def globs(self) -> tuple[str, ...]:
        """The raw globs, relative to the BUILD file."""

        # NB: We give a default implementation because it's common to use
        # `tgt.get(SourcesField)`, and that must not error. But, subclasses need to
        # implement this for the field to be useful (they should subclass `MultipleSourcesField`
        # and `SingleSourceField`).
        return ()

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
                fp for fp in files if PurePath(fp).suffix not in self.expected_file_extensions
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
                    "\n\nMaybe create a `resource`/`resources` or `file`/`files` target and "
                    "include it in the `dependencies` field?"
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
    @classmethod
    def can_generate(
        cls, output_type: type[SourcesField], union_membership: UnionMembership
    ) -> bool:
        """Can this field be used to generate the output_type?

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

    @final
    def path_globs(self, unmatched_build_file_globs: UnmatchedBuildFileGlobs) -> PathGlobs:
        if not self.globs:
            return PathGlobs([])

        # SingleSourceField has str as default type.
        default_globs = (
            [self.default] if self.default and isinstance(self.default, str) else self.default
        )

        using_default_globs = default_globs and (set(self.globs) == set(default_globs)) or False

        # Use fields default error behavior if defined, if we use default globs else the provided
        # error behavior.
        error_behavior = (
            unmatched_build_file_globs.error_behavior
            if not using_default_globs or self.default_glob_match_error_behavior is None
            else self.default_glob_match_error_behavior
        )

        return PathGlobs(
            (self._prefix_glob_with_address(glob) for glob in self.globs),
            conjunction=GlobExpansionConjunction.any_match,
            glob_match_error_behavior=error_behavior,
            description_of_origin=(
                f"{self.address}'s `{self.alias}` field"
                if error_behavior != GlobMatchErrorBehavior.ignore
                else None
            ),
        )

    @memoized_property
    def filespec(self) -> Filespec:
        """The original globs, returned in the Filespec dict format.

        The globs will be relativized to the build root.
        """
        includes = []
        excludes = []
        for glob in self.globs:
            if glob.startswith("!"):
                excludes.append(os.path.join(self.address.spec_path, glob[1:]))
            else:
                includes.append(os.path.join(self.address.spec_path, glob))
        result: Filespec = {"includes": includes}
        if excludes:
            result["excludes"] = excludes
        return result

    @memoized_property
    def filespec_matcher(self) -> FilespecMatcher:
        # Note: memoized because parsing the globs is expensive:
        # https://github.com/pantsbuild/pants/issues/16122
        return FilespecMatcher(self.filespec["includes"], self.filespec.get("excludes", []))


class MultipleSourcesField(SourcesField, StringSequenceField):
    """The `sources: list[str]` field.

    See the docstring for `SourcesField` for some class properties you can set, such as
    `expected_file_extensions`.

    When you need to get the sources for all targets, use `tgt.get(SourcesField)` rather than
    `tgt.get(MultipleSourcesField)`.
    """

    alias = "sources"

    ban_subdirectories: ClassVar[bool] = False

    @property
    def globs(self) -> tuple[str, ...]:
        return self.value or ()

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Optional[Tuple[str, ...]]:
        value = super().compute_value(raw_value, address)
        invalid_globs = [glob for glob in (value or ()) if glob.startswith("../") or "/../" in glob]
        if invalid_globs:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The {repr(cls.alias)} field in target {address} must not have globs with the
                    pattern `../` because targets can only have sources in the current directory
                    or subdirectories. It was set to: {sorted(value or ())}
                    """
                )
            )
        if cls.ban_subdirectories:
            invalid_globs = [glob for glob in (value or ()) if "**" in glob or os.path.sep in glob]
            if invalid_globs:
                raise InvalidFieldException(
                    softwrap(
                        f"""
                        The {repr(cls.alias)} field in target {address} must only have globs for
                        the target's directory, i.e. it cannot include values with `**` or
                        `{os.path.sep}`. It was set to: {sorted(value or ())}
                        """
                    )
                )
        return value


class OptionalSingleSourceField(SourcesField, StringField):
    """The `source: str` field.

    See the docstring for `SourcesField` for some class properties you can set, such as
    `expected_file_extensions`.

    When you need to get the sources for all targets, use `tgt.get(SourcesField)` rather than
    `tgt.get(OptionalSingleSourceField)`.

    Use `SingleSourceField` if the source must exist.
    """

    alias = "source"
    help = help_text(
        """
        A single file that belongs to this target.

        Path is relative to the BUILD file's directory, e.g. `source='example.ext'`.
        """
    )
    required = False
    default: ClassVar[str | None] = None
    expected_num_files: ClassVar[int | range] = range(0, 2)

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default is None:
            return None
        if value_or_default.startswith("../") or "/../" in value_or_default:
            raise InvalidFieldException(
                softwrap(
                    f"""\
                    The {repr(cls.alias)} field in target {address} should not include `../`
                    patterns because targets can only have sources in the current directory or
                    subdirectories. It was set to {value_or_default}. Instead, use a normalized
                    literal file path (relative to the BUILD file).
                    """
                )
            )
        if "*" in value_or_default:
            raise InvalidFieldException(
                softwrap(
                    f"""\
                    The {repr(cls.alias)} field in target {address} should not include `*` globs,
                    but was set to {value_or_default}. Instead, use a literal file path (relative
                    to the BUILD file).
                    """
                )
            )
        if value_or_default.startswith("!"):
            raise InvalidFieldException(
                softwrap(
                    f"""\
                    The {repr(cls.alias)} field in target {address} should not start with `!`,
                    which is usually used in the `sources` field to exclude certain files. Instead,
                    use a literal file path (relative to the BUILD file).
                    """
                )
            )
        return value_or_default

    @property
    def file_path(self) -> str | None:
        """The path to the file, relative to the build root.

        This works without hydration because we validate that `*` globs and `!` ignores are not
        used. However, consider still hydrating so that you verify the source file actually exists.

        The return type is optional because it's possible to have 0-1 files.
        """
        if self.value is None:
            return None
        return os.path.join(self.address.spec_path, self.value)

    @property
    def globs(self) -> tuple[str, ...]:
        if self.value is None:
            return ()
        return (self.value,)


class SingleSourceField(OptionalSingleSourceField):
    """The `source: str` field.

    Unlike `OptionalSingleSourceField`, the `.value` must be defined, whether by setting the
    `default` or making the field `required`.

    See the docstring for `SourcesField` for some class properties you can set, such as
    `expected_file_extensions`.

    When you need to get the sources for all targets, use `tgt.get(SourcesField)` rather than
    `tgt.get(SingleSourceField)`.
    """

    required = True
    expected_num_files = 1
    value: str

    @property
    def file_path(self) -> str:
        result = super().file_path
        assert result is not None
        return result


@dataclass(frozen=True)
class HydrateSourcesRequest(EngineAwareParameter):
    field: SourcesField
    for_sources_types: tuple[type[SourcesField], ...]
    enable_codegen: bool

    def __init__(
        self,
        field: SourcesField,
        *,
        for_sources_types: Iterable[type[SourcesField]] = (SourcesField,),
        enable_codegen: bool = False,
    ) -> None:
        """Convert raw sources globs into an instance of HydratedSources.

        If you only want to handle certain SourcesFields, such as only PythonSources, set
        `for_sources_types`. Any invalid sources will return a `HydratedSources` instance with an
        empty snapshot and `sources_type = None`.

        If `enable_codegen` is set to `True`, any codegen sources will try to be converted to one
        of the `for_sources_types`.
        """
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "for_sources_types", tuple(for_sources_types))
        object.__setattr__(self, "enable_codegen", enable_codegen)

        self.__post_init__()

    def __post_init__(self) -> None:
        if self.enable_codegen and self.for_sources_types == (SourcesField,):
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
    value is None, then the input `SourcesField` was not one of the expected types; or, when codegen
    was enabled in the request, there was no valid code generator to generate the requested language
    from the original input. This property allows for switching on the result, e.g. handling
    hydrated files() sources differently than hydrated Python sources.
    """

    snapshot: Snapshot
    filespec: Filespec
    sources_type: type[SourcesField] | None


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class GenerateSourcesRequest:
    """A request to go from protocol sources -> a particular language.

    This should be subclassed for each distinct codegen implementation. The subclasses must define
    the class properties `input` and `output`. The subclass must also be registered via
    `UnionRule(GenerateSourcesRequest, GenerateFortranFromAvroRequest)`, for example.

    The rule to actually implement the codegen should take the subclass as input, and it must
    return `GeneratedSources`.

    The `exportable` attribute disables the use of this codegen by the `export-codegen` goal when
    set to False.

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

    input: ClassVar[type[SourcesField]]
    output: ClassVar[type[SourcesField]]

    exportable: ClassVar[bool] = True


@dataclass(frozen=True)
class GeneratedSources:
    snapshot: Snapshot


class SourcesPaths(Paths):
    """The resolved file names of the `source`/`sources` field.

    This does not consider codegen, and only captures the files from the field.
    """


@dataclass(frozen=True)
class SourcesPathsRequest(EngineAwareParameter):
    """A request to resolve the file names of the `source`/`sources` field.

    Use via `Get(SourcesPaths, SourcesPathRequest(tgt.get(SourcesField))`.

    This is faster than `Get(HydratedSources, HydrateSourcesRequest)` because it does not snapshot
    the files and it only resolves the file names.

    This does not consider codegen, and only captures the files from the field. Use
    `HydrateSourcesRequest` to use codegen.
    """

    field: SourcesField

    def debug_hint(self) -> str:
        return self.field.address.spec


def targets_with_sources_types(
    sources_types: Iterable[type[SourcesField]],
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
            or tgt.get(SourcesField).can_generate(sources_type, union_membership)
            for sources_type in sources_types
        )
    )


# -----------------------------------------------------------------------------------------------
# `Dependencies` field
# -----------------------------------------------------------------------------------------------


class Dependencies(StringSequenceField, AsyncFieldMixin):
    """The dependencies field.

    To resolve all dependencies—including the results of dependency inference—use either `await
    Get(Addresses, DependenciesRequest(tgt[Dependencies])` or `await Get(Targets,
    DependenciesRequest(tgt[Dependencies])`.
    """

    alias = "dependencies"
    help = help_text(
        f"""
        Addresses to other targets that this target depends on, e.g.
        `['helloworld/subdir:lib', 'helloworld/main.py:lib', '3rdparty:reqs#django']`.

        This augments any dependencies inferred by Pants, such as by analyzing your imports. Use
        `{bin_name()} dependencies` or `{bin_name()} peek` on this target to get the final
        result.

        See {doc_url('docs/using-pants/key-concepts/targets-and-build-files')} for more about how addresses are formed, including for generated
        targets. You can also run `{bin_name()} list ::` to find all addresses in your project, or
        `{bin_name()} list dir` to find all addresses defined in that directory.

        If the target is in the same BUILD file, you can leave off the BUILD file path, e.g.
        `:tgt` instead of `helloworld/subdir:tgt`. For generated first-party addresses, use
        `./` for the file path, e.g. `./main.py:tgt`; for all other generated targets,
        use `:tgt#generated_name`.

        You may exclude dependencies by prefixing with `!`, e.g.
        `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are intended for false positives
        with dependency inference; otherwise, simply leave off the dependency from the BUILD file.
        """
    )
    supports_transitive_excludes = False

    @memoized_property
    def unevaluated_transitive_excludes(self) -> UnparsedAddressInputs:
        val = (
            (v[2:] for v in self.value if v.startswith("!!"))
            if self.supports_transitive_excludes and self.value
            else ()
        )
        return UnparsedAddressInputs(
            val,
            owning_address=self.address,
            description_of_origin=f"the `{self.alias}` field from the target {self.address}",
        )


@dataclass(frozen=True)
class DependenciesRequest(EngineAwareParameter):
    field: Dependencies
    should_traverse_deps_predicate: ShouldTraverseDepsPredicate = TraverseIfDependenciesField()

    def debug_hint(self) -> str:
        return self.field.address.spec


# NB: ExplicitlyProvidedDependenciesRequest does not have a predicate unlike DependenciesRequest.
@dataclass(frozen=True)
class ExplicitlyProvidedDependenciesRequest(EngineAwareParameter):
    field: Dependencies

    def debug_hint(self) -> str:
        return self.field.address.spec


@dataclass(frozen=True)
class ExplicitlyProvidedDependencies:
    """The literal addresses from a BUILD file `dependencies` field.

    Almost always, you should use `await Get(Addresses, DependenciesRequest)` instead, which will
    consider dependency inference and apply ignores. However, this type can be
    useful particularly within inference rules to see if a user already explicitly
    provided a dependency.

    Resolve using `await Get(ExplicitlyProvidedDependencies, DependenciesRequest)`.

    Note that the `includes` are not filtered based on the `ignores`: this type preserves exactly
    what was in the BUILD file.
    """

    address: Address
    includes: FrozenOrderedSet[Address]
    ignores: FrozenOrderedSet[Address]

    @memoized_method
    def any_are_covered_by_includes(self, addresses: Iterable[Address]) -> bool:
        """Return True if every address is in the explicitly provided includes.

        Note that if the input addresses are generated targets, they will still be marked as covered
        if their original target generator is in the explicitly provided includes.
        """
        return any(
            addr in self.includes or addr.maybe_convert_to_target_generator() in self.includes
            for addr in addresses
        )

    @memoized_method
    def remaining_after_disambiguation(
        self, addresses: Iterable[Address], owners_must_be_ancestors: bool
    ) -> frozenset[Address]:
        """All addresses that remain after ineligible candidates are discarded.

        Candidates are removed if they appear as ignores (`!` and `!!)` in the `dependencies`
        field. Note that if the input addresses are generated targets, they will still be marked as
        covered if their original target generator is in the explicitly provided ignores.

        Candidates are also removed if `owners_must_be_ancestors` is True and the targets are not
        ancestors, e.g. `root2:tgt` is not a valid candidate for something defined in `root1`.
        """
        original_addr_path = PurePath(self.address.spec_path)

        def is_valid(addr: Address) -> bool:
            is_ignored = (
                addr in self.ignores or addr.maybe_convert_to_target_generator() in self.ignores
            )
            if owners_must_be_ancestors is False:
                return not is_ignored
            # NB: `PurePath.is_relative_to()` was not added until Python 3.9. This emulates it.
            try:
                original_addr_path.relative_to(addr.spec_path)
                return not is_ignored
            except ValueError:
                return False

        return frozenset(filter(is_valid, addresses))

    def maybe_warn_of_ambiguous_dependency_inference(
        self,
        ambiguous_addresses: Iterable[Address],
        original_address: Address,
        *,
        context: str,
        import_reference: str,
        owners_must_be_ancestors: bool = False,
    ) -> None:
        """If the module is ambiguous and the user did not disambiguate, warn that dependency
        inference will not be used.

        Disambiguation usually happens by using ignores in the `dependencies` field with `!` and
        `!!`. If `owners_must_be_ancestors` is True, any addresses which are not ancestors of the
        target in question will also be ignored.
        """
        if not ambiguous_addresses or self.any_are_covered_by_includes(ambiguous_addresses):
            return
        remaining = self.remaining_after_disambiguation(
            ambiguous_addresses, owners_must_be_ancestors=owners_must_be_ancestors
        )
        if len(remaining) <= 1:
            return
        logger.warning(
            f"{context}, but Pants cannot safely infer a dependency because more than one target "
            f"owns this {import_reference}, so it is ambiguous which to use: "
            f"{sorted(addr.spec for addr in remaining)}."
            f"\n\nPlease explicitly include the dependency you want in the `dependencies` "
            f"field of {original_address}, or ignore the ones you do not want by prefixing "
            f"with `!` or `!!` so that one or no targets are left."
            f"\n\nAlternatively, you can remove the ambiguity by deleting/changing some of the "
            f"targets so that only 1 target owns this {import_reference}. Refer to "
            f"{doc_url('docs/using-pants/troubleshooting-common-issues#import-errors-and-missing-dependencies')}."
        )

    def disambiguated(
        self, ambiguous_addresses: Iterable[Address], owners_must_be_ancestors: bool = False
    ) -> Address | None:
        """If exactly one of the input addresses remains after disambiguation, return it.

        Disambiguation usually happens by using ignores in the `dependencies` field with `!` and
        `!!`. If `owners_must_be_ancestors` is True, any addresses which are not ancestors of the
        target in question will also be ignored.
        """
        if not ambiguous_addresses or self.any_are_covered_by_includes(ambiguous_addresses):
            return None
        remaining_after_ignores = self.remaining_after_disambiguation(
            ambiguous_addresses, owners_must_be_ancestors=owners_must_be_ancestors
        )
        return list(remaining_after_ignores)[0] if len(remaining_after_ignores) == 1 else None


FS = TypeVar("FS", bound="FieldSet")


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class InferDependenciesRequest(Generic[FS], EngineAwareParameter):
    """A request to infer dependencies by analyzing source files.

    To set up a new inference implementation, subclass this class. Set the class property
    `infer_from` to the FieldSet subclass you are able to infer from. This will cause the FieldSet
    class, and any subclass, to use your inference implementation.

    Note that there cannot be more than one implementation for a particular `FieldSet` class.

    Register this subclass with `UnionRule(InferDependenciesRequest, InferFortranDependencies)`, for example.

    Then, create a rule that takes the subclass as a parameter and returns `InferredDependencies`.

    For example:

        class InferFortranDependencies(InferDependenciesRequest):
            infer_from = FortranDependenciesInferenceFieldSet

        @rule
        def infer_fortran_dependencies(request: InferFortranDependencies) -> InferredDependencies:
            hydrated_sources = await Get(HydratedSources, HydrateSources(request.sources))
            ...
            return InferredDependencies(...)

        def rules():
            return [
                infer_fortran_dependencies,
                UnionRule(InferDependenciesRequest, InferFortranDependencies),
            ]
    """

    infer_from: ClassVar[Type[FS]]  # type: ignore[misc]

    field_set: FS


@dataclass(frozen=True)
class InferredDependencies:
    include: FrozenOrderedSet[Address]
    exclude: FrozenOrderedSet[Address]

    def __init__(
        self,
        include: Iterable[Address],
        *,
        exclude: Iterable[Address] = (),
    ) -> None:
        """The result of inferring dependencies."""
        object.__setattr__(self, "include", FrozenOrderedSet(sorted(include)))
        object.__setattr__(self, "exclude", FrozenOrderedSet(sorted(exclude)))


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class TransitivelyExcludeDependenciesRequest(Generic[FS], EngineAwareParameter):
    """A request to transitvely exclude dependencies of a "root" node.

    This is similar to `InferDependenciesRequest`, except the request is only made for "root" nodes
    in the dependency graph.

    This mirrors the public facing "transitive exclude" dependency feature (i.e. `!!<address>`).
    """

    infer_from: ClassVar[Type[FS]]  # type: ignore[misc]

    field_set: FS


class TransitivelyExcludeDependencies(FrozenOrderedSet[Address]):
    pass


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class ValidateDependenciesRequest(Generic[FS], ABC):
    """A request to validate dependencies after they have been computed.

    An implementing rule should raise an exception if dependencies are invalid.
    """

    field_set_type: ClassVar[Type[FS]]  # type: ignore[misc]

    field_set: FS
    dependencies: Addresses


@dataclass(frozen=True)
class ValidatedDependencies:
    pass


@dataclass(frozen=True)
class DependenciesRuleApplicationRequest:
    """A request to return the applicable dependency rule action for each dependency of a target."""

    address: Address
    dependencies: Addresses
    description_of_origin: str = dataclasses.field(hash=False, compare=False)


@dataclass(frozen=True)
class DependenciesRuleApplication:
    """Maps all dependencies to their respective dependency rule application of an origin target
    address.

    The `applications` will be empty and the `address` `None` if there is no dependency rule
    implementation.
    """

    address: Address | None = None
    dependencies_rule: FrozenDict[Address, DependencyRuleApplication] = FrozenDict()

    def __post_init__(self):
        if self.dependencies_rule and self.address is None:
            raise ValueError(
                "The `address` field must not be None when there are `dependencies_rule`s."
            )

    @classmethod
    @memoized_method
    def allow_all(cls) -> DependenciesRuleApplication:
        return cls()

    def execute_actions(self) -> None:
        errors = [
            action_error.replace("\n", "\n    ")
            for action_error in (rule.execute() for rule in self.dependencies_rule.values())
            if action_error is not None
        ]
        if errors:
            err_count = len(errors)
            raise DependencyRuleActionDeniedError(
                softwrap(
                    f"""
                    {self.address} has {pluralize(err_count, 'dependency violation')}:

                    {bullet_list(errors)}
                    """
                )
            )


class SpecialCasedDependencies(StringSequenceField, AsyncFieldMixin):
    """Subclass this for fields that act similarly to the `dependencies` field, but are handled
    differently than normal dependencies.

    For example, you might have a field for package/binary dependencies, which you will call
    the equivalent of `./pants package` on. While you could put these in the normal
    `dependencies` field, it is often clearer to the user to call out this magic through a
    dedicated field.

    This type will ensure that the dependencies show up in project introspection,
    like `dependencies` and `dependents`, but not show up when you call `Get(TransitiveTargets,
    TransitiveTargetsRequest)` and `Get(Addresses, DependenciesRequest)`.

    To hydrate this field's dependencies, use `await Get(Addresses, UnparsedAddressInputs,
    tgt.get(MyField).to_unparsed_address_inputs())`.
    """

    def to_unparsed_address_inputs(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(
            self.value or (),
            owning_address=self.address,
            description_of_origin=f"the `{self.alias}` from the target {self.address}",
        )


# -----------------------------------------------------------------------------------------------
# Other common Fields used across most targets
# -----------------------------------------------------------------------------------------------


class Tags(StringSequenceField):
    alias = "tags"
    help = help_text(
        f"""
        Arbitrary strings to describe a target.

        For example, you may tag some test targets with 'integration_test' so that you could run
        `{bin_name()} --tag='integration_test' test ::`  to only run on targets with that tag.
        """
    )


class DescriptionField(StringField):
    alias = "description"
    help = help_text(
        f"""
        A human-readable description of the target.

        Use `{bin_name()} list --documented ::` to see all targets with descriptions.
        """
    )


COMMON_TARGET_FIELDS = (Tags, DescriptionField)


class OverridesField(AsyncFieldMixin, Field):
    """A mapping of keys (e.g. target names, source globs) to field names with their overridden
    values.

    This is meant for target generators to reduce boilerplate. It's up to the corresponding target
    generator rule to determine how to implement the field, such as how users specify the key. For
    example, `{"f.ext": {"tags": ['my_tag']}}`.
    """

    alias = "overrides"
    value: dict[tuple[str, ...], dict[str, Any]] | None
    default: ClassVar[None] = None  # A default does not make sense for this field.

    @classmethod
    def compute_value(
        cls,
        raw_value: Optional[Dict[Union[str, Tuple[str, ...]], Dict[str, Any]]],
        address: Address,
    ) -> Optional[FrozenDict[Tuple[str, ...], FrozenDict[str, ImmutableValue]]]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default is None:
            return None

        def invalid_type_exception() -> InvalidFieldException:
            return InvalidFieldTypeException(
                address,
                cls.alias,
                raw_value,
                expected_type="dict[str | tuple[str, ...], dict[str, Any]]",
            )

        if not isinstance(value_or_default, collections.abc.Mapping):
            raise invalid_type_exception()

        result: dict[tuple[str, ...], FrozenDict[str, ImmutableValue]] = {}
        for outer_key, nested_value in value_or_default.items():
            if isinstance(outer_key, str):
                outer_key = (outer_key,)
            if not isinstance(outer_key, collections.abc.Sequence) or not all(
                isinstance(elem, str) for elem in outer_key
            ):
                raise invalid_type_exception()
            if not isinstance(nested_value, collections.abc.Mapping):
                raise invalid_type_exception()
            if not all(isinstance(inner_key, str) for inner_key in nested_value):
                raise invalid_type_exception()
            result[tuple(outer_key)] = FrozenDict.deep_freeze(cast(Mapping[str, Any], nested_value))

        return FrozenDict(result)

    @classmethod
    def to_path_globs(
        cls,
        address: Address,
        overrides_keys: Iterable[str],
        unmatched_build_file_globs: UnmatchedBuildFileGlobs,
    ) -> tuple[PathGlobs, ...]:
        """Create a `PathGlobs` for each key.

        This should only be used if the keys are file globs.
        """

        def relativize_glob(glob: str) -> str:
            return (
                f"!{os.path.join(address.spec_path, glob[1:])}"
                if glob.startswith("!")
                else os.path.join(address.spec_path, glob)
            )

        return tuple(
            PathGlobs(
                [relativize_glob(glob)],
                glob_match_error_behavior=unmatched_build_file_globs.error_behavior,
                description_of_origin=f"the `overrides` field for {address}",
            )
            for glob in overrides_keys
        )

    def flatten(self) -> dict[str, dict[str, Any]]:
        """Combine all overrides for every key into a single dictionary."""
        result: dict[str, dict[str, Any]] = {}
        for keys, override in (self.value or {}).items():
            for key in keys:
                for field, value in override.items():
                    if key not in result:
                        result[key] = {field: value}
                        continue
                    if field not in result[key]:
                        result[key][field] = value
                        continue
                    raise InvalidFieldException(
                        f"Conflicting overrides in the `{self.alias}` field of "
                        f"`{self.address}` for the key `{key}` for "
                        f"the field `{field}`. You cannot specify the same field name "
                        "multiple times for the same key.\n\n"
                        f"(One override sets the field to `{repr(result[key][field])}` "
                        f"but another sets to `{repr(value)}`.)"
                    )
        return result

    @classmethod
    def flatten_paths(
        cls,
        address: Address,
        paths_and_overrides: Iterable[tuple[Paths, PathGlobs, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        """Combine all overrides for each file into a single dictionary."""
        result: dict[str, dict[str, Any]] = {}
        for paths, globs, override in paths_and_overrides:
            # NB: If some globs did not result in any Paths, we preserve them to ensure that
            # unconsumed overrides trigger errors during generation.
            for path in paths.files or globs.globs:
                for field, value in override.items():
                    if path not in result:
                        result[path] = {field: value}
                        continue
                    if field not in result[path]:
                        result[path][field] = value
                        continue
                    relpath = fast_relpath(path, address.spec_path)
                    raise InvalidFieldException(
                        f"Conflicting overrides for `{address}` for the relative path "
                        f"`{relpath}` for the field `{field}`. You cannot specify the same field "
                        f"name multiple times for the same path.\n\n"
                        f"(One override sets the field to `{repr(result[path][field])}` "
                        f"but another sets to `{repr(value)}`.)"
                    )
        return result


def generate_multiple_sources_field_help_message(files_example: str) -> str:
    return softwrap(
        """
        A list of files and globs that belong to this target.

        Paths are relative to the BUILD file's directory. You can ignore files/globs by
        prefixing them with `!`.

        """
        + files_example
    )


def generate_file_based_overrides_field_help_message(
    generated_target_name: str, example: str
) -> str:
    example = textwrap.dedent(example.lstrip("\n"))  # noqa: PNT20
    example = textwrap.indent(example, " " * 4)
    return "\n".join(
        [
            softwrap(
                f"""
                Override the field values for generated `{generated_target_name}` targets.

                Expects a dictionary of relative file paths and globs to a dictionary for the
                overrides. You may either use a string for a single path / glob,
                or a string tuple for multiple paths / globs. Each override is a dictionary of
                field names to the overridden value.

                For example:

                {example}
                """
            ),
            "",
            softwrap(
                f"""
                File paths and globs are relative to the BUILD file's directory. Every overridden file is
                validated to belong to this target's `sources` field.

                If you'd like to override a field's value for every `{generated_target_name}` target
                generated by this target, change the field directly on this target rather than using the
                `overrides` field.

                You can specify the same file name in multiple keys, so long as you don't override the
                same field more than one time for the file.
                """
            ),
        ],
    )
