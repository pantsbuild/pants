# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# pants: infer-dep(native_engine.so)
# pants: infer-dep(native_engine.so.metadata)

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import datetime
from enum import Enum
from io import RawIOBase
from pathlib import Path
from typing import Any, ClassVar, Generic, Protocol, Self, TextIO, TypeVar, overload


from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import (
    CreateDigest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    GlobExpansionConjunction,
    NativeDownloadFile,
    PathMetadataRequest,
    PathMetadataResult,
    Paths,
)
from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.internals.native_dep_inference import (
    NativeDockerfileInfo,
    NativeJavascriptFileDependencies,
    NativePythonFileDependencies,
)
from pants.engine.internals.scheduler import Workunit, _PathGlobsAndRootCollection
from pants.engine.internals.session import RunId, SessionValues
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    Process,
)

# TODO: black and flake8 disagree about the content of this file:
#   see https://github.com/psf/black/issues/1548
# flake8: noqa: E302

# ------------------------------------------------------------------------------
# (core)
# ------------------------------------------------------------------------------

class PyFailure:
    def get_error(self) -> Exception | None: ...

K = TypeVar("K")
V = TypeVar("V")

class FrozenDict(Mapping[K, V]):
    """A wrapper around a normal `dict` that removes all methods to mutate the instance and that
    implements __hash__.

    This should be used instead of normal dicts when working with the engine because normal dicts
    are not safe to use.
    """

    @overload
    def __new__(cls, __items: Iterable[tuple[K, V]], **kwargs: V) -> Self: ...
    @overload
    def __new__(cls, __other: Mapping[K, V], **kwargs: V) -> Self: ...
    @overload
    def __new__(cls, **kwargs: V) -> Self: ...
    @classmethod
    def deep_freeze(cls, data: Mapping[K, V]) -> Self: ...
    @staticmethod
    def frozen(to_freeze: Mapping[K, V]) -> FrozenDict[K, V]: ...
    def __getitem__(self, k: K) -> V: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[K]: ...
    def __reversed__(self) -> Iterator[K]: ...
    def __eq__(self, other: Any) -> Any: ...
    def __lt__(self, other: Any) -> bool: ...
    def __or__(self, other: Any) -> FrozenDict[K, V]: ...
    def __ror__(self, other: Any) -> FrozenDict[K, V]: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

# ------------------------------------------------------------------------------
# Address
# ------------------------------------------------------------------------------

BANNED_CHARS_IN_TARGET_NAME: frozenset
BANNED_CHARS_IN_GENERATED_NAME: frozenset
BANNED_CHARS_IN_PARAMETERS: frozenset

def address_spec_parse(
    spec: str,
) -> tuple[tuple[str, str | None, str | None, tuple[tuple[str, str], ...]], str | None]: ...

class AddressParseException(Exception):
    pass

class InvalidAddressError(Exception):
    pass

class InvalidSpecPathError(Exception):
    pass

class InvalidTargetNameError(Exception):
    pass

class InvalidParametersError(Exception):
    pass

class UnsupportedWildcardError(Exception):
    pass

class AddressInput:
    """A string that has been parsed and normalized using the Address syntax.

    An AddressInput must be resolved into an Address using the engine (which involves inspecting
    disk to determine the types of its path component).
    """

    def __init__(
        self,
        original_spec: str,
        path_component: str,
        description_of_origin: str,
        target_component: str | None = None,
        generated_component: str | None = None,
        parameters: Mapping[str, str] | None = None,
    ) -> None: ...
    @classmethod
    def parse(
        cls,
        spec: str,
        *,
        description_of_origin: str,
        relative_to: str | None = None,
        subproject_roots: Sequence[str] | None = None,
    ) -> Self:
        """Parse a string into an AddressInput.

        :param spec: Target address spec.
        :param relative_to: path to use for sibling specs, ie: ':another_in_same_build_family',
          interprets the missing spec_path part as `relative_to`.
        :param subproject_roots: Paths that correspond with embedded build roots under
          the current build root.
        :param description_of_origin: where the AddressInput comes from, e.g. "CLI arguments" or
          "the option `--paths-from`". This is used for better error messages.

        For example:

            some_target(
                name='mytarget',
                dependencies=['path/to/buildfile:targetname'],
            )

        Where `path/to/buildfile:targetname` is the dependent target address spec.

        In there is no target name component, it defaults the default target in the resulting
        Address's spec_path.

        Optionally, specs can be prefixed with '//' to denote an absolute spec path. This is
        normally not significant except when a spec referring to a root level target is needed
        from deeper in the tree. For example, in `path/to/buildfile/BUILD`:

            some_target(
                name='mytarget',
                dependencies=[':targetname'],
            )

        The `targetname` spec refers to a target defined in `path/to/buildfile/BUILD*`. If instead
        you want to reference `targetname` in a root level BUILD file, use the absolute form.
        For example:

            some_target(
                name='mytarget',
                dependencies=['//:targetname'],
            )

        The spec may be for a generated target: `dir:generator#generated`.

        The spec may be a file, such as `a/b/c.txt`. It may include a relative address spec at the
        end, such as `a/b/c.txt:original` or `a/b/c.txt:../original`, to disambiguate which target
        the file comes from; otherwise, it will be assumed to come from the default target in the
        directory, i.e. a target which leaves off `name`.
        """
        ...

    @property
    def spec(self) -> str: ...
    @property
    def path_component(self) -> str: ...
    @property
    def target_component(self) -> str | None: ...
    @property
    def generated_component(self) -> str | None: ...
    @property
    def parameters(self) -> dict[str, str]: ...
    @property
    def description_of_origin(self) -> str: ...
    def file_to_address(self) -> Address:
        """Converts to an Address by assuming that the path_component is a file on disk."""
        ...

    def dir_to_address(self) -> Address:
        """Converts to an Address by assuming that the path_component is a directory on disk."""
        ...

class Address:
    """The unique address for a `Target`.

    Targets explicitly declared in BUILD files use the format `path/to:tgt`, whereas targets
    generated from other targets use the format `path/to:generator#generated`.
    """

    def __init__(
        self,
        spec_path: str,
        *,
        target_name: str | None = None,
        parameters: Mapping[str, str] | None = None,
        generated_name: str | None = None,
        relative_file_path: str | None = None,
    ) -> None:
        """
        :param spec_path: The path from the build root to the directory containing the BUILD file
          for the target. If the target is generated, this is the path to the generator target.
        :param target_name: The name of the target. For generated targets, this is the name of
            its target generator. If the `name` is left off (i.e. the default), set to `None`.
        :param parameters: A series of key-value pairs which are incorporated into the identity of
            the Address.
        :param generated_name: The name of what is generated. You can use a file path if the
            generated target represents an entity from the file system, such as `a/b/c` or
            `subdir/f.ext`.
        :param relative_file_path: The relative path from the spec_path to an addressed file,
          if any. Because files must always be located below targets that apply metadata to
          them, this will always be relative.
        """
        ...

    @property
    def spec_path(self) -> str: ...
    @property
    def generated_name(self) -> str | None: ...
    @property
    def relative_file_path(self) -> str | None: ...
    @property
    def parameters(self) -> dict[str, str]: ...
    @property
    def is_generated_target(self) -> bool: ...
    @property
    def is_file_target(self) -> bool: ...
    @property
    def is_parametrized(self) -> bool: ...
    def is_parametrized_subset_of(self, other: Address) -> bool:
        """True if this Address is == to the given Address, but with a subset of its parameters."""
        ...

    @property
    def filename(self) -> str: ...
    @property
    def target_name(self) -> str: ...
    @property
    def parameters_repr(self) -> str: ...
    @property
    def spec(self) -> str:
        """The canonical string representation of the Address.

        Prepends '//' if the target is at the root, to disambiguate build root level targets from
        "relative" spec notation.
        """
        ...

    @property
    def path_safe_spec(self) -> str: ...
    def parametrize(self, parameters: Mapping[str, str], replace: bool = False) -> Address:
        """Creates a new Address with the given `parameters` merged or replaced over
        self.parameters."""
        ...

    def maybe_convert_to_target_generator(self) -> Address:
        """If this address is generated or parametrized, convert it to its generator target.

        Otherwise, return self unmodified.
        """
        ...

    def create_generated(self, generated_name: str) -> Address: ...
    def create_file(self, relative_file_path: str) -> Address: ...
    def debug_hint(self) -> str: ...
    def metadata(self) -> dict[str, Any]: ...

    # NB: These methods are provided by our `__richcmp__` implementation, but must be declared in
    # the stub in order for mypy to accept them as comparable.
    def __lt__(self, other: Any) -> bool: ...
    def __gt__(self, other: Any) -> bool: ...

# ------------------------------------------------------------------------------
# Union
# ------------------------------------------------------------------------------

class UnionRule:
    union_base: type
    union_member: type

    def __init__(self, union_base: type, union_member: type) -> None: ...

_T = TypeVar("_T", bound=type)

class UnionMembership:
    @staticmethod
    def from_rules(rules: Iterable[UnionRule]) -> UnionMembership: ...
    @staticmethod
    def empty() -> UnionMembership: ...
    def __contains__(self, union_type: _T) -> bool: ...
    def __getitem__(self, union_type: _T) -> Sequence[_T]:
        """Get all members of this union type.

        If the union type does not exist because it has no members registered, this will raise an
        IndexError.

        Note that the type hint assumes that all union members will have subclassed the union type
        - this is only a convention and is not actually enforced. So, you may have inaccurate type
        hints.
        """

    def get(self, union_type: _T) -> Sequence[_T]:
        """Get all members of this union type.

        If the union type does not exist because it has no members registered, return an empty
        Sequence.

        Note that the type hint assumes that all union members will have subclassed the union type
        - this is only a convention and is not actually enforced. So, you may have inaccurate type
        hints.
        """

    def items(self) -> Iterable[tuple[type, Sequence[type]]]: ...
    def is_member(self, union_type: type, putative_member: type) -> bool: ...
    def has_members(self, union_type: type) -> bool:
        """Check whether the union has an implementation or not."""

# ------------------------------------------------------------------------------
# Scheduler
# ------------------------------------------------------------------------------

class PyExecutor:
    def __init__(self, core_threads: int, max_threads: int) -> None: ...
    def to_borrowed(self) -> PyExecutor: ...
    def shutdown(self, duration_secs: float) -> None: ...

# ------------------------------------------------------------------------------
# Target
# ------------------------------------------------------------------------------

# Type alias to express the intent that the type should be immutable and hashable. There's nothing
# to actually enforce this, outside of convention.
ImmutableValue = Any

class _NoValue:
    def __bool__(self) -> bool:
        """NB: Always returns `False`."""
        ...

    def __repr__(self) -> str: ...

# Marker for unspecified field values that should use the default value if applicable.
NO_VALUE: _NoValue

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
            def compute_value(cls, raw_value: Optional[int], address: Address) -> Optional[int]:
                value_or_default = super().compute_value(raw_value, address=address)
                if value_or_default is not None and not isinstance(value_or_default, int):
                    raise ValueError(
                        "The `timeout` field expects an integer, but was given"
                        f"{value_or_default} for target {address}."
                    )
                return value_or_default
    """

    # Opt-in per field class to use a "no value" marker for the `raw_value` in `compute_value()` in
    # case the field was not represented in the BUILD file.
    #
    # This will allow users to provide `None` as the field value (when applicable) without getting
    # the fields default value.
    none_is_valid_value: ClassVar[bool] = False

    # Subclasses must define these.
    alias: ClassVar[str]
    help: ClassVar[str | Callable[[], str]]

    # Subclasses must define at least one of these two.
    default: ClassVar[ImmutableValue]
    required: ClassVar[bool] = False

    # Subclasses may define these.
    removal_version: ClassVar[str | None] = None
    removal_hint: ClassVar[str | None] = None

    deprecated_alias: ClassVar[str | None] = None
    deprecated_alias_removal_version: ClassVar[str | None] = None

    value: ImmutableValue | None

    _raw_value_type: ClassVar[str]

    def __init__(self, raw_value: Any | None, address: Address) -> None: ...
    @classmethod
    def compute_value(cls, raw_value: Any | None, address: Address) -> ImmutableValue:
        """Convert the `raw_value` into `self.value`.

        You should perform any optional validation and/or hydration here. For example, you may want
        to check that an integer is > 0 or convert an `Iterable[str]` to `List[str]`.

        The resulting value must be hashable (and should be immutable).
        """
        ...

_ST = TypeVar("_ST")

class ScalarField(Field, Generic[_ST]):
    expected_type: ClassVar[type[_ST]]
    expected_type_description: ClassVar[str]
    value: _ST | None
    default: ClassVar[_ST | None] = None

    @classmethod
    def compute_value(cls, raw_value: Any | None, address: Address) -> _ST | None: ...

class BoolField(ScalarField[bool]):
    """A field whose value is a boolean.

    Subclasses must either set `default: bool` or `required = True` so that the value is always
    defined.
    """

    expected_type: ClassVar[type[bool]]
    expected_type_description: ClassVar[str]
    value: bool
    default: ClassVar[bool]

    @classmethod
    def compute_value(cls, raw_value: bool, address: Address) -> bool: ...  # type: ignore[override]

class TriBoolField(ScalarField[bool]):
    """A field whose value is a boolean or None, which is meant to represent a tri-state."""

    expected_type: ClassVar[type[bool]]
    expected_type_description: ClassVar[str]

    @classmethod
    def compute_value(cls, raw_value: bool | None, address: Address) -> bool | None: ...

class StringField(ScalarField[str]):
    expected_type: ClassVar[type[str]]
    expected_type_description: ClassVar[str]
    valid_choices: ClassVar[type[Enum] | tuple[str, ...] | None]

    @classmethod
    def compute_value(cls, raw_value: str | None, address: Address) -> str | None: ...

_ET = TypeVar("_ET")

class SequenceField(Field, Generic[_ET]):
    expected_element_type: ClassVar[type]
    expected_type_description: ClassVar[str]
    value: tuple[_ET, ...] | None
    default: ClassVar[tuple[_ET, ...] | None] = None

    @classmethod
    def compute_value(
        cls, raw_value: Iterable[Any] | None, address: Address
    ) -> tuple[_ET, ...] | None: ...

class StringSequenceField(SequenceField[str]):
    expected_element_type: ClassVar[type[str]]
    expected_type_description: ClassVar[str]
    valid_choices: ClassVar[type[Enum] | tuple[str, ...] | None]

    @classmethod
    def compute_value(
        cls, raw_value: Iterable[str] | None, address: Address
    ) -> tuple[str, ...] | None: ...

# NB: By subclassing `Field`, MyPy understands our type hints, and it means it doesn't matter
# which order you use for inheriting the field template vs. the mixin.
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
        async def hydrate_sources(request: HydrateSourcesRequest) -> HydratedSources:
            digest = await path_globs_to_digest(PathGlobs(request.field.value))
            result = await digest_to_snapshot(digest)
            request.field.validate_resolved_files(result.files)
            ...
            return HydratedSources(result)

    Then, call sites can `await` if they need to hydrate the field, even if they subclassed
    the original async field to have custom behavior:

        sources1 = hydrate_sources(HydrateSourcesRequest(my_tgt.get(Sources)))
        sources2 = hydrate_sources(HydrateSourcesRequest(custom_tgt.get(CustomSources)))
    """

    address: Address

    def __hash__(self) -> int: ...
    def __eq__(self, other: Any) -> bool: ...
    def __ne__(self, other: Any) -> bool: ...
    def __repr__(self) -> str: ...

class SourcesField(AsyncFieldMixin):
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

    expected_file_extensions: ClassVar[tuple[str, ...] | None]
    expected_num_files: ClassVar[int | range | None]
    uses_source_roots: ClassVar[bool]
    default: ClassVar[Any]
    default_glob_match_error_behavior: ClassVar[Any | None]
    @property
    def globs(self) -> tuple[str, ...]:
        """The raw globs, relative to the BUILD file."""
        ...
    def validate_resolved_files(self, files: Sequence[str]) -> None:
        """Perform any additional validation on the resulting source files, e.g. ensuring that
        certain banned files are not used.

        To enforce that the resulting files end in certain extensions, such as `.py` or `.java`, set
        the class property `expected_file_extensions`.

        To enforce that there are only a certain number of resulting files, such as binary targets
        checking for only 0-1 sources, set the class property `expected_num_files`.
        """
        ...
    @staticmethod
    def prefix_glob_with_dirpath(dirpath: str, glob: str) -> str: ...
    def _prefix_glob_with_address(self, glob: str) -> str: ...
    def path_globs(self, unmatched_build_file_globs: Any) -> Any: ...
    @classmethod
    def can_generate(cls, output_type: type[SourcesField], union_membership: Any) -> bool:
        """Can this field be used to generate the output_type?

        Generally, this method does not need to be used. Most call sites can simply use the below,
        and the engine will generate the sources if possible or will return an instance of
        HydratedSources with an empty snapshot if not possible:

            await hydrate_sources(
                HydrateSourcesRequest(
                    sources_field,
                    for_sources_types=[FortranSources],
                    enable_codegen=True,
                ),
                **implicitly(),
            )

        This method is useful when you need to filter targets before hydrating them, such as how
        you may filter targets via `tgt.has_field(MyField)`.
        """
        ...
    @property
    def filespec(self) -> Filespec:
        """The original globs, returned in the Filespec dict format.

        The globs will be relativized to the build root.
        """
        ...
    @property
    def filespec_matcher(self) -> FilespecMatcher: ...

class MultipleSourcesField(SourcesField):
    """The `sources: list[str]` field.

    See the docstring for `SourcesField` for some class properties you can set, such as
    `expected_file_extensions`.

    When you need to get the sources for all targets, use `tgt.get(SourcesField)` rather than
    `tgt.get(MultipleSourcesField)`.
    """

    alias: ClassVar[str]
    ban_subdirectories: ClassVar[bool]
    @property
    def globs(self) -> tuple[str, ...]: ...
    @classmethod
    def compute_value(cls, raw_value: Iterable[str] | None, address: Any) -> tuple[str, ...] | None: ...

class OptionalSingleSourceField(SourcesField):
    """The `source: str` field.

    See the docstring for `SourcesField` for some class properties you can set, such as
    `expected_file_extensions`.

    When you need to get the sources for all targets, use `tgt.get(SourcesField)` rather than
    `tgt.get(OptionalSingleSourceField)`.

    Use `SingleSourceField` if the source must exist.
    """

    alias: ClassVar[str]
    @property
    def globs(self) -> tuple[str, ...]: ...
    @property
    def file_path(self) -> str | None:
        """The path to the file, relative to the build root.

        This works without hydration because we validate that `*` globs and `!` ignores are not
        used. However, consider still hydrating so that you verify the source file actually exists.

        The return type is optional because it's possible to have 0-1 files.
        """
        ...
    @classmethod
    def compute_value(cls, raw_value: str | None, address: Any) -> str | None: ...

class SingleSourceField(OptionalSingleSourceField):
    """The `source: str` field.

    Unlike `OptionalSingleSourceField`, the `.value` must be defined, whether by setting the
    `default` or making the field `required`.

    See the docstring for `SourcesField` for some class properties you can set, such as
    `expected_file_extensions`.

    When you need to get the sources for all targets, use `tgt.get(SourcesField)` rather than
    `tgt.get(SingleSourceField)`.
    """

    value: str
    @property
    def file_path(self) -> str: ...

# ------------------------------------------------------------------------------
# FS
# ------------------------------------------------------------------------------

class Digest:
    """A Digest is a lightweight reference to a set of files known about by the engine."""

    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...
    def __eq__(self, other: Digest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class FileDigest:
    """A FileDigest is a digest that refers to a file's content, without its name."""

    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...
    def __eq__(self, other: FileDigest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class Snapshot:
    """A Snapshot is a collection of sorted file paths and dir paths fingerprinted by their
    names/content.

    The `files` and `dirs` properties are symlink oblivious. If you require knowing about symlinks,
    you can use the `digest` property to request the `DigestEntries`.
    """

    @classmethod
    def create_for_testing(cls, files: Sequence[str], dirs: Sequence[str]) -> Snapshot: ...
    @property
    def digest(self) -> Digest: ...
    @property
    def dirs(self) -> tuple[str, ...]: ...
    @property
    def files(self) -> tuple[str, ...]: ...
    # Don't call this, call pants.engine.fs.SnapshotDiff instead
    def _diff(
        self, other: Snapshot
    ) -> tuple[
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
    ]: ...
    def __eq__(self, other: Snapshot | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class MergeDigests:
    """A request to merge several digests into one single digest.

    This will fail if there are any conflicting changes, such as two digests having the same file
    but with different content.
    """

    def __init__(self, digests: Iterable[Digest]) -> None: ...
    def __eq__(self, other: MergeDigests | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class AddPrefix:
    """A request to add the specified prefix path to every file and directory in the digest."""

    def __init__(self, digest: Digest, prefix: str) -> None: ...
    def __eq__(self, other: AddPrefix | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class RemovePrefix:
    """A request to remove the specified prefix path from every file and directory in the digest.

    This will fail if there are any files or directories in the original input digest without the
    specified prefix.
    """

    def __init__(self, digest: Digest, prefix: str) -> None: ...
    def __eq__(self, other: RemovePrefix | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class FilespecMatcher:
    def __init__(self, includes: Sequence[str], excludes: Sequence[str]) -> None: ...
    def __eq__(self, other: FilespecMatcher | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
    def matches(self, paths: Sequence[str]) -> list[str]: ...


class Filespec:
    """The original globs for a SourcesField, with includes and excludes.

    For example: Filespec(includes=['helloworld/*.py'], excludes=['helloworld/ignore.py']).

    The globs are in zglobs format.
    """

    @property
    def includes(self) -> tuple[str, ...]: ...
    @property
    def excludes(self) -> tuple[str, ...]: ...
    def __getitem__(self, key: str) -> tuple[str, ...]: ...
    def __eq__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class PathGlobs:
    def __init__(
        self,
        globs: Iterable[str],
        glob_match_error_behavior: GlobMatchErrorBehavior = ...,
        conjunction: GlobExpansionConjunction = ...,
        description_of_origin: str | None = None,
    ) -> None:
        """A request to find files given a set of globs.
        The syntax supported is roughly Git's glob syntax. Use `*` for globs, `**` for recursive
        globs, and `!` for ignores.
        :param globs: globs to match, e.g. `foo.txt` or `**/*.txt`. To exclude something, prefix it
            with `!`, e.g. `!ignore.py`.
        :param glob_match_error_behavior: whether to warn or error upon match failures
        :param conjunction: whether all `globs` must match or only at least one must match
        :param description_of_origin: a human-friendly description of where this PathGlobs request
            is coming from, used to improve the error message for unmatched globs. For example,
            this might be the text string "the option `--isort-config`".
        """
    @property
    def globs(self) -> tuple[str, ...]: ...
    @property
    def glob_match_error_behavior(self) -> GlobMatchErrorBehavior: ...
    @property
    def conjunction(self) -> GlobExpansionConjunction: ...
    @property
    def description_of_origin(self) -> str | None: ...
    def __eq__(self, other: PathGlobs | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

EMPTY_DIGEST: Digest
EMPTY_FILE_DIGEST: FileDigest
EMPTY_SNAPSHOT: Snapshot

def default_cache_path() -> str: ...

class PathMetadataKind:
    FILE: PathMetadataKind = ...
    DIRECTORY: PathMetadataKind = ...
    SYMLINK: PathMetadataKind = ...

class PathMetadata:
    def __new__(
        cls,
        path: str,
        kind: PathMetadataKind,
        length: int,
        is_executable: bool,
        unix_mode: int | None,
        accessed: datetime | None,
        created: datetime | None,
        modified: datetime | None,
        symlink_target: str | None,
    ) -> PathMetadata: ...
    @property
    def path(self) -> str: ...
    @property
    def kind(self) -> PathMetadataKind: ...
    @property
    def length(self) -> int: ...
    @property
    def is_executable(self) -> bool: ...
    @property
    def unix_mode(self) -> int | None: ...
    @property
    def accessed(self) -> datetime | None: ...
    @property
    def created(self) -> datetime | None: ...
    @property
    def modified(self) -> datetime | None: ...
    @property
    def symlink_target(self) -> str | None: ...
    def copy(self) -> PathMetadata: ...

class PathNamespace:
    WORKSPACE: PathNamespace = ...
    SYSTEM: PathNamespace = ...

    def __eq__(self, other: PathNamespace | Any) -> bool: ...
    def __hash__(self) -> int: ...

# ------------------------------------------------------------------------------
# Intrinsics
# ------------------------------------------------------------------------------

async def create_digest(
    create_digest: CreateDigest,
) -> Digest: ...
async def path_globs_to_digest(
    path_globs: PathGlobs,
) -> Digest: ...
async def path_globs_to_paths(
    path_globs: PathGlobs,
) -> Paths: ...
async def download_file(
    native_download_file: NativeDownloadFile,
) -> Digest: ...
async def digest_to_snapshot(digest: Digest) -> Snapshot: ...
async def get_digest_contents(digest: Digest) -> DigestContents: ...
async def get_digest_entries(digest: Digest) -> DigestEntries: ...
async def merge_digests(merge_digests: MergeDigests) -> Digest: ...
async def remove_prefix(remove_prefix: RemovePrefix) -> Digest: ...
async def add_prefix(add_prefix: AddPrefix) -> Digest: ...
async def execute_process(
    process: Process, process_execution_environment: ProcessExecutionEnvironment
) -> FallibleProcessResult: ...
async def digest_subset_to_digest(digest_subset: DigestSubset) -> Digest: ...
async def session_values() -> SessionValues: ...
async def run_id() -> RunId: ...
async def interactive_process(
    process: InteractiveProcess, process_execution_environment: ProcessExecutionEnvironment
) -> InteractiveProcessResult: ...
async def docker_resolve_image(request: DockerResolveImageRequest) -> DockerResolveImageResult: ...
async def parse_dockerfile_info(
    deps_request: NativeDependenciesRequest,
) -> tuple[tuple[str, NativeDockerfileInfo]]: ...
async def parse_python_deps(
    deps_request: NativeDependenciesRequest,
) -> tuple[tuple[str, NativePythonFileDependencies]]: ...
async def parse_javascript_deps(
    deps_request: NativeDependenciesRequest,
) -> tuple[tuple[str, NativeJavascriptFileDependencies]]: ...
async def path_metadata_request(request: PathMetadataRequest) -> PathMetadataResult: ...

# ------------------------------------------------------------------------------
# `pantsd`
# ------------------------------------------------------------------------------

def pantsd_fingerprint_compute(expected_option_names: set[str]) -> str: ...

# ------------------------------------------------------------------------------
# Process
# ------------------------------------------------------------------------------

class ProcessExecutionEnvironment:
    """Settings from the current Environment for how a `Process` should be run.

    Note that most values from the Environment are instead set via changing the arguments `argv` and
    `env` in the `Process` constructor.
    """

    def __init__(
        self,
        *,
        environment_name: str | None,
        platform: str,
        docker_image: str | None,
        remote_execution: bool,
        remote_execution_extra_platform_properties: Sequence[tuple[str, str]],
        execute_in_workspace: bool,
        # Must be a `KeepSandboxes` value
        keep_sandboxes: str,
    ) -> None: ...
    def __eq__(self, other: ProcessExecutionEnvironment | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
    @property
    def name(self) -> str | None: ...
    @property
    def environment_type(self) -> str: ...
    @property
    def remote_execution(self) -> bool: ...
    @property
    def docker_image(self) -> str | None: ...
    @property
    def platform(self) -> str: ...
    @property
    def remote_execution_extra_platform_properties(self) -> list[tuple[str, str]]: ...

# ------------------------------------------------------------------------------
# Workunits
# ------------------------------------------------------------------------------

def all_counter_names() -> list[str]: ...

# ------------------------------------------------------------------------------
# Nailgun
# ------------------------------------------------------------------------------

class PyNailgunClient:
    def __init__(self, port: int, executor: PyExecutor) -> None: ...
    def execute(self, command: str, args: list[str], env: dict[str, str]) -> int: ...

class PantsdConnectionException(Exception):
    pass

class PantsdClientException(Exception):
    pass

# ------------------------------------------------------------------------------
# Options
# ------------------------------------------------------------------------------

class PyGoalInfo:
    def __init__(
        self, scope_name: str, is_builtin: bool, is_auxiliary: bool, aliases: tuple[str, ...]
    ) -> None: ...

class PyOptionId:
    def __init__(
        self, *components: str, scope: str | None = None, switch: str | None = None
    ) -> None: ...

class PyNgInvocation:
    @staticmethod
    def empty() -> PyNgInvocation: ...
    @staticmethod
    def from_args(args: tuple[str, ...]) -> PyNgInvocation: ...
    def global_flag_strings(self) -> tuple[str, ...]: ...
    def specs(self) -> tuple[str, ...]: ...
    def goals(self) -> tuple[str, ...]: ...
    def passthru(self) -> tuple[str, ...]: ...

class PyPantsCommand:
    def builtin_or_auxiliary_goal(self) -> str | None: ...
    def goals(self) -> list[str]: ...
    def unknown_goals(self) -> list[str]: ...
    def specs(self) -> list[str]: ...
    def passthru(self) -> list[str]: ...

class PyConfigSource:
    def __init__(self, path: str, content: bytes) -> None: ...

# See src/rust/engine/src/externs/options.rs for the Rust-side versions of these types.
T = TypeVar("T")

# List of tuples of (value, rank, details string).
OptionValueDerivation = list[tuple[T, int, str]]

# A tuple (value, rank of value, optional derivation of value).
OptionValue = tuple[T | None, int, OptionValueDerivation | None]

def py_bin_name() -> str: ...

class PyOptionParser:
    def __init__(
        self,
        buildroot: Path | None,
        args: Sequence[str] | None,
        env: dict[str, str],
        configs: Sequence[PyConfigSource] | None,
        allow_pantsrc: bool,
        include_derivation: bool,
        known_scopes_to_flags: dict[str, frozenset[str]] | None,
        known_goals: Sequence[PyGoalInfo] | None,
    ) -> None: ...
    def get_bool(self, option_id: PyOptionId, default: bool | None) -> OptionValue[bool]: ...
    def get_int(self, option_id: PyOptionId, default: int | None) -> OptionValue[int]: ...
    def get_float(self, option_id: PyOptionId, default: float | None) -> OptionValue[float]: ...
    def get_string(self, option_id: PyOptionId, default: str | None) -> OptionValue[str]: ...
    def get_bool_list(
        self, option_id: PyOptionId, default: Iterable[bool]
    ) -> OptionValue[list[bool]]: ...
    def get_int_list(
        self, option_id: PyOptionId, default: Iterable[int]
    ) -> OptionValue[list[int]]: ...
    def get_float_list(
        self, option_id: PyOptionId, default: Iterable[float]
    ) -> OptionValue[list[float]]: ...
    def get_string_list(
        self, option_id: PyOptionId, default: Iterable[str]
    ) -> OptionValue[list[str]]: ...
    def get_dict(self, option_id: PyOptionId, default: dict[str, Any]) -> OptionValue[dict]: ...
    def get_command(self) -> PyPantsCommand: ...
    def get_unconsumed_flags(self) -> dict[str, list[str]]: ...
    def validate_config(self, valid_keys: dict[str, set[str]]) -> list[str]: ...

class PyNgOptionsReader:
    # Useful in tests.
    def __init__(
        self,
        buildroot: Path,
        flags: dict[str, dict[str, tuple[str | None, ...]]],
        env: dict[str, str],
        configs: Sequence[PyConfigSource],
    ) -> None: ...
    def get_bool(self, option_id: PyOptionId, default: bool | None) -> OptionValue[bool]: ...
    def get_int(self, option_id: PyOptionId, default: int | None) -> OptionValue[int]: ...
    def get_float(self, option_id: PyOptionId, default: float | None) -> OptionValue[float]: ...
    def get_string(self, option_id: PyOptionId, default: str | None) -> OptionValue[str]: ...
    def get_bool_list(
        self, option_id: PyOptionId, default: list[bool] | tuple[bool]
    ) -> OptionValue[list[bool]]: ...
    def get_int_list(
        self, option_id: PyOptionId, default: list[int] | tuple[int]
    ) -> OptionValue[list[int]]: ...
    def get_float_list(
        self, option_id: PyOptionId, default: list[float] | tuple[float]
    ) -> OptionValue[list[float]]: ...
    def get_string_list(
        self, option_id: PyOptionId, default: list[str] | tuple[str]
    ) -> OptionValue[list[str]]: ...
    def get_dict(self, option_id: PyOptionId, default: dict[str, Any]) -> OptionValue[dict]: ...

class PyNgSourcePartition:
    def paths(self) -> tuple[str, ...]: ...
    def options_reader(self) -> PyNgOptionsReader: ...

class PyNgOptions:
    def __init__(
        self,
        pants_invocation: PyNgInvocation,
        env: dict[str, str],
        include_derivation: bool,
    ) -> None: ...
    def get_options_reader_for_dir(self, dir: str) -> PyNgOptionsReader: ...
    def partition_sources(self, paths: tuple[str, ...]) -> tuple[PyNgSourcePartition, ...]: ...

# ------------------------------------------------------------------------------
# Testutil
# ------------------------------------------------------------------------------

class PyStubCASBuilder:
    def ac_always_errors(self) -> PyStubCASBuilder: ...
    def cas_always_errors(self) -> PyStubCASBuilder: ...
    def build(self, executor: PyExecutor) -> PyStubCAS: ...

class PyStubCAS:
    @classmethod
    def builder(cls) -> PyStubCASBuilder: ...
    @property
    def address(self) -> str: ...
    def remove(self, digest: FileDigest | Digest) -> bool: ...
    def contains(self, digest: FileDigest | Digest) -> bool: ...
    def contains_action_result(self, digest: FileDigest | Digest) -> bool: ...
    def action_cache_len(self) -> int: ...

# ------------------------------------------------------------------------------
# Dependency inference
# ------------------------------------------------------------------------------

class InferenceMetadata:
    @staticmethod
    def javascript(
        package_root: str,
        import_patterns: dict[str, Sequence[str]],
        config_root: str | None,
        paths: dict[str, Sequence[str]],
    ) -> InferenceMetadata: ...
    def __eq__(self, other: InferenceMetadata | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

class NativeDependenciesRequest:
    """A request to parse the dependencies of a set of files.

    * Depending on the implementation, a `metadata` structure
      can be passed. It will be supplied to the native parser, and
      it will be incorporated into the cache key.
    """

    def __init__(self, digest: Digest, metadata: InferenceMetadata | None = None) -> None: ...
    def __eq__(self, other: NativeDependenciesRequest | Any) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...

# ------------------------------------------------------------------------------
# (etc.)
# ------------------------------------------------------------------------------

class RawFdRunner(Protocol):
    def __call__(
        self,
        command: str,
        args: tuple[str, ...],
        env: dict[str, str],
        working_dir: str,
        cancellation_latch: PySessionCancellationLatch,
        stdin_fileno: int,
        stdout_fileno: int,
        stderr_fileno: int,
    ) -> int: ...

def initialize() -> None: ...
def capture_snapshots(
    scheduler: PyScheduler,
    session: PySession,
    path_globs_and_root_tuple_wrapper: _PathGlobsAndRootCollection,
) -> list[Snapshot]: ...
def ensure_remote_has_recursive(
    scheduler: PyScheduler, digests: list[Digest | FileDigest]
) -> None: ...
def ensure_directory_digest_persisted(scheduler: PyScheduler, digest: Digest) -> None: ...
def single_file_digests_to_bytes(
    scheduler: PyScheduler, digests: list[FileDigest]
) -> list[bytes]: ...
def write_digest(
    scheduler: PyScheduler,
    session: PySession,
    digest: Digest,
    path_prefix: str,
    clear_paths: Sequence[str],
) -> None: ...
def write_log(msg: str, level: int, target: str) -> None: ...
def flush_log() -> None: ...
def set_per_run_log_path(path: str | None) -> None: ...
def maybe_set_panic_handler() -> None: ...
def stdio_initialize(
    level: int,
    show_rust_3rdparty_logs: bool,
    show_target: bool,
    log_levels_by_target: dict[str, int],
    literal_filters: tuple[str, ...],
    regex_filters: tuple[str, ...],
    log_file: str,
) -> tuple[RawIOBase, TextIO, TextIO]: ...
def stdio_thread_get_destination() -> PyStdioDestination: ...
def stdio_thread_set_destination(destination: PyStdioDestination) -> None: ...
def stdio_thread_console_set(stdin_fileno: int, stdout_fileno: int, stderr_fileno: int) -> None: ...
def stdio_thread_console_color_mode_set(use_color: bool) -> None: ...
def stdio_thread_console_clear() -> None: ...
def stdio_write_stdout(msg: str) -> None: ...
def stdio_write_stderr(msg: str) -> None: ...
def task_side_effected() -> None: ...
def teardown_dynamic_ui(scheduler: PyScheduler, session: PySession) -> None: ...
def tasks_task_begin(
    tasks: PyTasks,
    func: Any,
    return_type: type,
    arg_types: Sequence[tuple[str, type]],
    masked_types: Sequence[type],
    side_effecting: bool,
    engine_aware_return_type: bool,
    cacheable: bool,
    name: str,
    desc: str,
    level: int,
) -> None: ...
def tasks_task_end(tasks: PyTasks) -> None: ...
def tasks_add_call(
    tasks: PyTasks,
    output: type,
    inputs: Sequence[type],
    rule_id: str,
    explicit_args_arity: int,
    vtable_entries: Sequence[tuple[type, str]] | None,
    in_scope_types: Sequence[type] | None,
) -> None: ...
def tasks_add_query(tasks: PyTasks, output_type: type, input_types: Sequence[type]) -> None: ...
def execution_add_root_select(
    scheduler: PyScheduler,
    execution_request: PyExecutionRequest,
    param_vals: Sequence,
    product: type,
) -> None: ...
def nailgun_server_await_shutdown(server: PyNailgunServer) -> None: ...
def nailgun_server_create(
    executor: PyExecutor, port: int, runner: RawFdRunner
) -> PyNailgunServer: ...
def scheduler_create(
    executor: PyExecutor,
    tasks: PyTasks,
    types: PyTypes,
    build_root: str,
    pants_workdir: str,
    local_execution_root_dir: str,
    named_caches_dir: str,
    ignore_patterns: Sequence[str],
    use_gitignore: bool,
    watch_filesystem: bool,
    remoting_options: PyRemotingOptions,
    local_store_options: PyLocalStoreOptions,
    exec_strategy_opts: PyExecutionStrategyOptions,
    ca_certs_path: str | None,
) -> PyScheduler: ...
def scheduler_execute(
    scheduler: PyScheduler, session: PySession, execution_request: PyExecutionRequest
) -> list: ...
def scheduler_metrics(scheduler: PyScheduler, session: PySession) -> dict[str, int]: ...
def scheduler_live_items(
    scheduler: PyScheduler, session: PySession
) -> tuple[list[Any], dict[str, tuple[int, int]]]: ...
def scheduler_shutdown(scheduler: PyScheduler, timeout_secs: int) -> None: ...
def session_new_run_id(session: PySession) -> None: ...
def session_poll_workunits(
    scheduler: PyScheduler, session: PySession, max_log_verbosity_level: int
) -> tuple[tuple[Workunit, ...], tuple[Workunit, ...]]: ...
def session_run_interactive_process(
    session: PySession, process: InteractiveProcess, process_config: ProcessExecutionEnvironment
) -> InteractiveProcessResult: ...
def session_get_metrics(session: PySession) -> dict[str, int]: ...
def session_get_observation_histograms(
    scheduler: PyScheduler, session: PySession
) -> dict[str, Any]: ...
def session_record_test_observation(
    scheduler: PyScheduler, session: PySession, value: int
) -> None: ...
def session_isolated_shallow_clone(session: PySession, build_id: str) -> PySession: ...
def session_wait_for_tail_tasks(
    scheduler: PyScheduler, session: PySession, timeout: float
) -> None: ...
def graph_len(scheduler: PyScheduler) -> int: ...
def graph_visualize(scheduler: PyScheduler, session: PySession, path: str) -> None: ...
def graph_invalidate_paths(scheduler: PyScheduler, paths: Iterable[str]) -> int: ...
def graph_invalidate_all_paths(scheduler: PyScheduler) -> int: ...
def graph_invalidate_all(scheduler: PyScheduler) -> None: ...
def check_invalidation_watcher_liveness(scheduler: PyScheduler) -> None: ...
def validate_reachability(scheduler: PyScheduler) -> None: ...
def rule_graph_consumed_types(
    scheduler: PyScheduler, param_types: Sequence[type], product_type: type
) -> list[type]: ...
def rule_graph_visualize(scheduler: PyScheduler, path: str) -> None: ...
def rule_subgraph_visualize(
    scheduler: PyScheduler, param_types: Sequence[type], product_type: type, path: str
) -> None: ...
def garbage_collect_store(scheduler: PyScheduler, target_size_bytes: int) -> None: ...
def lease_files_in_graph(scheduler: PyScheduler, session: PySession) -> None: ...
def strongly_connected_components(
    adjacency_lists: Sequence[tuple[Any, Sequence[Any]]],
) -> Sequence[Sequence[Any]]: ...
def hash_prefix_zero_bits(item: str) -> int: ...

# ------------------------------------------------------------------------------
# Selectors
# ------------------------------------------------------------------------------

_Output = TypeVar("_Output")
_Input = TypeVar("_Input")

class PyGeneratorResponseCall:
    rule_id: str
    output_type: type
    inputs: Sequence[Any]

    @overload
    def __init__(
        self,
        rule_id: str,
        output_type: type,
        args: tuple[Any, ...],
        input_arg0: dict[Any, type],
    ) -> None: ...
    @overload
    def __init__(
        self, rule_id: str, output_type: type, args: tuple[Any, ...], input_arg0: _Input
    ) -> None: ...
    @overload
    def __init__(
        self,
        rule_id: str,
        output_type: type,
        args: tuple[Any, ...],
        input_arg0: type[_Input],
        input_arg1: _Input,
    ) -> None: ...
    @overload
    def __init__(
        self,
        rule_id: str,
        output_type: type,
        args: tuple[Any, ...],
        input_arg0: type[_Input] | _Input,
        input_arg1: _Input | None = None,
    ) -> None: ...

# ------------------------------------------------------------------------------
# (uncategorized)
# ------------------------------------------------------------------------------

class PyExecutionRequest:
    def __init__(
        self, *, poll: bool, poll_delay_in_ms: int | None, timeout_in_ms: int | None
    ) -> None: ...

class PyExecutionStrategyOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyNailgunServer:
    def port(self) -> int: ...

class PyRemotingOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyLocalStoreOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyScheduler:
    pass

class PySession:
    def __init__(
        self,
        *,
        scheduler: PyScheduler,
        dynamic_ui: bool,
        ui_use_prodash: bool,
        max_workunit_level: int,
        build_id: str,
        session_values: SessionValues,
        cancellation_latch: PySessionCancellationLatch,
    ) -> None: ...
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
    @property
    def session_values(self) -> SessionValues: ...

class PySessionCancellationLatch:
    def __init__(self) -> None: ...

class PyTasks:
    def __init__(self) -> None: ...

class PyTypes:
    def __init__(self, **kwargs: Any) -> None: ...

class PyStdioDestination:
    pass

class PyThreadLocals:
    @classmethod
    def get_for_current_thread(cls) -> PyThreadLocals: ...
    def set_for_current_thread(self) -> None: ...

class PollTimeout(Exception):
    pass

# Prefer to import these exception types from `pants.base.exceptions`

class EngineError(Exception):
    """Base exception used for errors originating from the native engine."""

class IntrinsicError(EngineError):
    """Exceptions raised for failures within intrinsic methods implemented in Rust."""

class IncorrectProductError(EngineError):
    """Exceptions raised when a rule's return value doesn't match its declared type."""
