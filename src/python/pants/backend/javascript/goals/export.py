# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.javascript.install_node_package import InstalledNodePackage, InstalledNodePackageRequest
from pants.backend.javascript.resolve import FirstPartyNodePackageResolves
from pants.backend.javascript.subsystems.nodejs import NodeJS
from pants.core.goals.export import (
    ExportRequest,
    ExportResult,
    ExportResults,
    ExportSubsystem,
)
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import (
    Digest, RemovePrefix,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule


@dataclass(frozen=True)
class ExportNodeModulesRequest(ExportRequest):
    pass


@dataclass(frozen=True)
class _ExportNodeModulesForResolveRequest(EngineAwareParameter):
    resolve: str


@dataclass(frozen=True)
class MaybeExportResult:
    result: ExportResult | None


@rule
async def export_node_modules_for_resolve(
    request: _ExportNodeModulesForResolveRequest,
    nodejs: NodeJS,
    union_membership: UnionMembership,
    resolves: FirstPartyNodePackageResolves,
) -> MaybeExportResult:
    resolve = request.resolve

    target = resolves.get(request.resolve)

    if not target:
        return MaybeExportResult(None)

    installation = await Get(InstalledNodePackage, InstalledNodePackageRequest(target.address))

    return MaybeExportResult(
        ExportResult(
            description=f"generated node_modules for {resolve} (using NodeJS {nodejs.version})",
            reldir=f"nodejs/modules/{resolve}",
            digest=await Get(Digest, RemovePrefix(installation.digest, installation.project_dir)),
            resolve=resolve,
        )
    )


@rule
async def export_node_modules(
    request: ExportNodeModulesRequest,
    export_subsys: ExportSubsystem,
) -> ExportResults:
    maybe_packages = await MultiGet(
        Get(MaybeExportResult, _ExportNodeModulesForResolveRequest(resolve))
        for resolve in export_subsys.options.resolve
    )
    return ExportResults(pkg.result for pkg in maybe_packages if pkg.result is not None)


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportRequest, ExportNodeModulesRequest),
    ]
