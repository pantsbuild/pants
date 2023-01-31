# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict

from pants.backend.python.framework.stevedore.target_types import (
    ResolvedStevedoreEntryPoints,
    ResolveStevedoreEntryPointsRequest,
    StevedoreEntryPoints,
    StevedoreEntryPointsField,
    StevedoreNamespaceField,
    StevedoreNamespacesField,
)
from pants.backend.python.goals.pytest_runner import PytestPluginSetup, PytestPluginSetupRequest
from pants.backend.python.target_types import PythonTestsDependenciesField
from pants.engine.fs import CreateDigest, Digest, FileContent, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, Target, Targets
from pants.engine.unions import UnionRule
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
    desc="Generate entry_points.txt from stevedore_extension target metadata",
    level=LogLevel.DEBUG,
)
async def generate_entry_points_txt_from_stevedore_extension(
    request: GenerateEntryPointsTxtFromStevedoreExtensionRequest,
) -> PytestPluginSetup:
    # get all injected dependencies that are StevedoreExtension targets
    dependencies = await Get(
        Targets, DependenciesRequest(request.target.get(PythonTestsDependenciesField))
    )
    stevedore_targets = [
        tgt
        for tgt in dependencies
        if tgt.has_field(StevedoreEntryPointsField)
        and tgt.get(StevedoreEntryPointsField).value is not None
    ]

    resolved_entry_points = await MultiGet(
        Get(
            ResolvedStevedoreEntryPoints,
            ResolveStevedoreEntryPointsRequest(tgt[StevedoreEntryPointsField]),
        )
        for tgt in stevedore_targets
    )

    possible_paths = [
        {
            f"{stevedore_extension.address.spec_path}/{entry_point.value.module.split('.')[0]}"
            for entry_point in resolved_ep.val or []
        }
        for stevedore_extension, resolved_ep in zip(stevedore_targets, resolved_entry_points)
    ]
    resolved_paths = await MultiGet(
        Get(Paths, PathGlobs(module_candidate_paths)) for module_candidate_paths in possible_paths
    )

    # arrange in sibling groups
    stevedore_extensions_by_path = defaultdict(list)
    for stevedore_extension, resolved_ep, paths in zip(
        stevedore_targets, resolved_entry_points, resolved_paths
    ):
        path = paths.dirs[0]  # just take the first match
        stevedore_extensions_by_path[path].append((stevedore_extension, resolved_ep))

    entry_points_txt_files = []
    for module_path, stevedore_extensions in stevedore_extensions_by_path.items():
        namespace_sections = {}

        for stevedore_extension, resolved_ep in stevedore_extensions:
            namespace: StevedoreNamespaceField = stevedore_extension[StevedoreNamespaceField]
            entry_points: StevedoreEntryPoints | None = resolved_ep.val
            if not entry_points:
                continue

            entry_points_txt_section = f"[{namespace.value}]\n"
            for entry_point in sorted(entry_points, key=lambda ep: ep.name):
                entry_points_txt_section += f"{entry_point.name} = {entry_point.value.spec}\n"
            entry_points_txt_section += "\n"
            namespace_sections[str(namespace.value)] = entry_points_txt_section

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
