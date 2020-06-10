# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, Iterator, Optional

from pants.backend.python.target_types import PythonRequirementsField, PythonSources
from pants.base.specs import AddressSpecs, AscendantAddresses, DescendantAddresses
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSourcesFieldRequest,
)
from pants.engine.addresses import Address
from pants.engine.collection import DeduplicatedCollection
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Targets
from pants.python.python_setup import PythonSetup
from pants.source.source_root import AllSourceRoots
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

    @property
    def name_as_path(self) -> PurePath:
        return PurePath(self.module.replace(".", "/"))

    def address_spec(self, *, source_root: str) -> AscendantAddresses:
        """The spec for all candidate targets which could feasibly own the module.

        This uses AscendantAddresses because targets can own files in subdirs (e.g. rglobs). We also
        use the package path, e.g. `helloworld/util/__init__.py`, rather than the module path to
        ensure that we capture all possible targets. It is okay if this directory does not actually
        exist.
        """
        return AscendantAddresses(directory=str(PurePath(source_root) / self.name_as_path))

    def possible_stripped_paths(self) -> Iterator[PurePath]:
        """Given a module like `helloworld.util`, convert it back to its possible paths.

        Each module has either 2 or 4 possible paths. For example, given the module
        `helloworld.util`:

        - helloworld/util.py
        - helloworld/util/__init__.py
        - helloworld.py
        - helloworld/__init__.py

        The last two possible paths look at the parent module, if any. This is to accommodate `from`
        imports, where we don't care about the specific symbol, but only the module. For example,
        with `from typing import List`, we only care about `typing`.
        """
        module_name_with_slashes = PurePath(self.module.replace(".", "/"))
        yield self.name_as_path.with_suffix(".py")
        yield self.name_as_path / "__init__.py"
        parent = module_name_with_slashes.parent
        if str(parent) != ".":
            yield parent.with_suffix(".py")
            yield parent / "__init__.py"


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
async def map_third_party_modules_to_addresses(
    python_setup: PythonSetup,
) -> ThirdPartyModuleToAddressMapping:
    all_targets = await Get[Targets](AddressSpecs([DescendantAddresses("")]))
    # NB: If >1 targets have the same distribution, we do not record the distribution. This is to
    # avoid ambiguity.
    requirements_to_addresses: Dict[str, Address] = {}
    for tgt in all_targets:
        if not tgt.has_field(PythonRequirementsField):
            continue
        for python_req in tgt[PythonRequirementsField].value:
            req_name = python_req.project_name
            if req_name in requirements_to_addresses:
                requirements_to_addresses.pop(req_name)
            else:
                requirements_to_addresses[req_name] = tgt.address
    return ThirdPartyModuleToAddressMapping(
        FrozenDict(
            {
                module: requirements_to_addresses[requirement]
                for requirement, modules in python_setup.thirdparty_modules_mapping.items()
                for module in modules
                if requirement in requirements_to_addresses
            }
        )
    )


class PythonModuleOwners(DeduplicatedCollection[Address]):
    """The targets that own a Python module."""

    sort_input = True


@rule
async def map_python_module_to_targets(
    module: PythonModule,
    source_roots: AllSourceRoots,
    third_party_mapping: ThirdPartyModuleToAddressMapping,
) -> PythonModuleOwners:
    third_party_address = third_party_mapping.address_for_module(module.module)
    if third_party_address:
        return PythonModuleOwners([third_party_address])
    unfiltered_candidate_targets = await Get[Targets](
        AddressSpecs(module.address_spec(source_root=src_root.path) for src_root in source_roots)
    )
    candidate_targets = tuple(
        tgt for tgt in unfiltered_candidate_targets if tgt.has_field(PythonSources)
    )
    sources_per_target = await MultiGet(
        Get[SourceRootStrippedSources](StripSourcesFieldRequest(tgt[PythonSources]))
        for tgt in candidate_targets
    )
    candidate_files = {str(p) for p in module.possible_stripped_paths()}
    return PythonModuleOwners(
        tgt.address
        for tgt, sources in zip(candidate_targets, sources_per_target)
        if bool(candidate_files.intersection(sources.snapshot.files))
    )


def rules():
    return [
        map_python_module_to_targets,
        map_third_party_modules_to_addresses,
        SubsystemRule(PythonSetup),
    ]
