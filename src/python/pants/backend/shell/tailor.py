# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.shell.shell_setup import ShellSetup
from pants.backend.shell.target_types import (
    ShellSourcesGeneratorTarget,
    Shunit2TestsGeneratorSourcesField,
    Shunit2TestsGeneratorTarget,
)
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    group_by_dir,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.source.filespec import Filespec, matches_filespec
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeShellTargetsRequest(PutativeTargetsRequest):
    pass


def classify_source_files(paths: Iterable[str]) -> dict[type[Target], set[str]]:
    """Returns a dict of target type -> files that belong to targets of that type."""
    tests_filespec = Filespec(includes=list(Shunit2TestsGeneratorSourcesField.default))
    test_filenames = set(
        matches_filespec(tests_filespec, paths=[os.path.basename(path) for path in paths])
    )
    test_files = {path for path in paths if os.path.basename(path) in test_filenames}
    sources_files = set(paths) - test_files
    return {Shunit2TestsGeneratorTarget: test_files, ShellSourcesGeneratorTarget: sources_files}


@rule(level=LogLevel.DEBUG, desc="Determine candidate shell targets to create")
async def find_putative_targets(
    req: PutativeShellTargetsRequest, all_owned_sources: AllOwnedSources, shell_setup: ShellSetup
) -> PutativeTargets:
    if not shell_setup.tailor:
        return PutativeTargets()

    all_shell_files = await Get(Paths, PathGlobs, req.path_globs("*.sh"))
    unowned_shell_files = set(all_shell_files.files) - set(all_owned_sources)
    classified_unowned_shell_files = classify_source_files(unowned_shell_files)
    pts = []
    for tgt_type, paths in classified_unowned_shell_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            name = "tests" if tgt_type == Shunit2TestsGeneratorTarget else None
            pts.append(
                PutativeTarget.for_target_type(
                    tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
                )
            )
    return PutativeTargets(pts)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeShellTargetsRequest)]
