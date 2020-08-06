# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union, cast

from pants.engine.collection import Collection
from pants.engine.fs import GlobExpansionConjunction, GlobMatchErrorBehavior, PathGlobs
from pants.util.collections import assert_single_element
from pants.util.dirutil import fast_relpath_optional, recursive_dirname
from pants.util.memo import memoized_property


class Spec(ABC):
    """A specification for what Pants should operate on."""

    @abstractmethod
    def __str__(self) -> str:
        """The normalized string representation of this spec."""


class AddressSpec(Spec, metaclass=ABCMeta):
    """Represents address selectors as passed from the command line.

    Supports `Single` target addresses as well as `Sibling` (:) and `Descendant` (::) selector forms.

    Note: In general, 'spec' should not be a user visible term, it is usually appropriate to
    substitute 'address' for a spec resolved to an address, or 'address selector' if you are
    referring to an unresolved spec string.
    """

    class AddressFamilyResolutionError(Exception):
        pass

    @abstractmethod
    def matching_address_families(self, address_families_dict: Dict[str, Any]) -> List[Any]:
        """Given a dict of (namespace path) -> AddressFamily, return the values matching this
        address spec.

        :raises: :class:`AddressSpec.AddressFamilyResolutionError` if no address families matched this spec.
        """

    @classmethod
    def address_families_for_dir(
        cls, address_families_dict: Dict[str, Any], spec_dir_path: str
    ) -> List[Any]:
        """Implementation of `matching_address_families()` for address specs matching at most one
        directory."""
        maybe_af = address_families_dict.get(spec_dir_path, None)
        if maybe_af is None:
            raise cls.AddressFamilyResolutionError(
                'Path "{}" does not contain any BUILD files.'.format(spec_dir_path)
            )
        return [maybe_af]

    class AddressResolutionError(Exception):
        pass

    @abstractmethod
    def address_target_pairs_from_address_families(self, address_families: List[Any]):
        """Given a list of AddressFamily, return (address, target) pairs matching this address spec.

        :raises: :class:`SingleAddress._SingleAddressResolutionError` for resolution errors with a
                 :class:`SingleAddress` instance.
        :raises: :class:`AddressSpec.AddressResolutionError` if no targets could be found otherwise, if
                 the address spec type requires a non-empty set of targets.
        :return: list of (Address, Target) pairs.
        """

    @classmethod
    def all_address_target_pairs(cls, address_families):
        """Implementation of `address_target_pairs_from_address_families()` which does no
        filtering."""
        addr_tgt_pairs = []
        for af in address_families:
            addr_tgt_pairs.extend(af.addressables.items())
        return addr_tgt_pairs

    @abstractmethod
    def to_globs(self, address_mapper: Any) -> Tuple[str, ...]:
        """Generate glob patterns matching exactly all the BUILD files this address spec covers."""

    @staticmethod
    def globs_in_single_dir(spec_dir_path: str, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        """Implementation of `to_globs()` which only allows a single base directory."""
        return tuple(os.path.join(spec_dir_path, pat) for pat in build_patterns)


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

    def matching_address_families(self, address_families_dict: Dict[str, Any]) -> List[Any]:
        return self.address_families_for_dir(address_families_dict, self.directory)

    class _SingleAddressResolutionError(Exception):
        def __init__(self, single_address_family: Any, name: str) -> None:
            super().__init__()
            self.single_address_family = single_address_family
            self.name = name

    def address_target_pairs_from_address_families(self, address_families: Sequence[Any]):
        """Return the pair for the single target matching the single AddressFamily, or error.

        :raises: :class:`SingleAddress._SingleAddressResolutionError` if no targets could be found for a
                 :class:`SingleAddress` instance.
        :return: list of (Address, Target) pairs with exactly one element.
        """
        single_af = assert_single_element(address_families)
        addr_tgt_pairs = [
            (bfa, tgt)
            for bfa, tgt in single_af.addressables.items()
            if bfa.address.target_name == self.name
        ]
        if len(addr_tgt_pairs) == 0:
            raise self._SingleAddressResolutionError(single_af, self.name)
        # There will be at most one target with a given name in a single AddressFamily.
        assert len(addr_tgt_pairs) == 1
        return addr_tgt_pairs

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return self.globs_in_single_dir(self.directory, build_patterns)


@dataclass(frozen=True)
class SiblingAddresses(AddressSpec):
    """An AddressSpec representing all addresses located directly within the given directory."""

    directory: str

    def __str__(self) -> str:
        return f"{self.directory}:"

    def matching_address_families(self, address_families_dict: Dict[str, Any]) -> List[Any]:
        return self.address_families_for_dir(address_families_dict, self.directory)

    def address_target_pairs_from_address_families(self, address_families: Sequence[Any]):
        return self.all_address_target_pairs(address_families)

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return self.globs_in_single_dir(self.directory, build_patterns)


@dataclass(frozen=True)
class DescendantAddresses(AddressSpec):
    """An AddressSpec representing all addresses located recursively under the given directory."""

    directory: str
    error_if_no_matches: bool = True

    def __str__(self) -> str:
        return f"{self.directory}::"

    def matching_address_families(self, address_families_dict: Dict[str, Any]) -> List[Any]:
        return [
            af
            for ns, af in address_families_dict.items()
            if fast_relpath_optional(ns, self.directory) is not None
        ]

    def address_target_pairs_from_address_families(self, address_families: Sequence[Any]):
        addr_tgt_pairs = self.all_address_target_pairs(address_families)
        if self.error_if_no_matches and len(addr_tgt_pairs) == 0:
            raise self.AddressResolutionError(
                f"Address spec '{str(self)}' does not match any targets."
            )
        return addr_tgt_pairs

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return tuple(os.path.join(self.directory, "**", pat) for pat in build_patterns)


@dataclass(frozen=True)
class AscendantAddresses(AddressSpec):
    """An AddressSpec representing all addresses located recursively _above_ the given directory."""

    directory: str

    def __str__(self) -> str:
        return f"{self.directory}^"

    def matching_address_families(self, address_families_dict: Dict[str, Any]) -> List[Any]:
        return [
            af
            for ns, af in address_families_dict.items()
            if fast_relpath_optional(self.directory, ns) is not None
        ]

    def address_target_pairs_from_address_families(self, address_families):
        return self.all_address_target_pairs(address_families)

    def to_globs(self, build_patterns: Iterable[str]) -> Tuple[str, ...]:
        return tuple(
            os.path.join(f, pattern)
            for pattern in build_patterns
            for f in recursive_dirname(self.directory)
        )


_specificity = {
    SingleAddress: 0,
    SiblingAddresses: 1,
    AscendantAddresses: 2,
    DescendantAddresses: 3,
    type(None): 99,
}


def more_specific(
    address_spec1: Optional[AddressSpec], address_spec2: Optional[AddressSpec]
) -> AddressSpec:
    """Returns which of the two specs is more specific.

    This is useful when a target matches multiple specs, and we want to associate it with the "most
    specific" one, which will make the most intuitive sense to the user.
    """
    # Note that if either of spec1 or spec2 is None, the other will be returned.
    if address_spec1 is None and address_spec2 is None:
        raise ValueError("internal error: both specs provided to more_specific() were None")
    return cast(
        AddressSpec,
        address_spec1
        if _specificity[type(address_spec1)] < _specificity[type(address_spec2)]
        else address_spec2,
    )


class AddressSpecs(Collection[AddressSpec]):
    def to_path_globs(
        self, *, build_patterns: Iterable[str], build_ignore_patterns: Iterable[str]
    ) -> PathGlobs:
        includes = set(
            itertools.chain.from_iterable(spec.to_globs(build_patterns) for spec in self)
        )
        ignores = (f"!{p}" for p in build_ignore_patterns)
        return PathGlobs(globs=(*includes, *ignores))


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
