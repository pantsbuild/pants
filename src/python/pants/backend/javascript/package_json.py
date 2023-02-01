# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os.path
from dataclasses import dataclass
from typing import Any, Iterable

from pants.backend.project_info import dependencies
from pants.core.util_rules import stripped_source_files
from pants.engine import fs
from pants.engine.addresses import Addresses
from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.internals import graph
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import Rule, collect_rules, rule, rule_helper
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllUnexpandedTargets,
    Dependencies,
    SingleSourceField,
    Target,
    TargetGenerator,
    Targets,
    UnexpandedTargets,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import OwnersNotFoundBehavior, UnmatchedBuildFileGlobs
from pants.util.frozendict import FrozenDict


class PackageJsonSourceField(SingleSourceField):
    default = "package.json"
    required = False


class PackageJsonDependenciesField(Dependencies):
    pass


class PackageJsonTarget(TargetGenerator):
    alias = "package_json"
    core_fields = (*COMMON_TARGET_FIELDS, PackageJsonSourceField, PackageJsonDependenciesField)
    help = "A package.json file."

    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = ()


@dataclass(frozen=True)
class PackageJson:
    content: FrozenDict[str, Any]
    name: str
    version: str
    snapshot: Snapshot
    workspaces: tuple[PackageJson, ...] = ()

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


@dataclass(frozen=True)
class ReadPackageJsonRequest:
    source: PackageJsonSourceField


@rule_helper
async def _read_workspaces_for(
    root_dir: str, parsed_package_json: dict[str, Any]
) -> tuple[PackageJson, ...]:
    self_reference = f".{os.path.sep}"
    workspace_addresses = await Get(
        Owners,
        OwnersRequest(
            tuple(
                os.path.join(root_dir, workspace_dir, PackageJsonSourceField.default)
                for workspace_dir in parsed_package_json.get("workspaces", ())
                if workspace_dir != self_reference
            ),
            OwnersNotFoundBehavior.error,
        ),
    )
    workspace_tgts = await Get(UnexpandedTargets, Addresses, Addresses(tuple(workspace_addresses)))
    return await MultiGet(
        Get(PackageJson, ReadPackageJsonRequest(tgt[PackageJsonSourceField]))
        for tgt in workspace_tgts
        if tgt.has_field(PackageJsonSourceField)
    )


@rule
async def read_package_json(request: ReadPackageJsonRequest) -> PackageJson:
    snapshot = await Get(
        Snapshot, PathGlobs, request.source.path_globs(UnmatchedBuildFileGlobs.error)
    )

    digest_content = await Get(DigestContents, Digest, snapshot.digest)
    parsed_package_json = json.loads(digest_content[0].content)
    root_dir = os.path.dirname(snapshot.files[0])

    workspace_pkg_jsons = await _read_workspaces_for(root_dir, parsed_package_json)

    return PackageJson(
        content=FrozenDict.deep_freeze(parsed_package_json),
        name=parsed_package_json["name"],
        version=parsed_package_json["version"],
        snapshot=snapshot,
        workspaces=workspace_pkg_jsons,
    )


@rule
async def all_package_json_targets(targets: AllUnexpandedTargets) -> AllPackageJsonTargets:
    return AllPackageJsonTargets(tgt for tgt in targets if tgt.has_field(PackageJsonSourceField))


@rule
async def all_package_json(targets: AllPackageJsonTargets) -> AllPackageJson:
    return AllPackageJson(
        await MultiGet(
            Get(PackageJson, ReadPackageJsonRequest(tgt[PackageJsonSourceField])) for tgt in targets
        )
    )


def target_types() -> Iterable[type[Target]]:
    return [PackageJsonTarget]


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *graph.rules(),
        *dependencies.rules(),
        *stripped_source_files.rules(),
        *fs.rules(),
        *collect_rules(),
    ]
