# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterable

from pants.backend.javascript import install_node_package
from pants.backend.javascript.install_node_package import (
    InstalledNodePackageRequest,
    InstalledNodePackageWithSource,
)
from pants.backend.javascript.package_json import (
    NodeBuildScriptEntryPointField,
    NodeBuildScriptOutputsField,
    NodeBuildScriptSourcesField,
    NodePackageNameField,
    NodePackageVersionField,
    PackageJsonSourceField,
)
from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.target_types import ResourceSourceField
from pants.engine.internals.native_engine import AddPrefix, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


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
        NodeJSToolProcess,
        NodeJSToolProcess.npm(
            ("pack",),
            f"Packaging .tgz archive for {field_set.name.value}@{field_set.version.value}",
            input_digest=installation.digest,
            output_files=(archive_file,),
            level=LogLevel.INFO,
        ),
    )

    return BuiltPackage(result.output_digest, (BuiltPackageArtifact(archive_file),))


@rule
async def run_node_build_script(
    req: GenerateResourcesFromNodeBuildScriptRequest,
) -> GeneratedSources:
    installed = await Get(
        InstalledNodePackageWithSource, InstalledNodePackageRequest(req.protocol_target.address)
    )
    args = ("run", req.protocol_target[NodeBuildScriptEntryPointField].value)
    result = await Get(
        ProcessResult,
        NodeJSToolProcess.npm(
            filter(None, args),
            "Running node build script.",
            input_digest=installed.digest,
            output_files=req.protocol_target[NodeBuildScriptOutputsField].value or (),
            level=LogLevel.INFO,
        ),
    )

    return GeneratedSources(
        await Get(Snapshot, AddPrefix, installed.add_root_prefix(result.output_digest))
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *install_node_package.rules(),
        UnionRule(PackageFieldSet, NodePackageTarFieldSet),
        UnionRule(GenerateSourcesRequest, GenerateResourcesFromNodeBuildScriptRequest),
    ]
