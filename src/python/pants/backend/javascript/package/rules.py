# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import dependency_inference, resolve
from pants.backend.javascript.package_json import (
    NodePackageNameField,
    NodePackageVersionField,
    PackageJsonSourceField,
)
from pants.backend.javascript.resolve import ChosenNodeResolve, RequestNodeResolve
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess
from pants.backend.javascript.target_types import JSSourceField
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Digest, MergeDigests, RemovePrefix, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    SourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class NodePackageTarFieldSet(PackageFieldSet):
    required_fields = (PackageJsonSourceField, NodePackageNameField, NodePackageVersionField)
    source: PackageJsonSourceField
    name: NodePackageNameField
    version: NodePackageVersionField


@rule
async def pack_node_package_into_tgz_for_publication(
    field_set: NodePackageTarFieldSet, union_membership: UnionMembership
) -> BuiltPackage:
    node_resolve = await Get(ChosenNodeResolve, RequestNodeResolve(field_set.address))
    lockfile_snapshot = await Get(Snapshot, PathGlobs([node_resolve.file_path]))
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))

    relevant_tgts = targets_with_sources_types(
        [JSSourceField, PackageJsonSourceField, ResourceSourceField, FileSourceField],
        transitive_targets.dependencies,
        union_membership,
    )
    sources = FrozenOrderedSet((field_set.source, *(tgt[SourcesField] for tgt in relevant_tgts)))
    source_files = await Get(SourceFiles, SourceFilesRequest(sources))
    merged_input_digest = await Get(
        Digest, MergeDigests((lockfile_snapshot.digest, source_files.snapshot.digest))
    )

    install_input_digest = await Get(
        Digest, RemovePrefix(merged_input_digest, os.path.dirname(node_resolve.file_path))
    )

    install_result = await Get(
        ProcessResult,
        NodeJSToolProcess,
        NodeJSToolProcess.npm(
            ("clean-install",),
            f"Installing {field_set.name.value}@{field_set.version.value}.",
            input_digest=install_input_digest,
            output_directories=("node_modules",),
        ),
    )
    input_digest = await Get(
        Digest, MergeDigests([install_input_digest, install_result.output_digest])
    )
    archive_file = f"{field_set.name.value}-{field_set.version.value}.tgz"
    result = await Get(
        ProcessResult,
        NodeJSToolProcess,
        NodeJSToolProcess.npm(
            ("pack",),
            f"Packaging .tgz archive for {field_set.name.value}@{field_set.version.value}",
            input_digest=input_digest,
            output_files=(archive_file,),
            level=LogLevel.INFO,
        ),
    )

    return BuiltPackage(result.output_digest, (BuiltPackageArtifact(archive_file),))


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *nodejs.rules(),
        *resolve.rules(),
        *dependency_inference.rules(),
        UnionRule(PackageFieldSet, NodePackageTarFieldSet),
    ]
