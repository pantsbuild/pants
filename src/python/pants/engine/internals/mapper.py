# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable, Mapping, TypeVar

from pants.backend.project_info.filter_targets import FilterSubsystem
from pants.base.exceptions import MappingError
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addresses import Addresses
from pants.engine.collection import Collection
from pants.engine.env_vars import EnvironmentVars
from pants.engine.internals.defaults import BuildFileDefaults, BuildFileDefaultsParserState
from pants.engine.internals.dep_rules import (
    BuildFileDependencyRules,
    BuildFileDependencyRulesParserState,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.target import RegisteredTargetTypes, Tags, Target
from pants.util.filtering import TargetFilter, and_filters, create_filters
from pants.util.memo import memoized_property


class DuplicateNameError(MappingError):
    """Indicates more than one top-level object was found with the same name."""


AddressMapT = TypeVar("AddressMapT", bound="AddressMap")


@dataclass(frozen=True)
class AddressMap:
    """Maps target adaptors from a byte source."""

    path: str
    name_to_target_adaptor: dict[str, TargetAdaptor]

    @classmethod
    def parse(
        cls,
        filepath: str,
        build_file_content: str,
        parser: Parser,
        extra_symbols: BuildFilePreludeSymbols,
        env_vars: EnvironmentVars,
        is_bootstrap: bool,
        defaults: BuildFileDefaultsParserState,
        dependents_rules: BuildFileDependencyRulesParserState | None,
        dependencies_rules: BuildFileDependencyRulesParserState | None,
    ) -> AddressMap:
        """Parses a source for targets.

        The target adaptors are all 'thin': any targets they point to in other namespaces or even in
        the same namespace but from a separate source are left as unresolved pointers.
        """
        try:
            target_adaptors = parser.parse(
                filepath,
                build_file_content,
                extra_symbols,
                env_vars,
                is_bootstrap,
                defaults,
                dependents_rules,
                dependencies_rules,
            )
        except Exception as e:
            raise MappingError(f"Failed to parse ./{filepath}:\n{type(e).__name__}: {e}")
        return cls.create(filepath, target_adaptors)

    @classmethod
    def create(
        cls: type[AddressMapT], filepath: str, target_adaptors: Iterable[TargetAdaptor]
    ) -> AddressMapT:
        name_to_target_adaptors: dict[str, TargetAdaptor] = {}
        for target_adaptor in target_adaptors:
            name = target_adaptor.name or os.path.basename(os.path.dirname(filepath))
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
    :param defaults: The default target field values, per target type, applicable for this address family.
    :param dependents_rules: The rules to apply on incoming dependencies to targets in this family.
    :param dependencies_rules: The rules to apply on the outgoing dependencies from targets in this family.
    """

    # The directory from which the adaptors were parsed.
    namespace: str
    name_to_target_adaptors: dict[str, tuple[str, TargetAdaptor]]
    defaults: BuildFileDefaults
    dependents_rules: BuildFileDependencyRules | None
    dependencies_rules: BuildFileDependencyRules | None

    @classmethod
    def create(
        cls,
        spec_path: str,
        address_maps: Iterable[AddressMap],
        defaults: BuildFileDefaults = BuildFileDefaults({}),
        dependents_rules: BuildFileDependencyRules | None = None,
        dependencies_rules: BuildFileDependencyRules | None = None,
    ) -> AddressFamily:
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

        name_to_target_adaptors: dict[str, tuple[str, TargetAdaptor]] = {}
        for address_map in address_maps:
            for name, target_adaptor in address_map.name_to_target_adaptor.items():
                if name in name_to_target_adaptors:
                    previous_path, _ = name_to_target_adaptors[name]
                    raise DuplicateNameError(
                        f"A target with name {name!r} is already defined in {previous_path!r}, but "
                        f"is also defined in {address_map.path!r}. Because both targets share the "
                        f"same namespace of {spec_path!r}, this is not allowed."
                    )
                name_to_target_adaptors[name] = (address_map.path, target_adaptor)
        return AddressFamily(
            namespace=spec_path,
            name_to_target_adaptors=dict(sorted(name_to_target_adaptors.items())),
            defaults=defaults,
            dependents_rules=dependents_rules,
            dependencies_rules=dependencies_rules,
        )

    @memoized_property
    def addresses_to_target_adaptors(self) -> Mapping[Address, TargetAdaptor]:
        return {
            Address(spec_path=self.namespace, target_name=name): target_adaptor
            for name, (_, target_adaptor) in self.name_to_target_adaptors.items()
        }

    @memoized_property
    def build_file_addresses(self) -> tuple[BuildFileAddress, ...]:
        return tuple(
            BuildFileAddress(
                rel_path=path, address=Address(spec_path=self.namespace, target_name=name)
            )
            for name, (path, _) in self.name_to_target_adaptors.items()
        )

    @property
    def target_names(self) -> tuple[str, ...]:
        return tuple(addr.target_name for addr in self.addresses_to_target_adaptors)

    def get_target_adaptor(self, address: Address) -> TargetAdaptor | None:
        assert address.spec_path == self.namespace
        entry = self.name_to_target_adaptors.get(address.target_name)
        if entry is None:
            return None
        _, target_adaptor = entry
        return target_adaptor

    def __hash__(self):
        return hash((self.namespace, self.defaults))

    def __repr__(self) -> str:
        return (
            f"AddressFamily(namespace={self.namespace!r}, "
            f"name_to_target_adaptors={sorted(self.name_to_target_adaptors.keys())})"
        )


@dataclass(frozen=True)
class SpecsFilter:
    """Filters targets with the `--tags`, `--exclude-target-regexp`, and `[filter]` subsystem
    options."""

    is_specified: bool
    filter_subsystem_filter: TargetFilter
    tags_filter: TargetFilter

    @classmethod
    def create(
        cls,
        filter_subsystem: FilterSubsystem,
        registered_target_types: RegisteredTargetTypes,
        *,
        tags: Iterable[str],
    ) -> SpecsFilter:
        def tags_outer_filter(tag: str) -> TargetFilter:
            def tags_inner_filter(tgt: Target) -> bool:
                return tag in (tgt.get(Tags).value or [])

            return tags_inner_filter

        tags_filter = and_filters(create_filters(tags, tags_outer_filter))

        return SpecsFilter(
            is_specified=bool(filter_subsystem.is_specified() or tags),
            filter_subsystem_filter=filter_subsystem.all_filters(registered_target_types),
            tags_filter=tags_filter,
        )

    def matches(self, target: Target) -> bool:
        """Check that the target matches the provided `--tag` and `--exclude-target-regexp`
        options."""
        return self.tags_filter(target) and self.filter_subsystem_filter(target)


class AddressFamilies(Collection[AddressFamily]):
    def addresses(self) -> Addresses:
        return Addresses(self._base_addresses())

    def _base_addresses(self) -> Iterable[Address]:
        for family in self:
            yield from family.addresses_to_target_adaptors
