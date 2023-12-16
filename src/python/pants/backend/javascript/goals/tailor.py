# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.target_types import (
    JS_FILE_EXTENSIONS,
    JSSourcesGeneratorTarget,
    JSTestsGeneratorSourcesField,
    JSTestsGeneratorTarget,
)
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.core.util_rules.ownership import get_unowned_files_for_globs
from pants.core.util_rules.source_files import classify_files_for_sources_and_tests
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeJSTargetsRequest(PutativeTargetsRequest):
    pass


@dataclass(frozen=True)
class PutativePackageJsonTargetsRequest(PutativeTargetsRequest):
    pass


_LOG_DESCRIPTION_TEMPLATE = "Determine candidate {} to create"


@rule(level=LogLevel.DEBUG, desc=_LOG_DESCRIPTION_TEMPLATE.format("JS targets"))
async def find_putative_js_targets(
    req: PutativeJSTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    unowned_js_files = await get_unowned_files_for_globs(
        req, all_owned_sources, (f"*{ext}" for ext in JS_FILE_EXTENSIONS)
    )
    classified_unowned_js_files = classify_files_for_sources_and_tests(
        paths=unowned_js_files,
        test_file_glob=JSTestsGeneratorSourcesField.default,
        sources_generator=JSSourcesGeneratorTarget,
        tests_generator=JSTestsGeneratorTarget,
    )

    return PutativeTargets(
        PutativeTarget.for_target_type(
            tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
        )
        for tgt_type, paths, name in (dataclasses.astuple(f) for f in classified_unowned_js_files)
        for dirname, filenames in group_by_dir(paths).items()
    )


@rule(level=LogLevel.DEBUG, desc=_LOG_DESCRIPTION_TEMPLATE.format("package.json targets"))
async def find_putative_package_json_targets(
    req: PutativePackageJsonTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    unowned_package_json_files = await get_unowned_files_for_globs(
        req, all_owned_sources, (f"**{os.path.sep}package.json",)
    )

    putative_targets = [
        PutativeTarget.for_target_type(
            PackageJsonTarget, path=dirname, name=None, triggering_sources=[filename]
        )
        for dirname, filename in (os.path.split(file) for file in unowned_package_json_files)
    ]

    return PutativeTargets(putative_targets)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeJSTargetsRequest),
        UnionRule(PutativeTargetsRequest, PutativePackageJsonTargetsRequest),
    )
