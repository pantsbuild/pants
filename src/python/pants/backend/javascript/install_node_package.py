# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import json
import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import nodejs_project_environment
from pants.backend.javascript.dependency_inference.rules import rules as dependency_inference_rules
from pants.backend.javascript.nodejs_project_environment import (
    NodeJsProjectEnvironment,
    NodeJsProjectEnvironmentProcess,
    NodeJSProjectEnvironmentRequest,
)
from pants.backend.javascript.package_json import (
    NodePackageNameField,
    NodePackageVersionField,
    PackageJsonSourceField,
)
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.target_types import JSSourceField
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, DigestContents, FileContent, PathGlobs
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    HydrateSourcesRequest,
    HydratedSources,
    SourcesField,
    Target,
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
    project_env: NodeJsProjectEnvironment
    digest: Digest

    @property
    def project_dir(self) -> str:
        return self.project_env.root_dir

    def join_relative_workspace_directory(self, path: str) -> str:
        return os.path.join(self.project_env.relative_workspace_directory(), path)

    @property
    def target(self) -> Target:
        return self.project_env.ensure_target()


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
async def fetch_source_files_for_address(
    req: InstalledNodePackageRequest, union_membership: UnionMembership
) -> InstalledNodePackage:
    project_env = await Get(NodeJsProjectEnvironment, NodeJSProjectEnvironmentRequest(req.address))
    target = project_env.ensure_target()
    # TODO: What is the order of these? https://github.com/npm/cli/issues/4139
    transitive_tgts = await Get(TransitiveTargets, TransitiveTargetsRequest([target.address]))


    pkg_tgts = targets_with_sources_types(
        [PackageJsonSourceField], transitive_tgts.dependencies, union_membership
    )
    assert target not in pkg_tgts

    # Get the paths of any sub-packages, relative to current dir
    target_depth = len(target.address.spec_path.split("/"))
    project_package_paths = []
    for tgt in pkg_tgts:
        project_package_paths.append("../" * target_depth + tgt.address.spec_path)


    # Modify project package.json to add workspaces - probably only need to do this for npm
    hydrated_source = await Get(HydratedSources, HydrateSourcesRequest(target[SourcesField]))
    source_contents = await Get(DigestContents, Digest, hydrated_source.snapshot.digest)
    proj_pkg_json = json.loads(source_contents[0].content)

    proj_pkg_json["workspaces"] = project_package_paths

    source_files = await _get_relevant_source_files(
        (tgt[SourcesField] for tgt in transitive_tgts.closure if tgt.has_field(SourcesField)),
        with_js=True,
    )
    workspace_pkg_json = json.dumps(proj_pkg_json)
    # workspace_pkg_json_digest = await Get(
    #     Digest,
    #     CreateDigest(
    #         [
    #             FileContent(
    #                 f"{project_env.root_dir}/package1.json",
    #                 json.dumps(workspace_pkg_json).encode("utf-8"),
    #             )
    #         ]
    #     ),
    # )

    # Run install
    package_digest = source_files.snapshot.digest

    install_result = await Get(
        ProcessResult,
        NodeJsProjectEnvironmentProcess(
            project_env,
            project_env.project.immutable_install_args,
            description=f"Installing {target[NodePackageNameField].value}@{target[NodePackageVersionField].value}.",
            input_digest=package_digest,
            output_directories=tuple(project_env.node_modules_directories),
        ),
    )
    node_modules = await Get(Digest, AddPrefix(install_result.output_digest, project_env.root_dir))

    return InstalledNodePackage(
        project_env,
        digest=await Get(
            Digest,
            MergeDigests(
                [
                    package_digest,
                    node_modules,
                    # workspace_pkg_json_digest
                ]
            ),
        ),
    )


# @rule
# async def install_node_packages_for_address(
#     req: InstalledNodePackageRequest, union_membership: UnionMembership
# ) -> InstalledNodePackage:
#     project_env = await Get(NodeJsProjectEnvironment, NodeJSProjectEnvironmentRequest(req.address))
#     target = project_env.ensure_target()
#     transitive_tgts = await Get(TransitiveTargets, TransitiveTargetsRequest([target.address]))

#     pkg_tgts = targets_with_sources_types(
#         [PackageJsonSourceField], transitive_tgts.dependencies, union_membership
#     )
#     assert target not in pkg_tgts
#     installations = await MultiGet(
#         Get(InstalledNodePackageWithSource, InstalledNodePackageRequest(pkg_tgt.address))
#         for pkg_tgt in pkg_tgts
#     )

#     source_files = await _get_relevant_source_files(
#         (tgt[SourcesField] for tgt in transitive_tgts.closure if tgt.has_field(SourcesField)),
#         with_js=False,
#     )
#     install_input_digest = await Get(
#         Digest,
#         MergeDigests(
#             itertools.chain(
#                 (installation.digest for installation in installations),
#                 (source_files.snapshot.digest,),
#             )
#         ),
#     )

#     install_result = await Get(
#         ProcessResult,
#         NodeJsProjectEnvironmentProcess(
#             project_env,
#             project_env.project.immutable_install_args,
#             description=f"Installing {target[NodePackageNameField].value}@{target[NodePackageVersionField].value}.",
#             input_digest=install_input_digest,
#             output_directories=tuple(project_env.node_modules_directories),
#         ),
#     )
#     node_modules = await Get(Digest, AddPrefix(install_result.output_digest, project_env.root_dir))
#     return InstalledNodePackage(
#         project_env,
#         digest=await Get(Digest, MergeDigests([install_input_digest, node_modules])),
#     )


@rule
async def add_sources_to_installed_node_package(
    req: InstalledNodePackageRequest,
) -> InstalledNodePackageWithSource:
    installation = await Get(InstalledNodePackage, InstalledNodePackageRequest, req)
    transitive_tgts = await Get(
        TransitiveTargets, TransitiveTargetsRequest([installation.target.address])
    )

    source_files = await _get_relevant_source_files(
        (tgt[SourcesField] for tgt in transitive_tgts.dependencies if tgt.has_field(SourcesField)),
        with_js=True,
    )
    digest = await Get(Digest, MergeDigests((installation.digest, source_files.snapshot.digest)))
    return InstalledNodePackageWithSource(installation.project_env, digest=digest)


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *nodejs.rules(),
        *nodejs_project_environment.rules(),
        *dependency_inference_rules(),
        *collect_rules(),
    ]
