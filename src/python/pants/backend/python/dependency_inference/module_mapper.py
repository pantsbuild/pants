# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, Optional

from pants.backend.python.target_types import PythonRequirementsField, PythonSources
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSourcesFieldRequest,
)
from pants.engine.addresses import Address
from pants.engine.collection import DeduplicatedCollection
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
    for tgt, sources in zip(candidate_targets, sources_per_target):
        for f in sources.snapshot.files:
            module = PythonModule.create_from_stripped_path(PurePath(f)).module
            # NB: If >1 targets have the same module, we do not record the module. This is to
            # avoid ambiguity.
            if module in modules_to_addresses:
                modules_to_addresses.pop(module)
            else:
                modules_to_addresses[module] = tgt.address
    return FirstPartyModuleToAddressMapping(FrozenDict(modules_to_addresses))


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
    for tgt in all_targets:
        if not tgt.has_field(PythonRequirementsField):
            continue
        for python_req in tgt[PythonRequirementsField].value:
            for module in python_req.modules:
                # NB: If >1 targets have the same module, we do not record the module. This is to
                # avoid ambiguity.
                if module in modules_to_addresses:
                    modules_to_addresses.pop(module)
                else:
                    modules_to_addresses[module] = tgt.address
    return ThirdPartyModuleToAddressMapping(FrozenDict(modules_to_addresses))


class PythonModuleOwners(DeduplicatedCollection[Address]):
    """The targets that own a Python module."""

    sort_input = True


@rule
async def map_module_to_addresses(
    module: PythonModule,
    first_party_mapping: FirstPartyModuleToAddressMapping,
    third_party_mapping: ThirdPartyModuleToAddressMapping,
) -> PythonModuleOwners:
    third_party_address = third_party_mapping.address_for_module(module.module)
    if third_party_address:
        return PythonModuleOwners([third_party_address])
    first_party_address = first_party_mapping.address_for_module(module.module)
    if first_party_address:
        return PythonModuleOwners([first_party_address])
    return PythonModuleOwners()


def rules():
    return [
        map_first_party_modules_to_addresses,
        map_third_party_modules_to_addresses,
        map_module_to_addresses,
    ]
