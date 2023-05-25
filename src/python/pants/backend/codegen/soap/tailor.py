# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.soap.soap_subsystem import SoapSubsystem
from pants.backend.codegen.soap.target_types import WsdlSourcesGeneratorTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeWsdlTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate WSDL targets to create")
async def find_putative_targets(
    req: PutativeWsdlTargetsRequest,
    all_owned_sources: AllOwnedSources,
    soap_subsystem: SoapSubsystem,
) -> PutativeTargets:
    if not soap_subsystem.tailor:
        return PutativeTargets()

    all_wsdl_files = await Get(Paths, PathGlobs, req.path_globs("*.wsdl"))
    unowned_wsdl_files = set(all_wsdl_files.files) - set(all_owned_sources)
    pts = [
        PutativeTarget.for_target_type(
            WsdlSourcesGeneratorTarget,
            path=dirname,
            name=None,
            triggering_sources=sorted(filenames),
        )
        for dirname, filenames in group_by_dir(unowned_wsdl_files).items()
    ]
    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeWsdlTargetsRequest),
    ]
