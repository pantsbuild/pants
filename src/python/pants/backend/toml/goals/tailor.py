# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.toml.subsystems.toml_setup import TomlSetup
from pants.backend.toml.target_types import TomlSourcesGeneratorTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PutativeTomlTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate TOML targets to create")
async def find_putative_targets(
    req: PutativeTomlTargetsRequest,
    all_owned_sources: AllOwnedSources,
    toml_setup: TomlSetup,
) -> PutativeTargets:
    if not toml_setup.tailor:
        return PutativeTargets()
    all_toml_files = await Get(Paths, PathGlobs, req.path_globs("*.toml"))
    unowned_toml_files = set(all_toml_files.files) - set(all_owned_sources)
    logger.debug(unowned_toml_files)
    pts = []
    for paths in unowned_toml_files:
        for dirname, filenames in group_by_dir(paths).items():
            pts.append(
                PutativeTarget.for_target_type(
                    TomlSourcesGeneratorTarget,
                    path=dirname,
                    name=None,
                    triggering_sources=sorted(filenames),
                )
            )
    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeTomlTargetsRequest),
    ]
