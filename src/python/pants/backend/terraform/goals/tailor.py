# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.terraform.target_types import TerraformModulesGeneratorTarget
from pants.core.goals.tailor import (
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    group_by_dir,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


def longest_common_prefix(x: tuple[str, ...], y: tuple[str, ...]) -> tuple[str, ...]:
    """Find the longest common prefix between two sequences."""

    i = j = 0
    while i < len(x) and j < len(y):
        if x[i] != y[j]:
            break
        i = i + 1
        j = j + 1

    return x[:i]


def find_disjoint_longest_common_prefixes(
    raw_values: Iterable[tuple[str, ...]]
) -> set[tuple[str, ...]]:
    values = sorted(raw_values)

    if len(values) == 0:
        return set()
    elif len(values) == 1:
        return set(values)

    prefixes = set()
    current_prefix = values[0]

    i = 1
    while i < len(values):
        potential_prefix = longest_common_prefix(current_prefix, values[i])
        if potential_prefix:
            # If this item still has any common prefix with the current run of items, then
            # update the prefix to this potential prefix.
            current_prefix = potential_prefix
        else:
            # If there is no common prefix between this item and the current run of items, then
            # this run of items with a common prefix has ended. Record the current prefix and make
            # the current item be the next current prefix.
            prefixes.add(current_prefix)
            current_prefix = values[i]
        i += 1

    # Record any prefix from the last run of items.
    if current_prefix:
        prefixes.add(current_prefix)

    return prefixes


@dataclass(frozen=True)
class PutativeTerraformTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Terraform targets to create")
async def find_putative_terrform_modules_targets(
    request: PutativeTerraformTargetsRequest,
) -> PutativeTargets:
    all_terraform_files = await Get(Paths, PathGlobs, request.search_paths.path_globs("*.tf"))
    directory_to_files = {
        dir: files
        for dir, files in group_by_dir(all_terraform_files.files).items()
        if any(file.endswith(".tf") for file in files)
    }
    prefixes = find_disjoint_longest_common_prefixes(
        [PurePath(dir).parts for dir in directory_to_files.keys()]
    )

    putative_targets = [
        PutativeTarget.for_target_type(
            TerraformModulesGeneratorTarget,
            str(PurePath(*dir_parts)),
            "tf_mods",
            [str(PurePath(*dir_parts).joinpath("**/*.tf"))],
        )
        for dir_parts in prefixes
    ]

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeTerraformTargetsRequest)]
