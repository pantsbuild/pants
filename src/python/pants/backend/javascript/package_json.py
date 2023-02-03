# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os.path
from dataclasses import dataclass, field
from typing import Any, Iterable

from typing_extensions import Literal

from pants.backend.project_info import dependencies
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.core.util_rules import stripped_source_files
from pants.engine import fs
from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.internals import graph
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllUnexpandedTargets,
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    SingleSourceField,
    StringField,
    Target,
    TargetGenerator,
    Targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import UnmatchedBuildFileGlobs
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


class NodePackageDependenciesField(Dependencies):
    pass


class PackageJsonSourceField(SingleSourceField):
    default = "package.json"
    required = False


class PackageJsonTarget(TargetGenerator):
    alias = "package_json"
    core_fields = (*COMMON_TARGET_FIELDS, PackageJsonSourceField, NodePackageDependenciesField)
    help = "A package.json file."

    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PackageJsonSourceField, NodePackageDependenciesField)


class NodePackageVersionField(StringField):
    alias = "version"
    help = softwrap(
        """
        Version of the Node package, as specified in the package.json.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = True
    value: str


class NodePackageNameField(StringField):
    alias = "package"
    help = softwrap(
        """
        Name of the Node package, as specified in the package.json.

        This field should not be overridden; use the value from target generation.
        """
    )
    required = True
    value: str


class NodeThirdPartyPackageNameField(NodePackageNameField):
    pass


class NodeThirdPartyPackageDependenciesField(Dependencies):
    pass


class NodeThirdPartyPackageTarget(Target):
    alias = "node_third_party_package"

    help = "A third party node package."

    core_fields = (
        *COMMON_TARGET_FIELDS,
        NodeThirdPartyPackageNameField,
        NodePackageVersionField,
        NodeThirdPartyPackageDependenciesField,
    )


class NodePackageTarget(Target):
    alias = "node_package"

    help = "A first party node package."

    core_fields = (
        *COMMON_TARGET_FIELDS,
        PackageJsonSourceField,
        NodePackageNameField,
        NodePackageDependenciesField,
    )


@dataclass(frozen=True)
class PackageJson:
    content: FrozenDict[str, Any]
    name: str
    version: str
    snapshot: Snapshot
    workspaces: tuple[PackageJson, ...] = ()
    module: Literal["commonjs", "module"] | None = None
    dependencies: FrozenDict[str, str] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if self.module not in (None, "commonjs", "module"):
            raise ValueError(
                f'package.json "type" can only be one of "commonjs", "module", but was "{self.module}".'
            )

    @property
    def digest(self) -> Digest:
        return self.snapshot.digest

    @property
    def file(self) -> str:
        return self.snapshot.files[0]

    @property
    def root_dir(self) -> str:
        return os.path.dirname(self.file)

    @property
    def workspace_digests(self) -> Iterable[Digest]:
        yield self.digest
        for workspace in self.workspaces:
            yield from workspace.workspace_digests


class AllPackageJsonTargets(Targets):
    pass


class AllPackageJson(Collection[PackageJson]):
    pass


class PackageJsonForGlobs(Collection[PackageJson]):
    pass


@rule
async def all_package_json_targets(targets: AllUnexpandedTargets) -> AllPackageJsonTargets:
    return AllPackageJsonTargets(tgt for tgt in targets if tgt.has_field(PackageJsonSourceField))


@rule
async def read_package_jsons(globs: PathGlobs) -> PackageJsonForGlobs:
    snapshot = await Get(Snapshot, PathGlobs, globs)
    digest_contents = await Get(DigestContents, Digest, snapshot.digest)

    pkgs = []
    for digest_content in digest_contents:
        parsed_package_json = FrozenDict.deep_freeze(json.loads(digest_content.content))

        self_reference = "./"
        workspaces = await Get(
            PackageJsonForGlobs,
            PathGlobs(
                os.path.join(
                    os.path.dirname(digest_content.path),
                    workspace_dir,
                    PackageJsonSourceField.default,
                )
                for workspace_dir in parsed_package_json.get("workspaces", ())
                if workspace_dir != self_reference
            ),
        )
        pkg = PackageJson(
            content=parsed_package_json,
            name=parsed_package_json["name"],
            version=parsed_package_json["version"],
            snapshot=await Get(Snapshot, PathGlobs([digest_content.path])),
            module=parsed_package_json.get("type"),
            workspaces=tuple(workspaces),
            dependencies=FrozenDict.deep_freeze(
                {
                    **parsed_package_json.get("dependencies", {}),
                    **parsed_package_json.get("devDependencies", {}),
                    **parsed_package_json.get("peerDependencies", {}),
                }
            ),
        )
        pkgs.append(pkg)
    return PackageJsonForGlobs(pkgs)


@rule
async def all_package_json() -> AllPackageJson:
    return AllPackageJson(await Get(PackageJsonForGlobs, PathGlobs(["**/package.json"])))


class GenerateNodePackageTargets(GenerateTargetsRequest):
    generate_from = PackageJsonTarget


@rule
async def generate_node_package_targets(
    request: GenerateNodePackageTargets,
    union_membership: UnionMembership,
    all_pkg_jsons: AllPackageJson,
) -> GeneratedTargets:
    file = request.generator[PackageJsonSourceField].file_path
    file_tgt = TargetGeneratorSourcesHelperTarget(
        {TargetGeneratorSourcesHelperSourcesField.alias: file},
        request.generator.address.create_generated(file),
        union_membership,
    )

    [pkg_json] = await Get(
        PackageJsonForGlobs,
        PathGlobs,
        request.generator[PackageJsonSourceField].path_globs(UnmatchedBuildFileGlobs.error),
    )

    first_party_names = {pkg.name for pkg in all_pkg_jsons}
    third_party_tgts = [
        NodeThirdPartyPackageTarget(
            {
                **{
                    key: value
                    for key, value in request.template.items()
                    if key != PackageJsonSourceField.alias
                },
                NodePackageNameField.alias: name,
                NodePackageVersionField.alias: version,
                NodeThirdPartyPackageDependenciesField.alias: [file_tgt.address.spec],
            },
            request.generator.address.create_generated(name),
            union_membership,
        )
        for name, version in pkg_json.dependencies.items()
        if name not in first_party_names
    ]

    package_target = NodePackageTarget(
        {
            **request.template,
            NodePackageNameField.alias: pkg_json.name,
            NodePackageDependenciesField.alias: [
                file_tgt.address.spec,
                *(tgt.address.spec for tgt in third_party_tgts),
                *request.template.get("dependencies", []),
            ],
        },
        request.generator.address.create_generated(pkg_json.name),
        union_membership,
    )

    return GeneratedTargets(request.generator, [package_target, file_tgt, *third_party_tgts])


def target_types() -> Iterable[type[Target]]:
    return [PackageJsonTarget, NodePackageTarget, NodeThirdPartyPackageTarget]


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *graph.rules(),
        *dependencies.rules(),
        *stripped_source_files.rules(),
        *fs.rules(),
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateNodePackageTargets),
    ]
