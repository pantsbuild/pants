# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import AllPackageJson, PackageJson
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess
from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
)
from pants.engine.internals.native_engine import AddPrefix, Digest, RemovePrefix
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class GeneratePackageLockJsonFile(GenerateLockfile):
    pkg_json: PackageJson


class KnownPackageJsonUserResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


class RequestedPackageJsonUserResolveNames(RequestedUserResolveNames):
    pass


@rule
async def determine_package_json_user_resolves(
    _: KnownPackageJsonUserResolveNamesRequest, pkg_jsons: AllPackageJson
) -> KnownUserResolveNames:
    return KnownUserResolveNames(
        names=tuple(pkg.name for pkg in pkg_jsons),
        option_name="<generated>",
        requested_resolve_names_cls=RequestedPackageJsonUserResolveNames,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedPackageJsonUserResolveNames, pkg_jsons: AllPackageJson
) -> UserGenerateLockfiles:
    return UserGenerateLockfiles(
        GeneratePackageLockJsonFile(
            resolve_name=pkg.name,
            lockfile_dest=f"{pkg.root_dir}{os.path.sep}package-lock.json",
            pkg_json=pkg,
            diff=False,
        )
        for pkg in pkg_jsons
        if pkg.name in requested
    )


@rule
async def generate_lockfile_from_package_jsons(
    request: GeneratePackageLockJsonFile,
) -> GenerateLockfileResult:
    input_digest = await Get(
        Digest, RemovePrefix(request.pkg_json.digest, request.pkg_json.root_dir)
    )
    result = await Get(
        ProcessResult,
        NodeJSToolProcess,
        NodeJSToolProcess.npm(
            args=("install", "--package-lock-only"),
            description=f"generate package-lock.json for '{request.resolve_name}'.",
            input_digest=input_digest,
            output_files=("package-lock.json",),
        ),
    )
    output_digest = await Get(Digest, AddPrefix(result.output_digest, request.pkg_json.root_dir))
    return GenerateLockfileResult(output_digest, request.resolve_name, request.lockfile_dest)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *package_json.rules(),
        *nodejs.rules(),
        UnionRule(GenerateLockfile, GeneratePackageLockJsonFile),
        UnionRule(KnownUserResolveNamesRequest, KnownPackageJsonUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedPackageJsonUserResolveNames),
    )
