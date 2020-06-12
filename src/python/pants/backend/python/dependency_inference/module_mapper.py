# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, Optional, Set

from pants.backend.python.target_types import PythonRequirementsField, PythonSources
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSourcesFieldRequest,
)
from pants.engine.addresses import Address
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Targets
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class PythonModule:
    module: str

    @classmethod
    def create_from_stripped_path(cls, path: PurePath) -> "PythonModule":
        module_name_with_slashes = (
            path.parent if path.name == "__init__.py" else path.with_suffix("")
        )
        return cls(module_name_with_slashes.as_posix().replace("/", "."))


@dataclass(frozen=True)
class FirstPartyModuleToAddressMapping:
    mapping: FrozenDict[str, Address]

    def address_for_module(self, module: str) -> Optional[Address]:
        target = self.mapping.get(module)
        if target is not None:
            return target
        # If the module is not found, try the parent, if any. This is to accommodate `from`
        # imports, where we don't care about the specific symbol, but only the module. For example,
        # with `from typing import List`, we only care about `typing`.
        # Unlike with third party modules, we do not look past the direct parent.
        if "." not in module:
            return None
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return self.mapping.get(parent_module)


@rule
async def map_first_party_modules_to_addresses() -> FirstPartyModuleToAddressMapping:
    all_targets = await Get[Targets](AddressSpecs([DescendantAddresses("")]))
    candidate_targets = tuple(tgt for tgt in all_targets if tgt.has_field(PythonSources))
    sources_per_target = await MultiGet(
        Get[SourceRootStrippedSources](StripSourcesFieldRequest(tgt[PythonSources]))
        for tgt in candidate_targets
    )
    modules_to_addresses: Dict[str, Address] = {}
    modules_with_multiple_owners: Set[str] = set()
    for tgt, sources in zip(candidate_targets, sources_per_target):
        for f in sources.snapshot.files:
            module = PythonModule.create_from_stripped_path(PurePath(f)).module
            if module in modules_to_addresses:
                modules_with_multiple_owners.add(module)
            else:
                modules_to_addresses[module] = tgt.address
    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_owners:
        modules_to_addresses.pop(module)
    return FirstPartyModuleToAddressMapping(FrozenDict(sorted(modules_to_addresses.items())))


@dataclass(frozen=True)
class ThirdPartyModuleToAddressMapping:
    mapping: FrozenDict[str, Address]

    def address_for_module(self, module: str) -> Optional[Address]:
        target = self.mapping.get(module)
        if target is not None:
            return target
        # If the module is not found, try the parent module, if any. For example,
        # pants.task.task.Task -> pants.task.task -> pants.task -> pants
        if "." not in module:
            return None
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return self.address_for_module(parent_module)


@rule
async def map_third_party_modules_to_addresses() -> ThirdPartyModuleToAddressMapping:
    all_targets = await Get[Targets](AddressSpecs([DescendantAddresses("")]))
    modules_to_addresses: Dict[str, Address] = {}
    modules_with_multiple_owners: Set[str] = set()
    for tgt in all_targets:
        if not tgt.has_field(PythonRequirementsField):
            continue
        for python_req in tgt[PythonRequirementsField].value:
            for module in python_req.modules:
                if module in modules_to_addresses:
                    modules_with_multiple_owners.add(module)
                else:
                    modules_to_addresses[module] = tgt.address
    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_owners:
        modules_to_addresses.pop(module)
    return ThirdPartyModuleToAddressMapping(FrozenDict(sorted(modules_to_addresses.items())))


@dataclass(frozen=True)
class PythonModuleOwner:
    """The target that owns a Python module.

    If >1 target own the same module, the `address` field should be set to `None` to avoid
    ambiguity.
    """

    address: Optional[Address]


@rule
async def map_module_to_address(
    module: PythonModule,
    first_party_mapping: FirstPartyModuleToAddressMapping,
    third_party_mapping: ThirdPartyModuleToAddressMapping,
) -> PythonModuleOwner:
    third_party_address = third_party_mapping.address_for_module(module.module)
    if third_party_address:
        return PythonModuleOwner(third_party_address)
    first_party_address = first_party_mapping.address_for_module(module.module)
    if first_party_address:
        return PythonModuleOwner(first_party_address)
    return PythonModuleOwner(address=None)


def rules():
    return [
        map_first_party_modules_to_addresses,
        map_third_party_modules_to_addresses,
        map_module_to_address,
    ]
