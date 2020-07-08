# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple, cast

from pants.base.exceptions import DuplicateNameError, MappingError
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.struct import TargetAdaptor
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class AddressMap:
    """Maps target adaptors from a byte source."""

    path: str
    name_to_target_adaptor: Dict[str, TargetAdaptor]

    @classmethod
    def parse(
        cls,
        filepath: str,
        build_file_content: str,
        parser: Parser,
        extra_symbols: BuildFilePreludeSymbols,
    ) -> "AddressMap":
        """Parses a source for targets.

        The target adaptors are all 'thin': any targets they point to in other namespaces or even in
        the same namespace but from a separate source are left as unresolved pointers.
        """
        try:
            target_adaptors = parser.parse(filepath, build_file_content, extra_symbols)
        except Exception as e:
            raise MappingError(f"Failed to parse {filepath}:\n{e!r}")
        name_to_target_adaptors: Dict[str, TargetAdaptor] = {}
        for target_adaptor in target_adaptors:
            attributes = target_adaptor._asdict()
            name = attributes["name"]
            if name in name_to_target_adaptors:
                duplicate = name_to_target_adaptors[name]
                raise DuplicateNameError(
                    f"A target already exists at {filepath!r} with name {name!r} and target type "
                    f"{duplicate.type_alias!r}. The {target_adaptor.type_alias!r} target "
                    "cannot use the same name."
                )
            name_to_target_adaptors[name] = target_adaptor
        return cls(filepath, dict(sorted(name_to_target_adaptors.items())))


class DifferingFamiliesError(MappingError):
    """Indicates an attempt was made to merge address maps from different families together."""


@dataclass(frozen=True)
class AddressFamily:
    """Represents the family of target adaptors in a namespace.

    To create an AddressFamily, use `create`.

    An address family can be composed of the target adaptors from zero or more underlying address
    sources. An "empty" AddressFamily is legal, and is the result when there are not build files in
    a particular namespace.

    :param namespace: The namespace path of this address family.
    :param name_to_target_adaptors: A dict mapping from name to the target adaptor.
    """

    namespace: str
    name_to_target_adaptors: Dict[str, Tuple[str, TargetAdaptor]]

    @classmethod
    def create(cls, spec_path: str, address_maps: Iterable[AddressMap]) -> "AddressFamily":
        """Creates an address family from the given set of address maps.

        :param spec_path: The directory prefix shared by all address_maps.
        :param address_maps: The family of maps that form this namespace.
        :raises: :class:`MappingError` if the given address maps do not form a family.
        """
        if spec_path == ".":
            spec_path = ""
        for address_map in address_maps:
            if not address_map.path.startswith(spec_path):
                raise DifferingFamiliesError(
                    f"Expected AddressMaps to share the same parent directory {spec_path!r}, "
                    f"but received: {address_map.path!r}"
                )

        name_to_target_adaptors = {}
        for address_map in address_maps:
            for name, target_adaptor in address_map.name_to_target_adaptor.items():
                if name in name_to_target_adaptors:
                    previous_path, _ = name_to_target_adaptors[name]
                    raise DuplicateNameError(
                        f"A target with name {name!r} is already defined in {previous_path!r}, but"
                        f"is also defined in {address_map.path!r}. Because both targets share the "
                        f"same namespace of {spec_path!r}, this is not allowed."
                    )
                name_to_target_adaptors[name] = (address_map.path, target_adaptor)
        return AddressFamily(
            namespace=spec_path,
            name_to_target_adaptors=dict(sorted(name_to_target_adaptors.items())),
        )

    @memoized_property
    def addressables(self) -> Dict[BuildFileAddress, TargetAdaptor]:
        return {
            BuildFileAddress(rel_path=path, target_name=name): obj
            for name, (path, obj) in self.name_to_target_adaptors.items()
        }

    @property
    def addressables_as_address_keyed(self) -> Dict[Address, TargetAdaptor]:
        """Identical to `addresses`, but with a `cast` to allow for type safe lookup of
        `Address`es."""
        return cast(Dict[Address, TargetAdaptor], self.addressables)

    def __hash__(self):
        return hash(self.namespace)

    def __repr__(self) -> str:
        return (
            f"AddressFamily(namespace={self.namespace!r}, "
            f"name_to_target_adaptors={sorted(self.name_to_target_adaptors.keys())})"
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressMapper:
    """Configuration to parse BUILD files matching a filename pattern."""

    parser: Parser
    prelude_glob_patterns: Tuple[str, ...]
    build_patterns: Tuple[str, ...]
    build_ignore_patterns: Tuple[str, ...]
    exclude_target_regexps: Tuple[str, ...]
    subproject_roots: Tuple[str, ...]

    def __init__(
        self,
        parser: Parser,
        prelude_glob_patterns: Optional[Iterable[str]] = None,
        build_patterns: Optional[Iterable[str]] = None,
        build_ignore_patterns: Optional[Iterable[str]] = None,
        exclude_target_regexps: Optional[Iterable[str]] = None,
        subproject_roots: Optional[Iterable[str]] = None,
    ) -> None:
        """Create an AddressMapper.

        :param build_patterns: A tuple of PathGlob-compatible patterns for identifying BUILD files
                               used to resolve addresses.
        :param build_ignore_patterns: A list of path ignore patterns used when searching for BUILD files.
        :param exclude_target_regexps: A list of regular expressions for excluding targets.
        """
        self.parser = parser
        self.prelude_glob_patterns = tuple(prelude_glob_patterns or [])
        self.build_patterns = tuple(build_patterns or ["BUILD", "BUILD.*"])
        self.build_ignore_patterns = tuple(build_ignore_patterns or [])
        self.exclude_target_regexps = tuple(exclude_target_regexps or [])
        self.subproject_roots = tuple(subproject_roots or [])

    def __repr__(self):
        return f"AddressMapper(build_patterns={self.build_patterns})"

    @memoized_property
    def exclude_patterns(self):
        return tuple(re.compile(pattern) for pattern in self.exclude_target_regexps)
