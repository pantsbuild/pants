# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Mapping, Optional, Pattern, Tuple

from pants.base.exceptions import MappingError
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.filtering import and_filters, create_filters
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init


class DuplicateNameError(MappingError):
    """Indicates more than one top-level object was found with the same name."""


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
    ) -> AddressMap:
        """Parses a source for targets.

        The target adaptors are all 'thin': any targets they point to in other namespaces or even in
        the same namespace but from a separate source are left as unresolved pointers.
        """
        try:
            target_adaptors = parser.parse(filepath, build_file_content, extra_symbols)
        except Exception as e:
            raise MappingError(f"Failed to parse {filepath}:\n{e}")
        name_to_target_adaptors: Dict[str, TargetAdaptor] = {}
        for target_adaptor in target_adaptors:
            name = target_adaptor.name
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
    """Represents the family of target adaptors collected from the BUILD files in one directory.

    To create an AddressFamily, use `create`.

    An address family can be composed of the target adaptors from zero or more underlying address
    sources. An "empty" AddressFamily is legal, and is the result when there are not build files in
    a particular namespace.

    :param namespace: The namespace path of this address family.
    :param name_to_target_adaptors: A dict mapping from name to the target adaptor.
    """

    # The directory from which the adaptors were parsed.
    namespace: str
    name_to_target_adaptors: Dict[str, Tuple[str, TargetAdaptor]]

    @classmethod
    def create(cls, spec_path: str, address_maps: Iterable[AddressMap]) -> AddressFamily:
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

        name_to_target_adaptors: Dict[str, Tuple[str, TargetAdaptor]] = {}
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
    def addresses_to_target_adaptors(self) -> Mapping[Address, TargetAdaptor]:
        return {
            Address(spec_path=self.namespace, target_name=name): target_adaptor
            for name, (_, target_adaptor) in self.name_to_target_adaptors.items()
        }

    @memoized_property
    def build_file_addresses(self) -> Tuple[BuildFileAddress, ...]:
        return tuple(
            BuildFileAddress(
                rel_path=path, address=Address(spec_path=self.namespace, target_name=name)
            )
            for name, (path, _) in self.name_to_target_adaptors.items()
        )

    @property
    def target_names(self) -> Tuple[str, ...]:
        return tuple(addr.target_name for addr in self.addresses_to_target_adaptors)

    def get_target_adaptor(self, address: Address) -> Optional[TargetAdaptor]:
        assert address.spec_path == self.namespace
        entry = self.name_to_target_adaptors.get(address.target_name)
        if entry is None:
            return None
        _, target_adaptor = entry
        return target_adaptor

    def __hash__(self):
        return hash(self.namespace)

    def __repr__(self) -> str:
        return (
            f"AddressFamily(namespace={self.namespace!r}, "
            f"name_to_target_adaptors={sorted(self.name_to_target_adaptors.keys())})"
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressSpecsFilter:
    """Filters addresses with the `--tags` and `--exclude-target-regexp` options."""

    tags: Tuple[str, ...]
    exclude_target_regexps: Tuple[str, ...]

    def __init__(
        self,
        *,
        tags: Optional[Iterable[str]] = None,
        exclude_target_regexps: Optional[Iterable[str]] = None,
    ) -> None:
        self.tags = tuple(tags or [])
        self.exclude_target_regexps = tuple(exclude_target_regexps or [])

    @memoized_property
    def _exclude_regexps(self) -> Tuple[Pattern, ...]:
        return tuple(re.compile(pattern) for pattern in self.exclude_target_regexps)

    def _is_excluded_by_pattern(self, address: Address) -> bool:
        return any(p.search(address.spec) is not None for p in self._exclude_regexps)

    @memoized_property
    def _tag_filter(self):
        def filter_for_tag(tag: str) -> Callable[[TargetAdaptor], bool]:
            def filter_target(tgt: TargetAdaptor) -> bool:
                # `tags` can sometimes be explicitly set to `None`. We convert that to an empty list
                # with `or`.
                tags = tgt.kwargs.get("tags", []) or []
                return tag in [str(t_tag) for t_tag in tags]

            return filter_target

        return and_filters(create_filters(self.tags, filter_for_tag))

    def matches(self, address: Address, target: TargetAdaptor) -> bool:
        """Check that the target matches the provided `--tags` and `--exclude-target-regexp`
        options."""
        return self._tag_filter(target) and not self._is_excluded_by_pattern(address)
