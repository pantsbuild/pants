# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import install_node_package
from pants.backend.javascript.install_node_package import InstalledNodePackage, InstalledNodePackageRequest
from pants.backend.javascript.package_json import (
    NodePackageNameField,
    NodePackageVersionField,
    PackageJsonSourceField,
)
from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class NodePackageTarFieldSet(PackageFieldSet):
    required_fields = (PackageJsonSourceField, NodePackageNameField, NodePackageVersionField)
    source: PackageJsonSourceField
    name: NodePackageNameField
    version: NodePackageVersionField


@rule
async def pack_node_package_into_tgz_for_publication(
    field_set: NodePackageTarFieldSet
) -> BuiltPackage:
    installation = await Get(InstalledNodePackage, InstalledNodePackageRequest(field_set.address))
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


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *install_node_package.rules(),
        UnionRule(PackageFieldSet, NodePackageTarFieldSet),
    ]
