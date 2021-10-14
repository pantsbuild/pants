# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from pants.base.exceptions import ResolveError
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.engine.fs import GlobExpansionConjunction, PathGlobs
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.dirutil import fast_relpath_optional, recursive_dirname
from pants.util.meta import frozen_after_init

if TYPE_CHECKING:
    from pants.engine.internals.mapper import AddressFamily


class Spec(ABC):
    """A specification for what Pants should operate on."""

    @abstractmethod
    def __str__(self) -> str:
        """The normalized string representation of this spec."""


class AddressSpec(Spec, metaclass=ABCMeta):
    """Represents address selectors as passed from the command line."""


@dataclass(frozen=True)
class AddressLiteralSpec(AddressSpec):
    """An AddressSpec for a single address.

    This may be one of:

    * A traditional address, like `dir:lib`.
    * A generated target address like `dir:lib#generated` or `dir#generated`.
    * A file address using disambiguation syntax like dir/f.ext:lib` (files without a target will
      be FilesystemSpecs).
    """

    path_component: str
    target_component: str | None = None
    generated_component: str | None = None

    def __str__(self) -> str:
        tgt = f":{self.target_component}" if self.target_component else ""
        generated = f"#{self.generated_component}" if self.generated_component else ""
        return f"{self.path_component}{tgt}{generated}"

    @property
    def is_directory_shorthand(self) -> bool:
        """Is in the format `path/to/dir`, which is shorthand for `path/to/dir:dir`."""
        return self.target_component is None and self.generated_component is None


@dataclass(frozen=True)  # type: ignore[misc]
class AddressGlobSpec(AddressSpec, metaclass=ABCMeta):

    directory: str

    @abstractmethod
    def to_globs(self, build_patterns: Iterable[str]) -> tuple[str, ...]:
        """Generate glob patterns matching exactly all the BUILD files this address spec covers."""

    @abstractmethod
    def matching_address_families(
        self, address_families_dict: Mapping[str, AddressFamily]
    ) -> tuple[AddressFamily, ...]:
        """Given a dict of (namespace path) -> AddressFamily, return the values matching this
        address spec.

        :raises: :class:`ResolveError` if no address families matched this spec and this spec type
            expects a match.
        """

    def matching_addresses(
        self, address_families: Sequence[AddressFamily]
    ) -> Sequence[tuple[Address, TargetAdaptor]]:
        """Given a list of AddressFamily, return (Address, TargetAdaptor) pairs matching this
        address spec.

        :raises: :class:`ResolveError` if no addresses could be matched and this spec type expects
            a match.
        """
        return tuple(
            itertools.chain.from_iterable(
                af.addresses_to_target_adaptors.items() for af in address_families
            )
        )


class MaybeEmptySiblingAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses located directly within the given directory.

    It is not an error if there are no such addresses.
    """

    def __str__(self) -> str:
        return f"{self.directory}:"

    def to_globs(self, build_patterns: Iterable[str]) -> tuple[str, ...]:
        return tuple(os.path.join(self.directory, pat) for pat in build_patterns)

    def matching_address_families(
        self, address_families_dict: Mapping[str, AddressFamily]
    ) -> tuple[AddressFamily, ...]:
        maybe_af = address_families_dict.get(self.directory)
        return (maybe_af,) if maybe_af is not None else ()


class SiblingAddresses(MaybeEmptySiblingAddresses):
    """An AddressSpec representing all addresses located directly within the given directory.

    At least one such address must exist.
    """

    def matching_address_families(
        self, address_families_dict: Mapping[str, AddressFamily]
    ) -> tuple[AddressFamily, ...]:
        address_families_tuple = super().matching_address_families(address_families_dict)
        if not address_families_tuple:
            raise ResolveError(
                f"Path '{self.directory}' does not contain any BUILD files, but '{self}' expected "
                "matching targets there."
            )
        return address_families_tuple

    def matching_addresses(
        self, address_families: Sequence[AddressFamily]
    ) -> Sequence[tuple[Address, TargetAdaptor]]:
        matching = super().matching_addresses(address_families)
        if len(matching) == 0:
            raise ResolveError(f"Address spec '{self}' does not match any targets.")
        return matching


class MaybeEmptyDescendantAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses located recursively under the given directory.

    It is not an error if there are no such addresses.
    """

    def __str__(self) -> str:
        return f"{self.directory}::"

    def to_globs(self, build_patterns: Iterable[str]) -> tuple[str, ...]:
        return tuple(os.path.join(self.directory, "**", pat) for pat in build_patterns)

    def matching_address_families(
        self, address_families_dict: Mapping[str, AddressFamily]
    ) -> tuple[AddressFamily, ...]:
        return tuple(
            af
            for ns, af in address_families_dict.items()
            if fast_relpath_optional(ns, self.directory) is not None
        )


class DescendantAddresses(MaybeEmptyDescendantAddresses):
    """An AddressSpec representing all addresses located recursively under the given directory.

    At least one such address must exist.
    """

    def matching_addresses(
        self, address_families: Sequence[AddressFamily]
    ) -> Sequence[tuple[Address, TargetAdaptor]]:
        matching = super().matching_addresses(address_families)
        if len(matching) == 0:
            raise ResolveError(f"Address spec '{self}' does not match any targets.")
        return matching


class AscendantAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses located recursively in and above the given
    directory."""

    def __str__(self) -> str:
        return f"{self.directory}^"

    def to_globs(self, build_patterns: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            os.path.join(f, pattern)
            for pattern in build_patterns
            for f in recursive_dirname(self.directory)
        )

    def matching_address_families(
        self, address_families_dict: Mapping[str, AddressFamily]
    ) -> tuple[AddressFamily, ...]:
        return tuple(
            af
            for ns, af in address_families_dict.items()
            if fast_relpath_optional(self.directory, ns) is not None
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressSpecs:
    literals: tuple[AddressLiteralSpec, ...]
    globs: tuple[AddressGlobSpec, ...]
    filter_by_global_options: bool

    def __init__(
        self, specs: Iterable[AddressSpec], *, filter_by_global_options: bool = False
    ) -> None:
        """Create the specs for what addresses Pants should run on.

        If `filter_by_global_options` is set to True, then the resulting Addresses will be filtered
        by the global options `--tag` and `--exclude-target-regexp`.
        """
        literals = []
        globs = []
        for spec in specs:
            if isinstance(spec, AddressLiteralSpec):
                literals.append(spec)
            elif isinstance(spec, AddressGlobSpec):
                globs.append(spec)
            else:
                raise ValueError(f"Unexpected type of AddressSpec: {repr(self)}")

        self.literals = tuple(literals)
        self.globs = tuple(globs)
        self.filter_by_global_options = filter_by_global_options

    @property
    def specs(self) -> tuple[AddressSpec, ...]:
        return (*self.literals, *self.globs)

    def to_path_globs(
        self, *, build_patterns: Iterable[str], build_ignore_patterns: Iterable[str]
    ) -> PathGlobs:
        includes = set(
            itertools.chain.from_iterable(spec.to_globs(build_patterns) for spec in self.globs)
        )
        ignores = (f"!{p}" for p in build_ignore_patterns)
        return PathGlobs(globs=(*includes, *ignores))

    def __bool__(self) -> bool:
        return bool(self.specs)


class FilesystemSpec(Spec, metaclass=ABCMeta):
    @abstractmethod
    def to_glob(self) -> str:
        """Convert to a glob understood by `PathGlobs`."""


@dataclass(frozen=True)
class FileLiteralSpec(FilesystemSpec):
    """A literal file name, e.g. `foo.py`."""

    file: str

    def __str__(self) -> str:
        return self.file

    def to_glob(self) -> str:
        return self.file


@dataclass(frozen=True)
class FileGlobSpec(FilesystemSpec):
    """A spec with a glob or globs, e.g. `*.py` and `**/*.java`."""

    glob: str

    def __str__(self) -> str:
        return self.glob

    def to_glob(self) -> str:
        return self.glob


@dataclass(frozen=True)
class FileIgnoreSpec(FilesystemSpec):
    """A spec to ignore certain files or globs."""

    glob: str

    def __post_init__(self) -> None:
        if self.glob.startswith("!"):
            raise ValueError(f"The `glob` for {self} should not start with `!`.")

    def __str__(self) -> str:
        return f"!{self.glob}"

    def to_glob(self) -> str:
        return f"!{self.glob}"


@dataclass(frozen=True)
class DirLiteralSpec(FilesystemSpec):
    """A literal dir path, e.g. `some/dir`.

    The empty string represents the build root.
    """

    v: str

    def __str__(self) -> str:
        return self.v

    def to_glob(self) -> str:
        if not self.v:
            return "*"
        return f"{self.v}/*"

    def to_address_literal(self) -> AddressLiteralSpec:
        """For now, `dir` can also be shorthand for `dir:dir`."""
        return AddressLiteralSpec(
            path_component=self.v, target_component=None, generated_component=None
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class FilesystemSpecs:
    file_includes: tuple[FileLiteralSpec | FileGlobSpec, ...]
    dir_includes: tuple[DirLiteralSpec, ...]
    ignores: tuple[FileIgnoreSpec, ...]

    def __init__(self, specs: Iterable[FilesystemSpec]) -> None:
        file_includes = []
        dir_includes = []
        ignores = []
        for spec in specs:
            if isinstance(spec, (FileLiteralSpec, FileGlobSpec)):
                file_includes.append(spec)
            elif isinstance(spec, DirLiteralSpec):
                dir_includes.append(spec)
            elif isinstance(spec, FileIgnoreSpec):
                ignores.append(spec)
            else:
                raise AssertionError(f"Unexpected type of FilesystemSpec: {repr(self)}")
        self.file_includes = tuple(file_includes)
        self.dir_includes = tuple(dir_includes)
        self.ignores = tuple(ignores)

    @staticmethod
    def _generate_path_globs(
        specs: Iterable[FilesystemSpec], glob_match_error_behavior: GlobMatchErrorBehavior
    ) -> PathGlobs:
        return PathGlobs(
            globs=(s.to_glob() for s in specs),
            glob_match_error_behavior=glob_match_error_behavior,
            # We validate that _every_ glob is valid.
            conjunction=GlobExpansionConjunction.all_match,
            description_of_origin=(
                None
                if glob_match_error_behavior == GlobMatchErrorBehavior.ignore
                else "file/directory arguments"
            ),
        )

    def path_globs_for_spec(
        self,
        spec: FileLiteralSpec | FileGlobSpec | DirLiteralSpec,
        glob_match_error_behavior: GlobMatchErrorBehavior,
    ) -> PathGlobs:
        """Generate PathGlobs for the specific spec, automatically including the instance's
        FileIgnoreSpecs."""
        return self._generate_path_globs((spec, *self.ignores), glob_match_error_behavior)

    def to_path_globs(self, glob_match_error_behavior: GlobMatchErrorBehavior) -> PathGlobs:
        """Generate a single PathGlobs for the instance."""
        return self._generate_path_globs(
            (*self.file_includes, *self.dir_includes, *self.ignores), glob_match_error_behavior
        )

    def __bool__(self) -> bool:
        return bool(self.file_includes) or bool(self.dir_includes) or bool(self.ignores)


@dataclass(frozen=True)
class Specs:
    address_specs: AddressSpecs
    filesystem_specs: FilesystemSpecs

    @property
    def provided(self) -> bool:
        """Did the user provide specs?"""
        return bool(self.address_specs) or bool(self.filesystem_specs)

    @classmethod
    def empty(cls) -> Specs:
        return Specs(AddressSpecs([], filter_by_global_options=True), FilesystemSpecs([]))
