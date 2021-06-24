# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.target_types import (
    ModuleMappingField,
    PythonRequirementsField,
    PythonSources,
)
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.stripped_source_files import StrippedSourceFileNames
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesPathsRequest, Targets
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class FirstPartyPythonMappingImpl:
    """A mapping of module names to owning addresses that a specific implementation adds for Python
    import dependency inference.

    For almost every implementation, there should only be one address per module to avoid ambiguity.
    However, the built-in implementation allows for 2 addresses when `.pyi` type stubs are used.

    All ambiguous modules must be added to `ambiguous_modules` and not be included in `mapping`.
    """

    mapping: FrozenDict[str, tuple[Address, ...]]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]


@union
class FirstPartyPythonMappingImplMarker:
    """An entry point for a specific implementation of mapping module names to owning targets for
    Python import dependency inference.

    All implementations will be merged together. Any modules that show up in multiple
    implementations will be marked ambiguous.

    The addresses should all be file addresses, rather than BUILD addresses.
    """


@dataclass(frozen=True)
class FirstPartyPythonModuleMapping:
    """A merged mapping of module names to owning addresses.

    This mapping may have been constructed from multiple distinct implementations, e.g.
    implementations for each codegen backends.
    """

    mapping: FrozenDict[str, tuple[Address, ...]]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]

    def addresses_for_module(self, module: str) -> tuple[tuple[Address, ...], tuple[Address, ...]]:
        """Return all unambiguous and ambiguous addresses.

        The unambiguous addresses should be 0-2, but not more. We only expect 2 if there is both an
        implementation (.py) and type stub (.pyi) with the same module name.
        """
        unambiguous = self.mapping.get(module, ())
        ambiguous = self.ambiguous_modules.get(module, ())
        if unambiguous or ambiguous:
            return unambiguous, ambiguous

        # If the module is not found, try the parent, if any. This is to accommodate `from`
        # imports, where we don't care about the specific symbol, but only the module. For example,
        # with `from my_project.app import App`, we only care about the `my_project.app` part.
        #
        # We do not look past the direct parent, as this could cause multiple ambiguous owners to
        # be resolved. This contrasts with the third-party module mapping, which will try every
        # ancestor.
        if "." not in module:
            return (), ()
        parent_module = module.rsplit(".", maxsplit=1)[0]
        unambiguous = self.mapping.get(parent_module, ())
        ambiguous = self.ambiguous_modules.get(parent_module, ())
        return unambiguous, ambiguous


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

    # First, record all known ambiguous modules. We will need to check that an implementation's
    # module is not ambiguous within another implementation.
    modules_with_multiple_implementations: DefaultDict[str, set[Address]] = defaultdict(set)
    for mapping_impl in all_mappings:
        for module, addresses in mapping_impl.ambiguous_modules.items():
            modules_with_multiple_implementations[module].update(addresses)

    # Then, merge the unambiguous modules within each MappingImpls while checking for ambiguity
    # across the other implementations.
    modules_to_addresses: dict[str, tuple[Address, ...]] = {}
    for mapping_impl in all_mappings:
        for module, addresses in mapping_impl.mapping.items():
            if module in modules_with_multiple_implementations:
                modules_with_multiple_implementations[module].update(addresses)
            elif module in modules_to_addresses:
                modules_with_multiple_implementations[module].update(
                    {*modules_to_addresses[module], *addresses}
                )
            else:
                modules_to_addresses[module] = addresses

    # Finally, remove any newly ambiguous modules from the previous step.
    for module in modules_with_multiple_implementations:
        if module in modules_to_addresses:
            modules_to_addresses.pop(module)

    return FirstPartyPythonModuleMapping(
        mapping=FrozenDict(sorted(modules_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(modules_with_multiple_implementations.items())
        ),
    )


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

    modules_to_addresses: DefaultDict[str, list[Address]] = defaultdict(list)
    modules_with_multiple_implementations: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt, stripped_sources in zip(python_targets, stripped_sources_per_target):
        for stripped_f in stripped_sources:
            module = PythonModule.create_from_stripped_path(PurePath(stripped_f)).module
            if module in modules_to_addresses:
                # We check if one of the targets is an implementation (.py file) and the other is
                # a type stub (.pyi file), which we allow. Otherwise, we have ambiguity.
                prior_is_type_stub = len(
                    modules_to_addresses[module]
                ) == 1 and modules_to_addresses[module][0].filename.endswith(".pyi")
                current_is_type_stub = tgt.address.filename.endswith(".pyi")
                if prior_is_type_stub ^ current_is_type_stub:
                    modules_to_addresses[module].append(tgt.address)
                else:
                    modules_with_multiple_implementations[module].update(
                        {*modules_to_addresses[module], tgt.address}
                    )
            else:
                modules_to_addresses[module].append(tgt.address)

    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_implementations:
        modules_to_addresses.pop(module)

    return FirstPartyPythonMappingImpl(
        mapping=FrozenDict((k, tuple(sorted(v))) for k, v in sorted(modules_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(modules_with_multiple_implementations.items())
        ),
    )


# -----------------------------------------------------------------------------------------------
# Third party module mapping
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThirdPartyPythonModuleMapping:
    mapping: FrozenDict[str, Address]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]

    def address_for_module(self, module: str) -> tuple[Address | None, tuple[Address, ...]]:
        """Return the unambiguous owner (if any) and all ambiguous addresses."""
        unambiguous = self.mapping.get(module)
        ambiguous = self.ambiguous_modules.get(module, ())
        if unambiguous or ambiguous:
            return unambiguous, ambiguous

        # If the module is not found, recursively try the ancestor modules, if any. For example,
        # pants.task.task.Task -> pants.task.task -> pants.task -> pants
        if "." not in module:
            return None, ()
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return self.address_for_module(parent_module)


@rule(desc="Creating map of third party targets to Python modules", level=LogLevel.DEBUG)
async def map_third_party_modules_to_addresses() -> ThirdPartyPythonModuleMapping:
    all_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    modules_to_addresses: dict[str, Address] = {}
    modules_with_multiple_owners: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt in all_targets:
        if not tgt.has_field(PythonRequirementsField):
            continue
        module_map = tgt.get(ModuleMappingField).value
        for req in tgt[PythonRequirementsField].value:
            modules = module_map.get(
                # NB: We only use `canonicalize_project_name()` for the key, but not the fallback
                # value, because we want to preserve `.` in the module name. See
                # https://www.python.org/dev/peps/pep-0503/#normalized-names.
                canonicalize_project_name(req.project_name),
                [req.project_name.lower().replace("-", "_")],
            )
            for module in modules:
                if module in modules_to_addresses:
                    modules_with_multiple_owners[module].update(
                        {modules_to_addresses[module], tgt.address}
                    )
                else:
                    modules_to_addresses[module] = tgt.address
    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_owners:
        modules_to_addresses.pop(module)
    return ThirdPartyPythonModuleMapping(
        mapping=FrozenDict(sorted(modules_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(modules_with_multiple_owners.items())
        ),
    )


# -----------------------------------------------------------------------------------------------
# module -> owners
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonModuleOwners:
    """The target(s) that own a Python module.

    If >1 targets own the same module, and they're implementations (vs .pyi type stubs), they will
    be put into `ambiguous` instead of `unambiguous`. `unambiguous` should never be > 2.
    """

    unambiguous: tuple[Address, ...]
    ambiguous: tuple[Address, ...] = ()

    def __post_init__(self) -> None:
        if self.unambiguous and self.ambiguous:
            raise AssertionError(
                "A module has both unambiguous and ambiguous owners, which is a bug in the "
                "dependency inference code. Please file a bug report at "
                "https://github.com/pantsbuild/pants/issues/new."
            )


@rule
async def map_module_to_address(
    module: PythonModule,
    first_party_mapping: FirstPartyPythonModuleMapping,
    third_party_mapping: ThirdPartyPythonModuleMapping,
) -> PythonModuleOwners:
    third_party_address, third_party_ambiguous = third_party_mapping.address_for_module(
        module.module
    )
    first_party_addresses, first_party_ambiguous = first_party_mapping.addresses_for_module(
        module.module
    )

    # First, check if there was any ambiguity within the first-party or third-party mappings. Note
    # that even if there's ambiguity purely within either third-party or first-party, all targets
    # with that module become ambiguous.
    if third_party_ambiguous or first_party_ambiguous:
        ambiguous = {*third_party_ambiguous, *first_party_ambiguous, *first_party_addresses}
        if third_party_address:
            ambiguous.add(third_party_address)
        return PythonModuleOwners((), ambiguous=tuple(sorted(ambiguous)))

    # It's possible for a user to write type stubs (`.pyi` files) for their third-party
    # dependencies. We check if that happened, but we're strict in validating that there is only a
    # single third party address and a single first-party address referring to a `.pyi` file;
    # otherwise, we have ambiguous implementations.
    if third_party_address and not first_party_addresses:
        return PythonModuleOwners((third_party_address,))
    first_party_is_type_stub = len(first_party_addresses) == 1 and first_party_addresses[
        0
    ].filename.endswith(".pyi")
    if third_party_address and first_party_is_type_stub:
        return PythonModuleOwners((third_party_address, *first_party_addresses))
    # Else, we have ambiguity between the third-party and first-party addresses.
    if third_party_address and first_party_addresses:
        return PythonModuleOwners(
            (), ambiguous=tuple(sorted((third_party_address, *first_party_addresses)))
        )

    # We're done with looking at third-party addresses, and now solely look at first-party, which
    # was already validated for ambiguity.
    if first_party_addresses:
        return PythonModuleOwners(first_party_addresses)
    return PythonModuleOwners(())


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, FirstPartyPythonTargetsMappingMarker),
    )
