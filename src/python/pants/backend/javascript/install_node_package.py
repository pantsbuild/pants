# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import dependency_inference, resolve
from pants.backend.javascript.package_json import (
    NodePackageNameField,
    NodePackageVersionField,
    OwningNodePackage,
    OwningNodePackageRequest,
    PackageJsonSourceField,
)
from pants.backend.javascript.resolve import ChosenNodeResolve, RequestNodeResolve
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess
from pants.backend.javascript.target_types import JSSourceField
from pants.build_graph.address import Address
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import (
    AddPrefix,
    Digest,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    SourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership, UnionRule


@dataclass(frozen=True)
class InstalledNodePackageRequest:
    address: Address


@dataclass(frozen=True)
class InstalledNodePackage:
    root_dir: str
    digest: Digest

    def add_root_prefix(self, digest: Digest) -> AddPrefix:
        return AddPrefix(digest, self.root_dir)


@dataclass(frozen=True)
class InstalledNodePackageWithSource(InstalledNodePackage):
    pass


async def _get_relevant_source_files(
    sources: Iterable[SourcesField], with_js: bool = False
) -> SourceFiles:
    return await Get(
        SourceFiles,
        SourceFilesRequest(
            sources,
            for_sources_types=(PackageJsonSourceField, FileSourceField)
            + ((ResourceSourceField, JSSourceField) if with_js else ()),
            enable_codegen=True,
        ),
    )


@rule
async def install_node_packages_for_address(
    req: InstalledNodePackageRequest, union_membership: UnionMembership
) -> InstalledNodePackage:
    node_resolve, owning_tgt = await MultiGet(
        Get(ChosenNodeResolve, RequestNodeResolve(req.address)),
        Get(OwningNodePackage, OwningNodePackageRequest(req.address)),
    )
    assert owning_tgt.target, f"Already ensured to exist by {ChosenNodeResolve.__name__}."
    target = owning_tgt.target
    lockfile_snapshot, transitive_tgts = await MultiGet(
        Get(Snapshot, PathGlobs([node_resolve.file_path])),
        Get(TransitiveTargets, TransitiveTargetsRequest([target.address])),
    )

    package_tgts = targets_with_sources_types(
        [PackageJsonSourceField], transitive_tgts.dependencies, union_membership
    )
    assert target not in package_tgts
    installations = await MultiGet(
        Get(InstalledNodePackageWithSource, InstalledNodePackageRequest(pkg_tgt.address))
        for pkg_tgt in package_tgts
    )

    source_files = await _get_relevant_source_files(
        (tgt[SourcesField] for tgt in transitive_tgts.closure if tgt.has_field(SourcesField)),
        with_js=False,
    )
    merged_input_digest = await Get(
        Digest, MergeDigests((lockfile_snapshot.digest, source_files.snapshot.digest))
    )
    root_dir = os.path.dirname(node_resolve.file_path)
    new_sources_digest = await Get(Digest, RemovePrefix(merged_input_digest, root_dir))

    install_input_digest = await Get(
        Digest,
        MergeDigests(
            itertools.chain(
                (installation.digest for installation in installations), (new_sources_digest,)
            )
        ),
    )

    install_result = await Get(
        ProcessResult,
        NodeJSToolProcess,
        NodeJSToolProcess.npm(
            ("clean-install",),
            f"Installing {target[NodePackageNameField].value}@{target[NodePackageVersionField].value}.",
            input_digest=install_input_digest,
            output_directories=("node_modules",),
        ),
    )
    return InstalledNodePackage(
        root_dir=root_dir,
        digest=await Get(
            Digest, MergeDigests([install_input_digest, install_result.output_digest])
        ),
    )


@rule
async def add_sources_to_installed_node_package(
    req: InstalledNodePackageRequest,
) -> InstalledNodePackageWithSource:
    installation = await Get(InstalledNodePackage, InstalledNodePackageRequest, req)
    transitive_tgts = await Get(TransitiveTargets, TransitiveTargetsRequest([req.address]))

    source_files = await _get_relevant_source_files(
        (tgt[SourcesField] for tgt in transitive_tgts.dependencies if tgt.has_field(SourcesField)),
        with_js=True,
    )
    digest_relative_root = await Get(
        Digest, RemovePrefix(source_files.snapshot.digest, installation.root_dir)
    )
    digest = await Get(Digest, MergeDigests((installation.digest, digest_relative_root)))
    return InstalledNodePackageWithSource(root_dir=installation.root_dir, digest=digest)


def rules() -> Iterable[Rule | UnionRule]:
    return [*nodejs.rules(), *resolve.rules(), *dependency_inference.rules(), *collect_rules()]
