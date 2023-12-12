# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
from dataclasses import dataclass
from typing import Iterable, Union

from pants.backend.typescript.target_types import (
    TS_FILE_EXTENSIONS,
    TypeScriptSourcesGeneratorTarget,
    TypeScriptTestsGeneratorSourcesField,
    TypeScriptTestsGeneratorTarget,
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
class PutativeTypeScriptTargetsRequest(PutativeTargetsRequest):
    pass


_LOG_DESCRIPTION_TEMPLATE = "Determine candidate {} to create"


@rule(level=LogLevel.DEBUG, desc=_LOG_DESCRIPTION_TEMPLATE.format("TypeScript targets"))
async def find_putative_ts_targets(
    req: PutativeTypeScriptTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    unowned_ts_files = await get_unowned_files_for_globs(
        req, all_owned_sources, (f"*{ext}" for ext in TS_FILE_EXTENSIONS)
    )
    classified_unowned_ts_files = classify_files_for_sources_and_tests(
        paths=unowned_ts_files,
        test_file_glob=TypeScriptTestsGeneratorSourcesField.default,
        sources_generator=TypeScriptSourcesGeneratorTarget,
        tests_generator=TypeScriptTestsGeneratorTarget,
    )

    return PutativeTargets(
        PutativeTarget.for_target_type(
            tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
        )
        for tgt_type, paths, name in (dataclasses.astuple(f) for f in classified_unowned_ts_files)
        for dirname, filenames in group_by_dir(paths).items()
    )


def rules() -> Iterable[Union[Rule, UnionRule]]:
    return (
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeTypeScriptTargetsRequest),
    )
