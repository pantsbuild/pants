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
from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.internals import graph
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllUnexpandedTargets,
    Dependencies,
    SingleSourceField,
    Target,
    TargetGenerator,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import UnmatchedBuildFileGlobs
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

    @property
    def digest(self) -> Digest:
        return self.snapshot.digest

    @property
    def file(self) -> str:
        return self.snapshot.files[0]

    @property
    def root_dir(self) -> str:
        return os.path.dirname(self.file)


class AllPackageJsonTargets(Targets):
    pass


class AllPackageJson(Collection[PackageJson]):
    pass


@dataclass(frozen=True)
class ReadPackageJsonRequest:
    source: PackageJsonSourceField


@rule
async def read_package_json(request: ReadPackageJsonRequest) -> PackageJson:
    snapshot = await Get(
        Snapshot, PathGlobs, request.source.path_globs(UnmatchedBuildFileGlobs.error)
    )

    digest_content = await Get(DigestContents, Digest, snapshot.digest)
    package_json = json.loads(digest_content[0].content)

    return PackageJson(
        content=FrozenDict.deep_freeze(package_json),
        name=package_json["name"],
        version=package_json["version"],
        snapshot=snapshot,
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
