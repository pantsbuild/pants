# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
from dataclasses import dataclass
from pathlib import PurePath
from typing import Collection, Iterable, Union

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
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeTypeScriptTargetsRequest(PutativeTargetsRequest):
    pass


@dataclass(frozen=True)
class _ClassifiedSources:
    target_type: type[Target]
    files: Collection[str]
    name: Union[str, None] = None


def classify_source_files(paths: Iterable[str]) -> Iterable[_ClassifiedSources]:
    sources_files = set(paths)
    test_file_glob = TypeScriptTestsGeneratorSourcesField.default
    test_files = {
        path for path in paths if any(PurePath(path).match(glob) for glob in test_file_glob)
    }
    if sources_files:
        yield _ClassifiedSources(TypeScriptSourcesGeneratorTarget, files=sources_files - test_files)
    if test_files:
        yield _ClassifiedSources(TypeScriptTestsGeneratorTarget, test_files, "tests")


async def _get_unowned_files_for_globs(
    request: PutativeTargetsRequest,
    all_owned_sources: AllOwnedSources,
    filename_globs: Iterable[str],
) -> set[str]:
    matching_paths = await Get(Paths, PathGlobs, request.path_globs(*filename_globs))
    return set(matching_paths.files) - set(all_owned_sources)


_LOG_DESCRIPTION_TEMPLATE = "Determine candidate {} to create"


@rule(level=LogLevel.DEBUG, desc=_LOG_DESCRIPTION_TEMPLATE.format("TypeScript targets"))
async def find_putative_ts_targets(
    req: PutativeTypeScriptTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    unowned_ts_files = await _get_unowned_files_for_globs(
        req, all_owned_sources, (f"*{ext}" for ext in TS_FILE_EXTENSIONS)
    )
    classified_unowned_ts_files = classify_source_files(unowned_ts_files)

    return PutativeTargets(
        PutativeTarget.for_target_type(
            tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
        )
        for tgt_type, paths, name in map(dataclasses.astuple, classified_unowned_ts_files)
        for dirname, filenames in group_by_dir(paths).items()
    )


def rules() -> Iterable[Union[Rule, UnionRule]]:
    return (
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeTypeScriptTargetsRequest),
    )
