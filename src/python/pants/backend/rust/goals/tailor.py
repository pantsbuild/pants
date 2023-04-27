# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.rust.target_types import RustCrateTarget
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


@dataclass(frozen=True)
class PutativeRustTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Rust targets to create")
async def find_putative_rust_targets(
    request: PutativeRustTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    putative_targets = []

    all_cargo_toml_files = await Get(
        Paths, PathGlobs, request.search_paths.path_globs("Cargo.toml")
    )
    unowned_cargo_toml_files = set(all_cargo_toml_files.files) - set(all_owned_sources)

    for dirname, filenames in group_by_dir(unowned_cargo_toml_files).items():
        putative_targets.append(
            PutativeTarget.for_target_type(
                RustCrateTarget,
                path=dirname,
                name=None,
                triggering_sources=sorted(filenames),
            )
        )

    return PutativeTargets(putative_targets)


def rules():
    return *collect_rules(), UnionRule(PutativeTargetsRequest, PutativeRustTargetsRequest)
