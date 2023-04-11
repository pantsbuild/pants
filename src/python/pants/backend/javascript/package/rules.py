# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Iterable

from pants.backend.javascript import install_node_package
from pants.backend.javascript.install_node_package import (
    InstalledNodePackageRequest,
    InstalledNodePackageWithSource,
)
from pants.backend.javascript.nodejs_project_environment import NodeJsProjectEnvironmentProcess
from pants.backend.javascript.package_json import (
    NodeBuildScriptEntryPointField,
    NodeBuildScriptExtraCaches,
    NodeBuildScriptOutputDirectoriesField,
    NodeBuildScriptOutputFilesField,
    NodeBuildScriptSourcesField,
    NodePackageNameField,
    NodePackageVersionField,
    PackageJsonSourceField,
)
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.target_types import ResourceSourceField
from pants.engine.internals.native_engine import AddPrefix, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class NodePackageTarFieldSet(PackageFieldSet):
    required_fields = (PackageJsonSourceField, NodePackageNameField, NodePackageVersionField)
    source: PackageJsonSourceField
    name: NodePackageNameField
    version: NodePackageVersionField


@dataclass(frozen=True)
class GenerateResourcesFromNodeBuildScriptRequest(GenerateSourcesRequest):
    input = NodeBuildScriptSourcesField
    output = ResourceSourceField

    exportable: ClassVar[bool] = True


@rule
async def pack_node_package_into_tgz_for_publication(
    field_set: NodePackageTarFieldSet,
) -> BuiltPackage:
    installation = await Get(
        InstalledNodePackageWithSource, InstalledNodePackageRequest(field_set.address)
    )
    archive_file = f"{field_set.name.value}-{field_set.version.value}.tgz"
    result = await Get(
        ProcessResult,
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=("pack",),
            description=f"Packaging .tgz archive for {field_set.name.value}@{field_set.version.value}",
            input_digest=installation.digest,
            output_files=(installation.join_relative_workspace_directory(archive_file),),
            level=LogLevel.INFO,
        ),
    )

    return BuiltPackage(result.output_digest, (BuiltPackageArtifact(archive_file),))


_NOT_ALPHANUMERIC = re.compile("[^0-9a-zA-Z]+")


@rule
async def run_node_build_script(
    req: GenerateResourcesFromNodeBuildScriptRequest,
) -> GeneratedSources:
    installation = await Get(
        InstalledNodePackageWithSource, InstalledNodePackageRequest(req.protocol_target.address)
    )
    output_files = req.protocol_target[NodeBuildScriptOutputFilesField]
    output_dirs = req.protocol_target[NodeBuildScriptOutputDirectoriesField]
    script_name = req.protocol_target[NodeBuildScriptEntryPointField].value
    extra_caches = req.protocol_target[NodeBuildScriptExtraCaches].value
    if not (output_dirs.value or output_files.value):
        raise ValueError(
            softwrap(
                f"""
                Neither the {output_dirs.alias} nor the {output_files.alias} field was provided.

                One of the fields have to be set, or else the `node_build_script`
                output will not be captured for further use in the build.
                """
            )
        )

    def cache_name(cache_path: str) -> str:
        parts = (installation.project_env.package_dir(), script_name, cache_path)
        return "_".join(_NOT_ALPHANUMERIC.sub("_", part) for part in parts if part)

    args = ("run", script_name)
    result = await Get(
        ProcessResult,
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=filter(None, args),
            description=f"Running node build script '{script_name}'.",
            input_digest=installation.digest,
            output_files=tuple(
                installation.join_relative_workspace_directory(file)
                for file in output_files.value or ()
            ),
            output_directories=tuple(
                installation.join_relative_workspace_directory(directory)
                for directory in output_dirs.value or ()
            ),
            level=LogLevel.INFO,
            per_package_caches=FrozenDict(
                {cache_name(extra_cache): extra_cache for extra_cache in extra_caches or ()}
            ),
        ),
    )

    return GeneratedSources(
        await Get(Snapshot, AddPrefix(result.output_digest, installation.project_dir))
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *install_node_package.rules(),
        UnionRule(PackageFieldSet, NodePackageTarFieldSet),
        UnionRule(GenerateSourcesRequest, GenerateResourcesFromNodeBuildScriptRequest),
    ]
