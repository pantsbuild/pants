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
    NodeBuildScript,
    NodeBuildScriptEntryPointField,
    NodeBuildScriptExtraCaches,
    NodeBuildScriptExtraEnvVarsField,
    NodeBuildScriptOutputDirectoriesField,
    NodeBuildScriptOutputFilesField,
    NodeBuildScriptSourcesField,
    NodePackageNameField,
    NodePackageVersionField,
    NPMDistributionTarget,
    PackageJsonSourceField,
)
from pants.build_graph.address import Address
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.target_types import ResourceSourceField
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.native_engine import AddPrefix, Digest, Snapshot
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
    required_fields = (PackageJsonSourceField, OutputPathField)
    source: PackageJsonSourceField
    output_path: OutputPathField


@dataclass(frozen=True)
class NodeBuildScriptPackageFieldSet(PackageFieldSet):
    required_fields = (
        NodeBuildScriptSourcesField,
        OutputPathField,
        NodeBuildScriptEntryPointField,
        NodeBuildScriptOutputFilesField,
        NodeBuildScriptOutputDirectoriesField,
        NodeBuildScriptExtraCaches,
    )
    source: NodeBuildScriptSourcesField
    output_path: OutputPathField
    script_name: NodeBuildScriptEntryPointField
    output_directories: NodeBuildScriptOutputDirectoriesField
    output_files: NodeBuildScriptOutputFilesField
    extra_caches: NodeBuildScriptExtraCaches
    extra_env_vars: NodeBuildScriptExtraEnvVarsField


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
    node_package = installation.project_env.ensure_target()
    name = node_package.get(NodePackageNameField).value
    version = node_package.get(NodePackageVersionField).value
    if version is None:
        raise ValueError(
            f"{field_set.source.file_path}#version must be set in order to package a {NPMDistributionTarget.alias}."
        )
    archive_file = installation.project_env.project.pack_archive_format.format(name, version)
    result = await Get(
        ProcessResult,
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=("pack",),
            description=f"Packaging .tgz archive for {name}@{version}",
            input_digest=installation.digest,
            output_files=(installation.join_relative_workspace_directory(archive_file),),
            level=LogLevel.INFO,
        ),
    )
    if field_set.output_path.value:
        output_path = field_set.output_path.value_or_default(file_ending=None)
        digest = await Get(Digest, AddPrefix(result.output_digest, output_path))
    else:
        digest = result.output_digest

    return BuiltPackage(
        digest, (BuiltPackageArtifact(archive_file, tuple(result.stderr.decode().splitlines())),)
    )


_NOT_ALPHANUMERIC = re.compile("[^0-9a-zA-Z]+")


@dataclass(frozen=True)
class NodeBuildScriptResult:
    process: ProcessResult
    project_directory: str


@dataclass(frozen=True)
class NodeBuildScriptRequest:
    address: Address
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    script_name: str
    extra_caches: tuple[str, ...]
    extra_env_vars: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (self.output_directories or self.output_files):
            raise ValueError(
                softwrap(
                    f"""
                    Neither the {NodeBuildScriptOutputDirectoriesField.alias} nor the
                    {NodeBuildScriptOutputFilesField.alias} field was provided.

                    One of the fields have to be set, or else the `{NodeBuildScript.alias}`
                    output will not be captured for further use in the build.
                    """
                )
            )

    @classmethod
    def from_generate_request(
        cls, req: GenerateResourcesFromNodeBuildScriptRequest
    ) -> NodeBuildScriptRequest:
        return cls(
            address=req.protocol_target.address,
            output_files=req.protocol_target[NodeBuildScriptOutputFilesField].value or (),
            output_directories=req.protocol_target[NodeBuildScriptOutputDirectoriesField].value
            or (),
            script_name=req.protocol_target[NodeBuildScriptEntryPointField].value,
            extra_caches=req.protocol_target[NodeBuildScriptExtraCaches].value or (),
            extra_env_vars=req.protocol_target[NodeBuildScriptExtraEnvVarsField].value or (),
        )

    @classmethod
    def from_package_request(cls, req: NodeBuildScriptPackageFieldSet) -> NodeBuildScriptRequest:
        return cls(
            address=req.address,
            output_files=req.output_files.value or (),
            output_directories=req.output_directories.value or (),
            script_name=req.script_name.value,
            extra_caches=req.extra_caches.value or (),
            extra_env_vars=req.extra_env_vars.value or (),
        )

    def get_paths(self) -> Iterable[str]:
        yield from self.output_directories
        yield from self.output_files


@rule
async def run_node_build_script(req: NodeBuildScriptRequest) -> NodeBuildScriptResult:
    installation = await Get(
        InstalledNodePackageWithSource, InstalledNodePackageRequest(req.address)
    )
    output_files = req.output_files
    output_dirs = req.output_directories
    script_name = req.script_name
    extra_caches = req.extra_caches
    extra_env_vars = req.extra_env_vars

    def cache_name(cache_path: str) -> str:
        parts = (installation.project_env.package_dir(), script_name, cache_path)
        return "_".join(_NOT_ALPHANUMERIC.sub("_", part) for part in parts if part)

    args = ("run", script_name)
    target_env_vars = await Get(EnvironmentVars, EnvironmentVarsRequest(extra_env_vars))
    result = await Get(
        ProcessResult,
        NodeJsProjectEnvironmentProcess(
            installation.project_env,
            args=filter(None, args),
            description=f"Running node build script '{script_name}'.",
            input_digest=installation.digest,
            output_files=tuple(
                installation.join_relative_workspace_directory(file) for file in output_files or ()
            ),
            output_directories=tuple(
                installation.join_relative_workspace_directory(directory)
                for directory in output_dirs or ()
            ),
            level=LogLevel.INFO,
            per_package_caches=FrozenDict(
                {cache_name(extra_cache): extra_cache for extra_cache in extra_caches or ()}
            ),
            extra_env=target_env_vars,
        ),
    )

    return NodeBuildScriptResult(result, installation.project_dir)


@rule
async def generate_resources_from_node_build_script(
    req: GenerateResourcesFromNodeBuildScriptRequest,
) -> GeneratedSources:
    result = await Get(NodeBuildScriptResult, NodeBuildScriptRequest.from_generate_request(req))
    return GeneratedSources(
        await Get(Snapshot, AddPrefix(result.process.output_digest, result.project_directory))
    )


@rule
async def generate_package_artifact_from_node_build_script(
    req: NodeBuildScriptPackageFieldSet,
) -> BuiltPackage:
    request = NodeBuildScriptRequest.from_package_request(req)
    result = await Get(NodeBuildScriptResult, NodeBuildScriptRequest, request)
    if req.output_path.value:
        output_path = req.output_path.value_or_default(file_ending=None)
        digest = await Get(Digest, AddPrefix(result.process.output_digest, output_path))
    else:
        digest = result.process.output_digest
    artifacts = tuple(BuiltPackageArtifact(path) for path in request.get_paths())
    return BuiltPackage(digest, artifacts)


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *install_node_package.rules(),
        UnionRule(PackageFieldSet, NodePackageTarFieldSet),
        UnionRule(PackageFieldSet, NodeBuildScriptPackageFieldSet),
        UnionRule(GenerateSourcesRequest, GenerateResourcesFromNodeBuildScriptRequest),
    ]
