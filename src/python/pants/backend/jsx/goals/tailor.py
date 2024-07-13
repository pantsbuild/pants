# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.jsx.target_types import JSX_FILE_EXTENSIONS, JSXSourcesGeneratorTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.core.util_rules.ownership import get_unowned_files_for_globs
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeJSXTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate JSX targets to create")
async def find_putative_jsx_targets(
    req: PutativeJSXTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    unowned_jsx_files = await get_unowned_files_for_globs(
        req, all_owned_sources, (f"*{ext}" for ext in JSX_FILE_EXTENSIONS)
    )

    return PutativeTargets(
        PutativeTarget.for_target_type(
            JSXSourcesGeneratorTarget, path=dirname, name=None, triggering_sources=sorted(filenames)
        )
        for dirname, filenames in group_by_dir(unowned_jsx_files).items()
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeJSXTargetsRequest),
    )
