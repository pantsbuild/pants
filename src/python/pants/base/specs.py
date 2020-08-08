# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Sequence, Tuple, Union, cast

from pants.base.exceptions import ResolveError
from pants.build_graph.address import Address
from pants.engine.fs import GlobExpansionConjunction, GlobMatchErrorBehavior, PathGlobs
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

    This may be a traditional address, like `a/b/c:c`, or a file address using disambiguation
    syntax, e.g. `a/b/c.txt:tgt`.
    """

    path_component: str
    target_component: str

    def __str__(self) -> str:
        return f"{self.path_component}:{self.target_component}"


class AddressGlobSpec(AddressSpec, metaclass=ABCMeta):
    @abstractmethod
    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        """Generate glob patterns matching exactly all the BUILD files this address spec covers."""

    @abstractmethod
    def matching_address_families(
        self, address_families_dict: Mapping[str, "AddressFamily"]
    ) -> Tuple["AddressFamily", ...]:
        """Given a dict of (namespace path) -> AddressFamily, return the values matching this
        address spec.

        :raises: :class:`ResolveError` if no address families matched this spec and this spec type
            expects a match.
        """

    def matching_addresses(
        self, address_families: Sequence["AddressFamily"]
    ) -> Sequence[Tuple[Address, TargetAdaptor]]:
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


@dataclass(frozen=True)
class SiblingAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses located directly within the given directory."""

    directory: str

    def __str__(self) -> str:
        return f"{self.directory}:"

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return tuple(os.path.join(self.directory, pat) for pat in build_patterns)

    def matching_address_families(
        self, address_families_dict: Mapping[str, "AddressFamily"]
    ) -> Tuple["AddressFamily", ...]:
        maybe_af = address_families_dict.get(self.directory)
        if maybe_af is None:
            raise ResolveError(
                f"Path '{self.directory}' does not contain any BUILD files, but '{self}' expected "
                "matching targets there."
            )
        return (maybe_af,)


@dataclass(frozen=True)
class DescendantAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses located recursively under the given directory."""

    directory: str

    def __str__(self) -> str:
        return f"{self.directory}::"

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return tuple(os.path.join(self.directory, "**", pat) for pat in build_patterns)

    def matching_address_families(
        self, address_families_dict: Mapping[str, "AddressFamily"]
    ) -> Tuple["AddressFamily", ...]:
        return tuple(
            af
            for ns, af in address_families_dict.items()
            if fast_relpath_optional(ns, self.directory) is not None
        )

    def matching_addresses(
        self, address_families: Sequence["AddressFamily"]
    ) -> Sequence[Tuple[Address, TargetAdaptor]]:
        matching = super().matching_addresses(address_families)
        if len(matching) == 0:
            raise ResolveError(f"Address spec '{self}' does not match any targets.")
        return matching


@dataclass(frozen=True)
class AscendantAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses located recursively _above_ the given directory."""

    directory: str

    def __str__(self) -> str:
        return f"{self.directory}^"

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return tuple(
            os.path.join(f, pattern)
            for pattern in build_patterns
            for f in recursive_dirname(self.directory)
        )

    def matching_address_families(
        self, address_families_dict: Mapping[str, "AddressFamily"]
    ) -> Tuple["AddressFamily", ...]:
        return tuple(
            af
            for ns, af in address_families_dict.items()
            if fast_relpath_optional(self.directory, ns) is not None
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressSpecs:
    literals: Tuple[AddressLiteralSpec, ...]
    globs: Tuple[AddressGlobSpec, ...]
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
    def specs(self) -> Tuple[AddressSpec, ...]:
        return (*self.literals, *self.globs)

    @staticmethod
    def more_specific(spec1: Optional[AddressSpec], spec2: Optional[AddressSpec]) -> AddressSpec:
        # Note that if either of spec1 or spec2 is None, the other will be returned.
        if spec1 is None and spec2 is None:
            raise ValueError("Internal error: both specs provided to more_specific() were None")
        _specificity = {
            AddressLiteralSpec: 0,
            SiblingAddresses: 1,
            AscendantAddresses: 2,
            DescendantAddresses: 3,
            type(None): 99,
        }
        result = spec1 if _specificity[type(spec1)] < _specificity[type(spec2)] else spec2
        return cast(AddressSpec, result)

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
    pass


@dataclass(frozen=True)
class FilesystemLiteralSpec(FilesystemSpec):
    """A literal file name, e.g. `foo.py`."""

    file: str

    def __str__(self) -> str:
        return self.file


@dataclass(frozen=True)
class FilesystemGlobSpec(FilesystemSpec):
    """A spec with a glob or globs, e.g. `*.py` and `**/*.java`."""

    glob: str

    def __str__(self) -> str:
        return self.glob


@dataclass(frozen=True)
class FilesystemIgnoreSpec(FilesystemSpec):
    """A spec to ignore certain files or globs."""

    glob: str

    def __post_init__(self) -> None:
        if self.glob.startswith("!"):
            raise ValueError(f"The `glob` for {self} should not start with `!`.")

    def __str__(self) -> str:
        return f"!{self.glob}"


@frozen_after_init
@dataclass(unsafe_hash=True)
class FilesystemSpecs:
    includes: Tuple[Union[FilesystemLiteralSpec, FilesystemGlobSpec], ...]
    ignores: Tuple[FilesystemIgnoreSpec, ...]

    def __init__(self, specs: Iterable[FilesystemSpec]) -> None:
        includes = []
        ignores = []
        for spec in specs:
            if isinstance(spec, (FilesystemLiteralSpec, FilesystemGlobSpec)):
                includes.append(spec)
            elif isinstance(spec, FilesystemIgnoreSpec):
                ignores.append(spec)
            else:
                raise ValueError(f"Unexpected type of FilesystemSpec: {repr(self)}")
        self.includes = tuple(includes)
        self.ignores = tuple(ignores)

    @property
    def specs(self) -> Tuple[FilesystemSpec, ...]:
        return (*self.includes, *self.ignores)

    @staticmethod
    def more_specific(
        spec1: Optional[FilesystemSpec], spec2: Optional[FilesystemSpec]
    ) -> FilesystemSpec:
        # Note that if either of spec1 or spec2 is None, the other will be returned.
        if spec1 is None and spec2 is None:
            raise ValueError("Internal error: both specs provided to more_specific() were None")
        _specificity = {
            FilesystemLiteralSpec: 0,
            FilesystemGlobSpec: 1,
            type(None): 99,
        }
        result = spec1 if _specificity[type(spec1)] < _specificity[type(spec2)] else spec2
        return cast(FilesystemSpec, result)

    @staticmethod
    def _generate_path_globs(
        specs: Iterable[FilesystemSpec], glob_match_error_behavior: GlobMatchErrorBehavior
    ) -> PathGlobs:
        return PathGlobs(
            globs=(str(s) for s in specs),
            glob_match_error_behavior=glob_match_error_behavior,
            # We validate that _every_ glob is valid.
            conjunction=GlobExpansionConjunction.all_match,
            description_of_origin=(
                None
                if glob_match_error_behavior == GlobMatchErrorBehavior.ignore
                else "file arguments"
            ),
        )

    def path_globs_for_spec(
        self,
        spec: Union[FilesystemLiteralSpec, FilesystemGlobSpec],
        glob_match_error_behavior: GlobMatchErrorBehavior,
    ) -> PathGlobs:
        """Generate PathGlobs for the specific spec, automatically including the instance's
        FilesystemIgnoreSpecs."""
        return self._generate_path_globs((spec, *self.ignores), glob_match_error_behavior)

    def to_path_globs(self, glob_match_error_behavior: GlobMatchErrorBehavior) -> PathGlobs:
        """Generate a single PathGlobs for the instance."""
        return self._generate_path_globs((*self.includes, *self.ignores), glob_match_error_behavior)

    def __bool__(self) -> bool:
        return bool(self.specs)


@dataclass(frozen=True)
class Specs:
    address_specs: AddressSpecs
    filesystem_specs: FilesystemSpecs

    @property
    def provided(self) -> bool:
        """Did the user provide specs?"""
        return bool(self.address_specs) or bool(self.filesystem_specs)
