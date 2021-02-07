# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict, Dict, List, Optional, Set, Tuple, cast

from pants.backend.python.target_types import (
    ModuleMappingField,
    PythonRequirementsField,
    PythonSources,
)
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.stripped_source_files import StrippedSourceFileNames
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesPathsRequest, Targets
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonModule:
    module: str

    @classmethod
    def create_from_stripped_path(cls, path: PurePath) -> PythonModule:
        module_name_with_slashes = (
            path.parent if path.name == "__init__.py" else path.with_suffix("")
        )
        return cls(module_name_with_slashes.as_posix().replace("/", "."))


# -----------------------------------------------------------------------------------------------
# First-party module mapping
# -----------------------------------------------------------------------------------------------


class FirstPartyPythonMappingImpl(FrozenDict[str, Tuple[Address, ...]]):
    """A mapping of module names to owning addresses that a specific implementation adds for Python
    import dependency inference.

    For almost every implementation, there should only be one address per module to avoid ambiguity.
    However, the built-in implementation allows for 2 addresses when `.pyi` type stubs are used.
    """


@union
class FirstPartyPythonMappingImplMarker:
    """An entry point for a specific implementation of mapping module names to owning targets for
    Python import dependency inference.

    All implementations will be merged together. Any conflicting modules will be removed due to
    ambiguity.

    The addresses should all be file addresses, rather than BUILD addresses.
    """


class FirstPartyPythonModuleMapping(FrozenDict[str, Tuple[Address, ...]]):
    """A merged mapping of module names to owning addresses.

    This mapping may have been constructed from multiple distinct implementations, e.g.
    implementations for each codegen backends.
    """

    def addresses_for_module(self, module: str) -> Tuple[Address, ...]:
        addresses = self.get(module)
        if addresses:
            return addresses
        # If the module is not found, try the parent, if any. This is to accommodate `from`
        # imports, where we don't care about the specific symbol, but only the module. For example,
        # with `from my_project.app import App`, we only care about the `my_project.app` part.
        #
        # We do not look past the direct parent, as this could cause multiple ambiguous owners to
        # be resolved. This contrasts with the third-party module mapping, which will try every
        # ancestor.
        if "." not in module:
            return ()
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return self.get(parent_module, ())


@rule(level=LogLevel.DEBUG)
async def merge_first_party_module_mappings(
    union_membership: UnionMembership,
) -> FirstPartyPythonModuleMapping:
    all_mappings = await MultiGet(
        Get(
            FirstPartyPythonMappingImpl,
            FirstPartyPythonMappingImplMarker,
            marker_cls(),
        )
        for marker_cls in union_membership.get(FirstPartyPythonMappingImplMarker)
    )
    modules_to_addresses: Dict[str, Tuple[Address, ...]] = {}
    modules_with_multiple_implementations: Set[str] = set()
    for mapping in all_mappings:
        for module, addresses in mapping.items():
            if module in modules_to_addresses:
                modules_with_multiple_implementations.add(module)
            else:
                modules_to_addresses[module] = addresses
    for module in modules_with_multiple_implementations:
        modules_to_addresses.pop(module)
    return FirstPartyPythonModuleMapping(sorted(modules_to_addresses.items()))


# This is only used to register our implementation with the plugin hook via unions. Note that we
# implement this like any other plugin implementation so that we can run them all in parallel.
class FirstPartyPythonTargetsMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


@rule(desc="Creating map of first party Python targets to Python modules", level=LogLevel.DEBUG)
async def map_first_party_python_targets_to_modules(
    _: FirstPartyPythonTargetsMappingMarker,
) -> FirstPartyPythonMappingImpl:
    all_expanded_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    python_targets = tuple(tgt for tgt in all_expanded_targets if tgt.has_field(PythonSources))
    stripped_sources_per_target = await MultiGet(
        Get(StrippedSourceFileNames, SourcesPathsRequest(tgt[PythonSources]))
        for tgt in python_targets
    )

    modules_to_addresses: DefaultDict[str, List[Address]] = defaultdict(list)
    modules_with_multiple_implementations: Set[str] = set()
    for tgt, stripped_sources in zip(python_targets, stripped_sources_per_target):
        for stripped_f in stripped_sources:
            module = PythonModule.create_from_stripped_path(PurePath(stripped_f)).module
            if module in modules_to_addresses:
                # We check if one of the targets is an implementation (.py file) and the other is
                # a type stub (.pyi file), which we allow. Otherwise, we have ambiguity.
                either_targets_are_type_stubs = len(modules_to_addresses[module]) == 1 and (
                    tgt.address.filename.endswith(".pyi")
                    or modules_to_addresses[module][0].filename.endswith(".pyi")
                )
                if either_targets_are_type_stubs:
                    modules_to_addresses[module].append(tgt.address)
                else:
                    modules_with_multiple_implementations.add(module)
            else:
                modules_to_addresses[module].append(tgt.address)

    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_implementations:
        modules_to_addresses.pop(module)

    return FirstPartyPythonMappingImpl(
        {k: tuple(sorted(v)) for k, v in modules_to_addresses.items()}
    )


# -----------------------------------------------------------------------------------------------
# Third party module mapping
# -----------------------------------------------------------------------------------------------


class ThirdPartyPythonModuleMapping(FrozenDict[str, Address]):
    def address_for_module(self, module: str) -> Optional[Address]:
        address = self.get(module)
        if address is not None:
            return address
        # If the module is not found, recursively try the ancestor modules, if any. For example,
        # pants.task.task.Task -> pants.task.task -> pants.task -> pants
        if "." not in module:
            return None
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return self.address_for_module(parent_module)


@rule(desc="Creating map of third party targets to Python modules", level=LogLevel.DEBUG)
async def map_third_party_modules_to_addresses() -> ThirdPartyPythonModuleMapping:
    all_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    modules_to_addresses: Dict[str, Address] = {}
    modules_with_multiple_owners: Set[str] = set()
    for tgt in all_targets:
        if not tgt.has_field(PythonRequirementsField):
            continue
        module_map = tgt.get(ModuleMappingField).value or {}  # type: ignore[var-annotated]
        for python_req in tgt[PythonRequirementsField].value:
            modules = module_map.get(
                python_req.project_name,
                [python_req.project_name.lower().replace("-", "_")],
            )
            for module in modules:
                if module in modules_to_addresses:
                    modules_with_multiple_owners.add(module)
                else:
                    modules_to_addresses[module] = tgt.address
    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_owners:
        modules_to_addresses.pop(module)
    return ThirdPartyPythonModuleMapping(sorted(modules_to_addresses.items()))


# -----------------------------------------------------------------------------------------------
# module -> owners
# -----------------------------------------------------------------------------------------------


class PythonModuleOwners(Collection[Address]):
    """The target(s) that own a Python module.

    If >1 targets own the same module, and they're implementations (vs .pyi type stubs), the
    collection should be empty. The collection should never be > 2.
    """


@rule
async def map_module_to_address(
    module: PythonModule,
    first_party_mapping: FirstPartyPythonModuleMapping,
    third_party_mapping: ThirdPartyPythonModuleMapping,
) -> PythonModuleOwners:
    third_party_address = third_party_mapping.address_for_module(module.module)
    first_party_addresses = first_party_mapping.addresses_for_module(module.module)

    # It's possible for a user to write type stubs (`.pyi` files) for their third-party
    # dependencies. We check if that happened, but we're strict in validating that there is only a
    # single third party address and a single first-party address referring to a `.pyi` file;
    # otherwise, we have ambiguous implementations, so no-op.
    third_party_resolved_only = third_party_address and not first_party_addresses
    third_party_resolved_with_type_stub = (
        third_party_address
        and len(first_party_addresses) == 1
        and first_party_addresses[0].filename.endswith(".pyi")
    )

    if third_party_resolved_only:
        return PythonModuleOwners([cast(Address, third_party_address)])
    if third_party_resolved_with_type_stub:
        return PythonModuleOwners([cast(Address, third_party_address), first_party_addresses[0]])
    # Else, we have ambiguity between the third-party and first-party addresses.
    if third_party_address and first_party_addresses:
        return PythonModuleOwners()

    # We're done with looking at third-party addresses, and now solely look at first-party.
    if first_party_addresses:
        return PythonModuleOwners(first_party_addresses)
    return PythonModuleOwners()


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, FirstPartyPythonTargetsMappingMarker),
    )
