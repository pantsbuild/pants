# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

from pants.base.exceptions import ResolveError
from pants.build_graph.address import Address
from pants.engine.collection import Collection
from pants.engine.fs import GlobExpansionConjunction, GlobMatchErrorBehavior, PathGlobs
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.collections import assert_single_element
from pants.util.dirutil import fast_relpath_optional, recursive_dirname
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init

if TYPE_CHECKING:
    from pants.engine.internals.mapper import AddressFamily


class Spec(ABC):
    """A specification for what Pants should operate on."""

    @abstractmethod
    def __str__(self) -> str:
        """The normalized string representation of this spec."""


def _globs_in_single_dir(dir_path: str, build_patterns: Iterable[str]) -> Tuple[str, ...]:
    return tuple(os.path.join(dir_path, pat) for pat in build_patterns)


def _address_family_for_dir(
    dir_path: str, address_families: Mapping[str, "AddressFamily"]
) -> "AddressFamily":
    maybe_af = address_families.get(dir_path)
    if maybe_af is None:
        raise ResolveError(f"Path '{dir_path}' does not contain any BUILD files.")
    return maybe_af


def _all_address_target_pairs(
    address_families: Sequence["AddressFamily"],
) -> Sequence[Tuple[Address, TargetAdaptor]]:
    return tuple(
        itertools.chain.from_iterable(
            af.addresses_to_target_adaptors.items() for af in address_families
        )
    )


class AddressSpec(Spec, metaclass=ABCMeta):
    """Represents address selectors as passed from the command line."""

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

    @abstractmethod
    def matching_addresses(
        self, address_families: Sequence["AddressFamily"]
    ) -> Sequence[Tuple[Address, TargetAdaptor]]:
        """Given a list of AddressFamily, return (Address, TargetAdaptor) pairs matching this
        address spec.

        :raises: :class:`ResolveError` if no addresses could be matched and this spec type expects
            a match.
        """


@dataclass(frozen=True)
class SingleAddress(AddressSpec):
    """An AddressSpec for a single address."""

    directory: str
    name: str

    def __post_init__(self) -> None:
        if self.directory is None:
            raise ValueError(f"A SingleAddress must have a directory. Got: {self}")
        if self.name is None:
            raise ValueError(f"A SingleAddress must have a name. Got: {self}")

    def __str__(self) -> str:
        return f"{self.directory}:{self.name}"

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return _globs_in_single_dir(self.directory, build_patterns)

    def matching_address_families(
        self, address_families_dict: Mapping[str, "AddressFamily"]
    ) -> Tuple["AddressFamily", ...]:
        return (_address_family_for_dir(self.directory, address_families_dict),)

    def matching_addresses(
        self, address_families: Sequence["AddressFamily"]
    ) -> Sequence[Tuple[Address, TargetAdaptor]]:
        single_af = assert_single_element(address_families)
        addr_tgt_pairs = tuple(
            (addr, tgt)
            for addr, tgt in single_af.addresses_to_target_adaptors.items()
            if addr.target_name == self.name
        )
        # There will be at most one target with a given name in a single AddressFamily.
        assert len(addr_tgt_pairs) <= 1
        return addr_tgt_pairs


@dataclass(frozen=True)
class SiblingAddresses(AddressSpec):
    """An AddressSpec representing all addresses located directly within the given directory."""

    directory: str

    def __str__(self) -> str:
        return f"{self.directory}:"

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return _globs_in_single_dir(self.directory, build_patterns)

    def matching_address_families(
        self, address_families_dict: Mapping[str, "AddressFamily"]
    ) -> Tuple["AddressFamily", ...]:
        return (_address_family_for_dir(self.directory, address_families_dict),)

    def matching_addresses(
        self, address_families: Sequence["AddressFamily"]
    ) -> Sequence[Tuple[Address, TargetAdaptor]]:
        return _all_address_target_pairs(address_families)


@dataclass(frozen=True)
class DescendantAddresses(AddressSpec):
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
        matching = _all_address_target_pairs(address_families)
        if len(matching) == 0:
            raise ResolveError(f"Address spec '{str(self)}' does not match any targets.")
        return matching


@dataclass(frozen=True)
class AscendantAddresses(AddressSpec):
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

    def matching_addresses(
        self, address_families: Sequence["AddressFamily"]
    ) -> Sequence[Tuple[Address, TargetAdaptor]]:
        return _all_address_target_pairs(address_families)


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressSpecs:
    specs: Tuple[AddressSpec, ...]
    filter_by_global_options: bool

    def __init__(
        self, specs: Iterable[AddressSpec], *, filter_by_global_options: bool = False
    ) -> None:
        """Create the specs for what addresses Pants should run on.

        If `filter_by_global_options` is set to True, then the resulting Addresses will be filtered
        by the global options `--tag` and `--exclude-target-regexp`.
        """
        self.specs = tuple(specs)
        self.filter_by_global_options = filter_by_global_options

    @staticmethod
    def more_specific(spec1: Optional[AddressSpec], spec2: Optional[AddressSpec]) -> AddressSpec:
        # Note that if either of spec1 or spec2 is None, the other will be returned.
        if spec1 is None and spec2 is None:
            raise ValueError("Internal error: both specs provided to more_specific() were None")
        _specificity = {
            SingleAddress: 0,
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
            itertools.chain.from_iterable(spec.to_globs(build_patterns) for spec in self)
        )
        ignores = (f"!{p}" for p in build_ignore_patterns)
        return PathGlobs(globs=(*includes, *ignores))

    def __iter__(self) -> Iterator[AddressSpec]:
        return iter(self.specs)

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


class FilesystemSpecs(Collection[FilesystemSpec]):
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

    @memoized_property
    def includes(self) -> Tuple[Union[FilesystemLiteralSpec, FilesystemGlobSpec], ...]:
        return tuple(
            spec for spec in self if isinstance(spec, (FilesystemGlobSpec, FilesystemLiteralSpec))
        )

    @memoized_property
    def ignores(self) -> Tuple[FilesystemIgnoreSpec, ...]:
        return tuple(spec for spec in self if isinstance(spec, FilesystemIgnoreSpec))

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


@dataclass(frozen=True)
class Specs:
    address_specs: AddressSpecs
    filesystem_specs: FilesystemSpecs

    @property
    def provided(self) -> bool:
        """Did the user provide specs?"""
        return bool(self.address_specs) or bool(self.filesystem_specs)
