# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Callable, Iterable

from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwners,
    PythonModuleOwnersRequest,
)
from pants.backend.python.target_types import (
    EntryPoint,
    PythonDistribution,
    PythonDistributionDependenciesField,
    PythonDistributionEntryPoint,
    PythonDistributionEntryPointsField,
    PythonTestTarget,
    PythonTestsDependenciesField,
    PythonTestsEntryPointDependenciesField,
    PythonTestsGeneratorTarget,
    ResolvePythonDistributionEntryPointsRequest,
    ResolvedPythonDistributionEntryPoints,
)
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Address, Digest
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap


def get_python_distribution_entry_point_unambiguous_module_owners(
    address: Address,
    entry_point_group: str,  # group is the pypa term; aka category or namespace
    entry_point_name: str,
    entry_point: EntryPoint,
    explicitly_provided_deps: ExplicitlyProvidedDependencies,
    owners: PythonModuleOwners,
) -> tuple[Address]:
    field_str = repr({entry_point_group: {entry_point_name: entry_point.spec}})
    explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
        owners.ambiguous,
        address,
        import_reference="module",
        context=softwrap(
            f"""
            The python_distribution target {address} has the field
            `entry_points={field_str}`, which maps to the Python module
            `{entry_point.module}`
            """
        ),
    )
    maybe_disambiguated = explicitly_provided_deps.disambiguated(owners.ambiguous)
    unambiguous_owners = owners.unambiguous or (
        (maybe_disambiguated,) if maybe_disambiguated else ()
    )
    return unambiguous_owners


@dataclass(frozen=True)
class GetEntryPointDependenciesRequest:
    targets: Targets
    group_predicate: Callable[[PythonDistribution, str], bool]
    predicate: Callable[[PythonDistribution, str, str], bool]


@dataclass(frozen=True)
class EntryPointDependencies:
    addresses: FrozenOrderedSet[Address]

    def __init__(self, addresses: Iterable[Address]) -> None:
        object.__setattr__(self, "addresses", FrozenOrderedSet(sorted(addresses)))


@rule
async def get_filtered_entry_point_dependencies(
    request: GetEntryPointDependenciesRequest,
) -> EntryPointDependencies:
    # This is based on pants.backend.python.target_type_rules.infer_python_distribution_dependencies,
    # but handles multiple targets and filters the entry_points to just get the requested deps.
    all_explicit_dependencies = await MultiGet(
        Get(
            ExplicitlyProvidedDependencies,
            DependenciesRequest(tgt[PythonDistributionDependenciesField]),
        )
        for _, tgt in request.targets
    )
    resolved_entry_points = await MultiGet(
        Get(
            ResolvedPythonDistributionEntryPoints,
            ResolvePythonDistributionEntryPointsRequest(tgt[PythonDistributionEntryPointsField]),
        )
        for _, tgt in request.targets
    )

    filtered_entry_point_pex_addresses: list[Address] = []
    filtered_entry_point_modules: list[
        tuple[Address, str, str, EntryPoint, ExplicitlyProvidedDependencies]
    ] = []

    distribution_entry_points: ResolvedPythonDistributionEntryPoints
    for tgt, distribution_entry_points, explicitly_provided_deps in zip(
        request.targets, resolved_entry_points, all_explicit_dependencies
    ):
        entry_points_field = tgt[PythonDistributionEntryPointsField]
        # use .val instead of .explicit_modules and .pex_binary_addresses to facilitate filtering
        for ep_group, entry_points in distribution_entry_points.val.items():
            if not request.group_predicate(entry_points_field, ep_group):
                continue
            for ep_name, ep_val in entry_points.items():
                if not request.predicate(entry_points_field, ep_group, ep_name):
                    continue
                if ep_val.pex_binary_address:
                    filtered_entry_point_pex_addresses.append(ep_val.pex_binary_address)
                else:
                    filtered_entry_point_modules.append(
                        (
                            tgt.address,
                            ep_group,
                            ep_name,
                            ep_val.entry_point,
                            explicitly_provided_deps,
                        )
                    )
    filtered_module_owners = await MultiGet(
        Get(PythonModuleOwners, PythonModuleOwnersRequest(entry_point.module, resolve=None))
        for _, _, _, entry_point, _ in filtered_entry_point_modules
    )

    filtered_unambiguous_module_owners: OrderedSet[Address] = OrderedSet()
    for (address, ep_group, ep_name, entry_point, explicitly_provided_deps), owners in zip(
        filtered_entry_point_modules, filtered_module_owners
    ):
        filtered_unambiguous_module_owners.update(
            get_python_distribution_entry_point_unambiguous_module_owners(
                address, ep_group, ep_name, entry_point, explicitly_provided_deps, owners
            )
        )

    return EntryPointDependencies(
        Addresses(*filtered_entry_point_pex_addresses, *filtered_unambiguous_module_owners)
    )


@dataclass(frozen=True)
class PythonTestsEntryPointDependenciesInferenceFieldSet(FieldSet):

    required_fields = (
        PythonTestsDependenciesField,
        PythonTestsEntryPointDependenciesField,
    )
    entry_point_dependencies: PythonTestsEntryPointDependenciesField


class InferEntryPointDependencies(InferDependenciesRequest):
    infer_from = PythonTestsEntryPointDependenciesField


@rule(
    desc=f"Infer dependencies based on `{PythonTestsEntryPointDependenciesField.alias}` field.",
    level=LogLevel.DEBUG,
)
async def infer_entry_point_dependencies(
    request: InferEntryPointDependencies,
) -> InferredDependencies:
    entry_point_deps: PythonTestsEntryPointDependenciesField = (
        request.field_set.entry_point_dependencies
    )
    if entry_point_deps.value is None:
        return InferredDependencies([])

    targets = await Get(
        Targets,
        UnparsedAddressInputs(
            entry_point_deps.value.keys(),
            owning_address=request.field_set.address,
            description_of_origin=f"{PythonTestsEntryPointDependenciesField.alias} from {request.field_set.address}",
        ),
    )

    requested_entry_points: dict[PythonDistribution, set[str]] = {}

    address: Address
    requested_ep: tuple[str, ...]
    for target, (address, requested_ep) in zip(targets, entry_point_deps.value.items()):
        assert target.address == address, "sort order was not preserved"

        if not requested_ep:
            # requested an empty list, so no entry points were actually requested.
            continue
        if "*" in requested_ep and len(requested_ep) > 1:
            requested_ep = ("*",)

        if not target.has_field(PythonDistributionEntryPointsField):
            # unknown target type. ignore
            continue
        if not target.get(PythonDistributionEntryPointsField).value:
            # no entry points can be resolved.
            # TODO: Maybe warn that the requested entry points do not exist?
            continue
        requested_entry_points[target] = set(requested_ep)

    def group_predicate(tgt: PythonDistribution, ep_group: str) -> bool:
        relevant = ("*", ep_group)
        for item in sorted(requested_entry_points[tgt]):
            if item in relevant or item.startswith(f"{ep_group}/"):
                return True
        return False

    def predicate(tgt: PythonDistribution, ep_group: str, ep_name: str) -> bool:
        relevant = {"*", ep_group, f"{ep_group}/{ep_name}"}
        if relevant & requested_entry_points[tgt]:
            # at least one requested entry point is relevant
            return True
        return False

    entry_point_dependencies = await Get(
        EntryPointDependencies,
        GetEntryPointDependenciesRequest(
            Targets(requested_entry_points.keys()), group_predicate, predicate
        ),
    )
    return InferredDependencies(entry_point_dependencies.addresses)


@dataclass(frozen=True)
class GenerateEntryPointsTxtRequest:
    entry_points_by_path: FrozenDict[str, tuple[ResolvedPythonDistributionEntryPoints]]
    group_predicate: Callable[[str], bool]
    predicate: Callable[[str, str], bool]

    def __init__(
        self,
        entry_points_by_path: dict[str, Iterable[ResolvedPythonDistributionEntryPoints]],
        group_predicate: Callable[[str], bool],
        predicate: Callable[[str, str], bool],
    ) -> None:
        object.__setattr__(
            self,
            "entry_points_by_path",
            FrozenDict(
                (path, tuple(entry_points)) for path, entry_points in entry_points_by_path.items()
            ),
        )
        object.__setattr__(self, "group_predicate", group_predicate)
        object.__setattr__(self, "predicate", predicate)


@dataclass(frozen=True)
class EntryPointsTxt:
    digest: Digest


@rule
async def generate_entry_points_txt(request: GenerateEntryPointsTxtRequest) -> EntryPointsTxt:
    entry_points_txt_files = []
    for module_path, resolved_eps in request.entry_points_by_path.items():
        group_sections = {}

        for resolved_ep in resolved_eps:
            ep_group: str
            entry_points: FrozenDict[str, PythonDistributionEntryPoint]
            for ep_group, entry_points in resolved_ep.val.items():
                if not entry_points or not request.group_predicate(ep_group):
                    continue

                entry_points_txt_section = f"[{ep_group}]\n"
                for entry_point_name, ep in sorted(entry_points.items()):
                    if not request.predicate(ep_group, entry_point_name):
                        continue
                    entry_points_txt_section += f"{entry_point_name} = {ep.entry_point.spec}\n"
                entry_points_txt_section += "\n"
                group_sections[ep_group] = entry_points_txt_section

        # consistent sorting
        entry_points_txt_contents = "".join(
            group_sections[ep_group] for ep_group in sorted(group_sections)
        )

        entry_points_txt_path = f"{module_path}.egg-info/entry_points.txt"
        entry_points_txt_files.append(
            FileContent(entry_points_txt_path, entry_points_txt_contents.encode("utf-8"))
        )

    digest = await Get(Digest, CreateDigest(entry_points_txt_files))
    return EntryPointsTxt(digest)


def rules():
    return [
        *collect_rules(),
        PythonTestTarget.register_plugin_field(PythonTestsEntryPointDependenciesField),
        PythonTestsGeneratorTarget.register_plugin_field(
            PythonTestsEntryPointDependenciesField,
            as_moved_field=True,
        ),
        UnionRule(InferDependenciesRequest, InferEntryPointDependencies),
    ]
