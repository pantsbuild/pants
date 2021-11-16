# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.dependency_inference.default_module_mapping import (
    DEFAULT_MODULE_MAPPING,
    DEFAULT_TYPE_STUB_MODULE_MAPPING,
)
from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementsField,
    PythonRequirementTypeStubModulesField,
    PythonSourceField,
)
from pants.core.util_rules.stripped_source_files import StrippedSourceFileNames
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import AllTargets, SourcesPathsRequest, Target
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

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


@dataclass(frozen=True)
class AllPythonTargets:
    first_party: tuple[Target, ...]
    third_party: tuple[Target, ...]


@rule(desc="Find all Python targets in project", level=LogLevel.DEBUG)
def find_all_python_projects(all_targets: AllTargets) -> AllPythonTargets:
    first_party = []
    third_party = []
    for tgt in all_targets:
        if tgt.has_field(PythonSourceField):
            first_party.append(tgt)
        if tgt.has_field(PythonRequirementsField):
            third_party.append(tgt)
    return AllPythonTargets(tuple(first_party), tuple(third_party))


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
    modules_with_type_stub: FrozenOrderedSet[str] = FrozenOrderedSet()


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
    modules_with_type_stub: FrozenOrderedSet[str] = FrozenOrderedSet()

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

    def has_type_stub(self, module: str) -> bool:
        if module in self.modules_with_type_stub:
            return True

        # Also check for the parent module if relevant. See self.addresses_for_module.
        if "." not in module:
            return False
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return parent_module in self.modules_with_type_stub


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

    # First, record all known ambiguous modules.
    modules_with_multiple_implementations: DefaultDict[str, set[Address]] = defaultdict(set)
    for mapping_impl in all_mappings:
        for module, addresses in mapping_impl.ambiguous_modules.items():
            modules_with_multiple_implementations[module].update(addresses)

    # Then, merge the unambiguous modules within each MappingImpls while checking for ambiguity
    # across the other implementations.
    modules_to_addresses: dict[str, tuple[Address, ...]] = {}
    modules_with_type_stub: set[str] = set()
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
                if module in mapping_impl.modules_with_type_stub:
                    modules_with_type_stub.add(module)

    # Finally, remove any newly ambiguous modules from the previous step.
    for module in modules_with_multiple_implementations:
        if module in modules_to_addresses:
            modules_to_addresses.pop(module)
            modules_with_type_stub.discard(module)

    return FirstPartyPythonModuleMapping(
        mapping=FrozenDict(sorted(modules_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(modules_with_multiple_implementations.items())
        ),
        modules_with_type_stub=FrozenOrderedSet(modules_with_type_stub),
    )


# This is only used to register our implementation with the plugin hook via unions. Note that we
# implement this like any other plugin implementation so that we can run them all in parallel.
class FirstPartyPythonTargetsMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


@rule(desc="Creating map of first party Python targets to Python modules", level=LogLevel.DEBUG)
async def map_first_party_python_targets_to_modules(
    _: FirstPartyPythonTargetsMappingMarker, all_python_targets: AllPythonTargets
) -> FirstPartyPythonMappingImpl:
    stripped_sources_per_target = await MultiGet(
        Get(StrippedSourceFileNames, SourcesPathsRequest(tgt[PythonSourceField]))
        for tgt in all_python_targets.first_party
    )

    modules_to_addresses: DefaultDict[str, list[Address]] = defaultdict(list)
    modules_with_type_stub: set[str] = set()
    modules_with_multiple_implementations: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt, stripped_sources in zip(all_python_targets.first_party, stripped_sources_per_target):
        # `PythonSourceFile` validates that each target has exactly one file.
        assert len(stripped_sources) == 1
        stripped_f = PurePath(stripped_sources[0])
        is_type_stub = stripped_f.suffix == ".pyi"

        module = PythonModule.create_from_stripped_path(stripped_f).module
        if module not in modules_to_addresses:
            modules_to_addresses[module].append(tgt.address)
            if is_type_stub:
                modules_with_type_stub.add(module)
            continue

        # Else, possible ambiguity. Check if one of the targets is an implementation
        # (.py file) and the other is a type stub (.pyi file), which we allow. Otherwise, it's
        # ambiguous.
        prior_is_type_stub = (
            len(modules_to_addresses[module]) == 1 and module in modules_with_type_stub
        )
        if is_type_stub ^ prior_is_type_stub:
            modules_to_addresses[module].append(tgt.address)
            if is_type_stub:
                modules_with_type_stub.add(module)
        else:
            modules_with_multiple_implementations[module].update(
                {*modules_to_addresses[module], tgt.address}
            )

    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_implementations:
        modules_to_addresses.pop(module)
        modules_with_type_stub.discard(module)

    return FirstPartyPythonMappingImpl(
        mapping=FrozenDict((k, tuple(sorted(v))) for k, v in sorted(modules_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(modules_with_multiple_implementations.items())
        ),
        modules_with_type_stub=FrozenOrderedSet(modules_with_type_stub),
    )


# -----------------------------------------------------------------------------------------------
# Third party module mapping
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThirdPartyPythonModuleMapping:
    mapping: FrozenDict[str, tuple[Address, ...]]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]

    def addresses_for_module(self, module: str) -> tuple[tuple[Address, ...], tuple[Address, ...]]:
        """Return all unambiguous and ambiguous addresses.

        The unambiguous addresses should be 0-2, but not more. We only expect 2 if there is both an
        implementation and type stub with the same module name.
        """
        unambiguous = self.mapping.get(module, ())
        ambiguous = self.ambiguous_modules.get(module, ())
        if unambiguous or ambiguous:
            return unambiguous, ambiguous

        # If the module is not found, recursively try the ancestor modules, if any. For example,
        # pants.task.task.Task -> pants.task.task -> pants.task -> pants
        if "." not in module:
            return (), ()
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return self.addresses_for_module(parent_module)


@rule(desc="Creating map of third party targets to Python modules", level=LogLevel.DEBUG)
async def map_third_party_modules_to_addresses(
    all_python_tgts: AllPythonTargets,
) -> ThirdPartyPythonModuleMapping:
    modules_to_addresses: dict[str, Address] = {}
    modules_to_stub_addresses: dict[str, Address] = {}
    modules_with_multiple_owners: DefaultDict[str, set[Address]] = defaultdict(set)

    def add_modules(modules: tuple[str, ...], address: Address) -> None:
        for module in modules:
            if module in modules_with_multiple_owners:
                modules_with_multiple_owners[module].add(address)
            elif module in modules_to_addresses:
                modules_with_multiple_owners[module].update({modules_to_addresses[module], address})
            else:
                modules_to_addresses[module] = address

    def add_stub_modules(modules: tuple[str, ...], address: Address) -> None:
        for module in modules:
            if module in modules_with_multiple_owners:
                modules_with_multiple_owners[module].add(address)
            elif module in modules_to_stub_addresses:
                modules_with_multiple_owners[module].update(
                    {modules_to_stub_addresses[module], address}
                )
            else:
                modules_to_stub_addresses[module] = address

    for tgt in all_python_tgts.third_party:
        explicit_modules = tgt.get(PythonRequirementModulesField).value
        if explicit_modules:
            add_modules(explicit_modules, tgt.address)
            continue

        explicit_stub_modules = tgt.get(PythonRequirementTypeStubModulesField).value
        if explicit_stub_modules:
            add_stub_modules(explicit_stub_modules, tgt.address)
            continue

        # Else, fall back to defaults.
        for req in tgt[PythonRequirementsField].value:
            # NB: We don't use `canonicalize_project_name()` for the fallback value because we
            # want to preserve `.` in the module name. See
            # https://www.python.org/dev/peps/pep-0503/#normalized-names.
            proj_name = canonicalize_project_name(req.project_name)
            fallback_value = req.project_name.strip().lower().replace("-", "_")

            in_stubs_map = proj_name in DEFAULT_TYPE_STUB_MODULE_MAPPING
            starts_with_prefix = fallback_value.startswith(("types_", "stubs_"))
            ends_with_prefix = fallback_value.endswith(("_types", "_stubs"))
            if proj_name not in DEFAULT_MODULE_MAPPING and (
                in_stubs_map or starts_with_prefix or ends_with_prefix
            ):
                if in_stubs_map:
                    stub_modules = DEFAULT_TYPE_STUB_MODULE_MAPPING[proj_name]
                else:
                    stub_modules = (
                        fallback_value[6:] if starts_with_prefix else fallback_value[:-6],
                    )
                add_stub_modules(stub_modules, tgt.address)
            else:
                add_modules(DEFAULT_MODULE_MAPPING.get(proj_name, (fallback_value,)), tgt.address)

    # Remove modules with ambiguous owners.
    for module in modules_with_multiple_owners:
        if module in modules_to_addresses:
            modules_to_addresses.pop(module)
        if module in modules_to_stub_addresses:
            modules_to_stub_addresses.pop(module)

    merged_mapping: DefaultDict[str, list[Address]] = defaultdict(list)
    for k, v in modules_to_addresses.items():
        merged_mapping[k].append(v)
    for k, v in modules_to_stub_addresses.items():
        merged_mapping[k].append(v)

    return ThirdPartyPythonModuleMapping(
        mapping=FrozenDict((k, tuple(sorted(v))) for k, v in sorted(merged_mapping.items())),
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
    third_party_addresses, third_party_ambiguous = third_party_mapping.addresses_for_module(
        module.module
    )
    first_party_addresses, first_party_ambiguous = first_party_mapping.addresses_for_module(
        module.module
    )

    # First, check if there was any ambiguity within the first-party or third-party mappings. Note
    # that even if there's ambiguity purely within either third-party or first-party, all targets
    # with that module become ambiguous.
    if third_party_ambiguous or first_party_ambiguous:
        ambiguous = {
            *first_party_ambiguous,
            *first_party_addresses,
            *third_party_ambiguous,
            *third_party_addresses,
        }
        return PythonModuleOwners((), ambiguous=tuple(sorted(ambiguous)))

    # It's possible for a user to write type stubs (`.pyi` files) for their third-party
    # dependencies. We check if that happened, but we're strict in validating that there is only a
    # single third party address and a single first-party address referring to a `.pyi` file;
    # otherwise, we have ambiguous implementations.
    if third_party_addresses and not first_party_addresses:
        return PythonModuleOwners(third_party_addresses)
    if (
        len(third_party_addresses) == 1
        and len(first_party_addresses) == 1
        and first_party_mapping.has_type_stub(module.module)
    ):
        return PythonModuleOwners((*third_party_addresses, *first_party_addresses))
    # Else, we have ambiguity between the third-party and first-party addresses.
    if third_party_addresses and first_party_addresses:
        return PythonModuleOwners(
            (), ambiguous=tuple(sorted((*third_party_addresses, *first_party_addresses)))
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
