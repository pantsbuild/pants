# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict

from pants.backend.python.framework.stevedore.target_types import (
    StevedoreExtensionTargets,
    StevedoreNamespacesField,
    StevedoreNamespacesProviderTargetsRequest,
)
from pants.backend.python.goals.pytest_runner import PytestPluginSetup, PytestPluginSetupRequest
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonDistributionEntryPoint,
    PythonDistributionEntryPointsField,
    ResolvedPythonDistributionEntryPoints,
    ResolvePythonDistributionEntryPointsRequest,
)
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


class GenerateEntryPointsTxtFromStevedoreExtensionRequest(PytestPluginSetupRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        # select python_tests targets with stevedore_namespaces field
        return (
            target.has_field(StevedoreNamespacesField)
            and target.get(StevedoreNamespacesField).value is not None
        )


@rule(
    desc=f"Generate entry_points.txt to imitate `{PythonDistribution.alias}` installation.",
    level=LogLevel.DEBUG,
)
async def generate_entry_points_txt_from_stevedore_extension(
    request: GenerateEntryPointsTxtFromStevedoreExtensionRequest,
) -> PytestPluginSetup:
    requested_namespaces = request.target[StevedoreNamespacesField]
    if not requested_namespaces.value:
        return PytestPluginSetup(EMPTY_DIGEST)

    stevedore_targets = await Get(
        StevedoreExtensionTargets,
        StevedoreNamespacesProviderTargetsRequest(requested_namespaces),
    )

    all_resolved_entry_points = await MultiGet(
        Get(
            ResolvedPythonDistributionEntryPoints,
            ResolvePythonDistributionEntryPointsRequest(tgt[PythonDistributionEntryPointsField]),
        )
        for tgt in stevedore_targets
    )

    possible_paths = [
        {
            f"{tgt.address.spec_path}/{ep.entry_point.module.split('.')[0]}"
            for _, entry_points in (resolved_eps.val or {}).items()
            for ep in entry_points.values()
        }
        for tgt, resolved_eps in zip(stevedore_targets, all_resolved_entry_points)
    ]
    resolved_paths = await MultiGet(
        Get(Paths, PathGlobs(module_candidate_paths)) for module_candidate_paths in possible_paths
    )

    # arrange in sibling groups
    stevedore_extensions_by_path: dict[str, list[ResolvedPythonDistributionEntryPoints]] = (
        defaultdict(list)
    )
    for resolved_ep, paths in zip(all_resolved_entry_points, resolved_paths):
        path = paths.dirs[0]  # just take the first match
        stevedore_extensions_by_path[path].append(resolved_ep)

    entry_points_txt_files = []
    for module_path, resolved_eps in stevedore_extensions_by_path.items():
        namespace_sections = {}

        for resolved_ep in resolved_eps:
            namespace: str
            entry_points: FrozenDict[str, PythonDistributionEntryPoint]
            for namespace, entry_points in resolved_ep.val.items():
                if not entry_points or namespace not in requested_namespaces.value:
                    continue

                entry_points_txt_section = f"[{namespace}]\n"
                for entry_point_name, ep in sorted(entry_points.items()):
                    entry_points_txt_section += f"{entry_point_name} = {ep.entry_point.spec}\n"
                entry_points_txt_section += "\n"
                namespace_sections[namespace] = entry_points_txt_section

        # consistent sorting
        entry_points_txt_contents = "".join(
            namespace_sections[ns] for ns in sorted(namespace_sections)
        )

        entry_points_txt_path = f"{module_path}.egg-info/entry_points.txt"
        entry_points_txt_files.append(
            FileContent(entry_points_txt_path, entry_points_txt_contents.encode("utf-8"))
        )

    digest = await Get(Digest, CreateDigest(entry_points_txt_files))
    return PytestPluginSetup(digest)


def rules():
    return [
        *collect_rules(),
        UnionRule(
            PytestPluginSetupRequest,
            GenerateEntryPointsTxtFromStevedoreExtensionRequest,
        ),
    ]
