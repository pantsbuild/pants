# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import functools
import itertools
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from functools import total_ordering
from pathlib import PurePath
from typing import DefaultDict, Iterable, Mapping, Tuple

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.dependency_inference.default_module_mapping import (
    DEFAULT_MODULE_MAPPING,
    DEFAULT_MODULE_PATTERN_MAPPING,
    DEFAULT_TYPE_STUB_MODULE_MAPPING,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementResolveField,
    PythonRequirementsField,
    PythonRequirementTypeStubModulesField,
    PythonResolveField,
    PythonSourceField,
)
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.addresses import Address
from pants.engine.environment import EnvironmentName
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import AllTargets, Target
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


ResolveName = str


@total_ordering
class ModuleProviderType(enum.Enum):
    TYPE_STUB = enum.auto()
    IMPL = enum.auto()

    def __lt__(self, other) -> bool:
        if not isinstance(other, ModuleProviderType):
            return NotImplemented
        return self.name < other.name


@dataclass(frozen=True, order=True)
class ModuleProvider:
    addr: Address
    typ: ModuleProviderType


@dataclass(frozen=True, order=True)
class PossibleModuleProvider:
    provider: ModuleProvider
    # 0 = The provider mapped to the module itself, 1 = the provider mapped to its parent, etc.
    ancestry: int


def module_from_stripped_path(path: PurePath) -> str:
    module_name_with_slashes = (
        path.parent if path.name in ("__init__.py", "__init__.pyi") else path.with_suffix("")
    )
    return module_name_with_slashes.as_posix().replace("/", ".")


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


class FirstPartyPythonMappingImpl(
    FrozenDict[ResolveName, FrozenDict[str, Tuple[ModuleProvider, ...]]]
):
    """A mapping of each resolve name to the first-party module names contained and their owning
    addresses.

    This contains the modules from a specific implementation, e.g. a codegen backend. All
    implementations then get merged.
    """

    @classmethod
    def create(
        cls,
        resolves_to_modules_to_providers: Mapping[
            ResolveName, Mapping[str, Iterable[ModuleProvider]]
        ],
    ) -> FirstPartyPythonMappingImpl:
        return FirstPartyPythonMappingImpl(
            (
                resolve,
                FrozenDict(
                    (mod, tuple(sorted(providers))) for mod, providers in sorted(mapping.items())
                ),
            )
            for resolve, mapping in sorted(resolves_to_modules_to_providers.items())
        )


@union(in_scope_types=[EnvironmentName])
class FirstPartyPythonMappingImplMarker:
    """An entry point for a specific implementation of mapping module names to owning targets for
    Python import dependency inference.

    All implementations will be merged together. Any modules that show up in multiple
    implementations will be marked ambiguous.
    """


@dataclass(frozen=True)
class FirstPartyPythonModuleMapping:
    resolves_to_modules_to_providers: FrozenDict[
        ResolveName, FrozenDict[str, Tuple[ModuleProvider, ...]]
    ]

    """A merged mapping of each resolve name to the first-party module names contained and their
    owning addresses.

    This mapping may have been constructed from multiple distinct implementations, e.g.
    implementations for each codegen backends.
    """

    def _providers_for_resolve(
        self, module: str, resolve: str
    ) -> tuple[PossibleModuleProvider, ...]:
        mapping = self.resolves_to_modules_to_providers.get(resolve)
        if not mapping:
            return ()

        result = mapping.get(module, ())
        if result:
            return tuple(PossibleModuleProvider(provider, 0) for provider in result)

        # If the module is not found, try the parent, if any. This is to handle `from` imports
        # where the "module" we were handed was actually a symbol inside the module.
        # E.g., with `from my_project.app import App`, we would be passed "my_project.app.App".
        #
        # We do not look past the direct parent, as this could cause multiple ambiguous owners to
        # be resolved. This contrasts with the third-party module mapping, which will try every
        # ancestor.
        # TODO: Now that we capture the ancestry, we could look past the direct parent.
        #  One reason to do so would be to unify more of the FirstParty and ThirdParty impls.
        if "." not in module:
            return ()
        parent_module = module.rsplit(".", maxsplit=1)[0]
        parent_providers = mapping.get(parent_module, ())
        return tuple(PossibleModuleProvider(mp, 1) for mp in parent_providers)

    def providers_for_module(
        self, module: str, resolve: str | None
    ) -> tuple[PossibleModuleProvider, ...]:
        """Find all providers for the module.

        If `resolve` is None, will not consider resolves, i.e. any `python_source` et al can be
        used. Otherwise, providers can only come from first-party targets with the resolve.
        """
        if resolve:
            return self._providers_for_resolve(module, resolve)
        return tuple(
            itertools.chain.from_iterable(
                self._providers_for_resolve(module, resolve)
                for resolve in list(self.resolves_to_modules_to_providers.keys())
            )
        )


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
    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))
    for mapping_impl in all_mappings:
        for resolve, modules_to_providers in mapping_impl.items():
            for module, providers in modules_to_providers.items():
                resolves_to_modules_to_providers[resolve][module].extend(providers)
    return FirstPartyPythonModuleMapping(
        FrozenDict(
            (
                resolve,
                FrozenDict(
                    (mod, tuple(sorted(providers))) for mod, providers in sorted(mapping.items())
                ),
            )
            for resolve, mapping in sorted(resolves_to_modules_to_providers.items())
        )
    )


# This is only used to register our implementation with the plugin hook via unions. Note that we
# implement this like any other plugin implementation so that we can run them all in parallel.
class FirstPartyPythonTargetsMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


@rule(desc="Creating map of first party Python targets to Python modules", level=LogLevel.DEBUG)
async def map_first_party_python_targets_to_modules(
    _: FirstPartyPythonTargetsMappingMarker,
    all_python_targets: AllPythonTargets,
    python_setup: PythonSetup,
) -> FirstPartyPythonMappingImpl:
    stripped_file_per_target = await MultiGet(
        Get(StrippedFileName, StrippedFileNameRequest(tgt[PythonSourceField].file_path))
        for tgt in all_python_targets.first_party
    )

    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))
    for tgt, stripped_file in zip(all_python_targets.first_party, stripped_file_per_target):
        resolve = tgt[PythonResolveField].normalized_value(python_setup)
        stripped_f = PurePath(stripped_file.value)
        provider_type = (
            ModuleProviderType.TYPE_STUB if stripped_f.suffix == ".pyi" else ModuleProviderType.IMPL
        )
        module = module_from_stripped_path(stripped_f)
        resolves_to_modules_to_providers[resolve][module].append(
            ModuleProvider(tgt.address, provider_type)
        )

    return FirstPartyPythonMappingImpl.create(resolves_to_modules_to_providers)


# -----------------------------------------------------------------------------------------------
# Third party module mapping
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThirdPartyPythonModuleMapping:
    """A mapping of each resolve to the modules they contain and the addresses providing those
    modules."""

    resolves_to_modules_to_providers: FrozenDict[
        ResolveName, FrozenDict[str, Tuple[ModuleProvider, ...]]
    ]

    def _providers_for_resolve(
        self, module: str, resolve: str, ancestry: int = 0
    ) -> tuple[PossibleModuleProvider, ...]:
        mapping = self.resolves_to_modules_to_providers.get(resolve)
        if not mapping:
            return ()

        result = mapping.get(module, ())
        if result:
            return tuple(PossibleModuleProvider(mp, ancestry) for mp in result)

        # If the module is not found, recursively try the ancestor modules, if any. For example,
        # pants.task.task.Task -> pants.task.task -> pants.task -> pants
        if "." not in module:
            return ()
        parent_module = module.rsplit(".", maxsplit=1)[0]
        return self._providers_for_resolve(parent_module, resolve, ancestry + 1)

    def providers_for_module(
        self, module: str, resolve: str | None
    ) -> tuple[PossibleModuleProvider, ...]:
        """Find all providers for the module.

        If `resolve` is None, will not consider resolves, i.e. any `python_requirement` can be
        consumed. Otherwise, providers can only come from `python_requirements` with the resolve.
        """
        if resolve:
            return self._providers_for_resolve(module, resolve)
        return tuple(
            itertools.chain.from_iterable(
                self._providers_for_resolve(module, resolve)
                for resolve in list(self.resolves_to_modules_to_providers.keys())
            )
        )


@functools.cache
def generate_mappings_from_pattern(proj_name: str) -> Iterable[str]:
    """Generate an iterable of possible module mappings from a project name using a regex pattern.

    e.g. google-cloud-foo -> [google.cloud.foo, google.cloud.foo_v1, google.cloud.foo_v2]
    Should eliminate the need to "manually" add a mapping for every service
    proj_name: The project name to generate mappings for e.g google-cloud-datastream
    """
    pattern_values = []
    for match_pattern, replace_patterns in DEFAULT_MODULE_PATTERN_MAPPING.items():
        if match_pattern.match(proj_name) is not None:
            pattern_values = [
                match_pattern.sub(replace_pattern, proj_name)
                for replace_pattern in replace_patterns
            ]
            break  # stop after the first match in the rare chance that there are multiple matches
    return pattern_values


@functools.cache
def generate_mappings(proj_name: str, fallback_value: str) -> Iterable[str]:
    """Will try the default mapping first and if no mapping is found, try the pattern match.

    Always append the fallback value.
    """
    mappings = list(
        DEFAULT_MODULE_MAPPING.get(proj_name, generate_mappings_from_pattern(proj_name))
    )
    mappings.append(fallback_value)
    return mappings


@rule(desc="Creating map of third party targets to Python modules", level=LogLevel.DEBUG)
async def map_third_party_modules_to_addresses(
    all_python_targets: AllPythonTargets,
    python_setup: PythonSetup,
) -> ThirdPartyPythonModuleMapping:
    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))

    for tgt in all_python_targets.third_party:
        resolve = tgt[PythonRequirementResolveField].normalized_value(python_setup)

        def add_modules(modules: Iterable[str], *, type_stub: bool = False) -> None:
            for module in modules:
                resolves_to_modules_to_providers[resolve][module].append(
                    ModuleProvider(
                        tgt.address,
                        ModuleProviderType.TYPE_STUB if type_stub else ModuleProviderType.IMPL,
                    )
                )

        explicit_modules = tgt.get(PythonRequirementModulesField).value
        if explicit_modules:
            add_modules(explicit_modules)
            continue

        explicit_stub_modules = tgt.get(PythonRequirementTypeStubModulesField).value
        if explicit_stub_modules:
            add_modules(explicit_stub_modules, type_stub=True)
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
                add_modules(stub_modules, type_stub=True)
            else:
                add_modules(generate_mappings(proj_name, fallback_value))

    return ThirdPartyPythonModuleMapping(
        FrozenDict(
            (
                resolve,
                FrozenDict(
                    (mod, tuple(sorted(providers))) for mod, providers in sorted(mapping.items())
                ),
            )
            for resolve, mapping in sorted(resolves_to_modules_to_providers.items())
        )
    )


# -----------------------------------------------------------------------------------------------
# module -> owners
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonModuleOwners:
    """The target(s) that own a Python module.

    Up to 2 targets can unambiguously own the same module, if one is an implementation and the other
    is a .pyi type stub. It is ambiguous for >1 implementation target to own the same module, and
    those targets will be put into `ambiguous` instead of `unambiguous`. Therefore, `unambiguous`
    should never be >2; and only 1 of `unambiguous` and `ambiguous` should have targets.
    """

    unambiguous: tuple[Address, ...]
    ambiguous: tuple[Address, ...] = ()

    def __post_init__(self) -> None:
        if self.unambiguous and self.ambiguous:
            raise AssertionError(
                softwrap(
                    """
                    A module has both unambiguous and ambiguous owners, which is a bug in the
                    dependency inference code. Please file a bug report at
                    https://github.com/pantsbuild/pants/issues/new.
                    """
                )
            )


@dataclass(frozen=True)
class PythonModuleOwnersRequest:
    module: str
    resolve: str | None
    # If specified, resolve ambiguity by choosing the symbol provider with the
    # closest common ancestor to this path. Must be a path relative to the build root.
    locality: str | None = None


@rule
async def map_module_to_address(
    request: PythonModuleOwnersRequest,
    first_party_mapping: FirstPartyPythonModuleMapping,
    third_party_mapping: ThirdPartyPythonModuleMapping,
) -> PythonModuleOwners:
    possible_providers: tuple[PossibleModuleProvider, ...] = (
        *third_party_mapping.providers_for_module(request.module, resolve=request.resolve),
        *first_party_mapping.providers_for_module(request.module, resolve=request.resolve),
    )

    # We first attempt to disambiguate conflicting providers by taking - for each provider type -
    # the providers of the closest ancestors to the requested modules.
    # E.g., if we have a provider for foo.bar and for foo.bar.baz, prefer the latter.
    # This prevents issues with namespace packages that are split between first-party and
    # third-party (e.g., https://github.com/pantsbuild/pants/discussions/17286).

    # Map from provider type to mutable pair of
    # [closest ancestry, list of provider of that type at that ancestry level].
    type_to_closest_providers: dict[ModuleProviderType, list] = defaultdict(lambda: [999, []])
    for possible_provider in possible_providers:
        val = type_to_closest_providers[possible_provider.provider.typ]
        if possible_provider.ancestry < val[0]:
            val[0] = possible_provider.ancestry
            val[1] = []
        # NB This must come after the < check above, so we handle the possible_provider
        # that caused that check to pass.
        if possible_provider.ancestry == val[0]:
            val[1].append(possible_provider.provider)

    if request.locality:
        # For each provider type, if we have more than one provider left, prefer
        # the one with the closest common ancestor to the requester.
        for val in type_to_closest_providers.values():
            providers = val[1]
            if len(providers) < 2:
                continue
            providers_with_closest_common_ancestor: list[ModuleProvider] = []
            closest_common_ancestor_len = 0
            for provider in providers:
                common_ancestor_len = len(
                    os.path.commonpath([request.locality, provider.addr.spec_path])
                )
                if common_ancestor_len > closest_common_ancestor_len:
                    closest_common_ancestor_len = common_ancestor_len
                    providers_with_closest_common_ancestor = []
                if common_ancestor_len == closest_common_ancestor_len:
                    providers_with_closest_common_ancestor.append(provider)
            providers[:] = providers_with_closest_common_ancestor

    remaining_providers: list[ModuleProvider] = list(
        itertools.chain(*[val[1] for val in type_to_closest_providers.values()])
    )
    addresses = tuple(provider.addr for provider in remaining_providers)
    # Check that we have at most one remaining provider for each provider type.
    # If we have more than one, signal ambiguity.
    if any(len(val[1]) > 1 for val in type_to_closest_providers.values()):
        return PythonModuleOwners((), ambiguous=addresses)

    return PythonModuleOwners(addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, FirstPartyPythonTargetsMappingMarker),
    )
