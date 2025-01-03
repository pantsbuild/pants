# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.k8s.k8s_subsystem import K8sSubsystem
from pants.backend.k8s.target_types import K8sSourcesTargetGenerator
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
class PutativeK8sTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate k8s targets to create")
async def find_putative_targets(
    req: PutativeK8sTargetsRequest,
    all_owned_sources: AllOwnedSources,
    k8s: K8sSubsystem,
) -> PutativeTargets:
    putative_targets = []

    if k8s.tailor_source_targets:
        all_k8s_files_globs = req.path_globs("*.yaml")
        all_k8s_files = await Get(Paths, PathGlobs, all_k8s_files_globs)
        unowned_k8s_files = set(all_k8s_files.files) - set(all_owned_sources)

        for dirname, filenames in group_by_dir(unowned_k8s_files).items():
            name = None
            putative_targets.append(
                PutativeTarget.for_target_type(
                    K8sSourcesTargetGenerator,
                    path=dirname,
                    name=name,
                    triggering_sources=sorted(filenames),
                )
            )

    return PutativeTargets(putative_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeK8sTargetsRequest),
    ]
