# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Set

from pants.backend.python.target_types import PythonLibrary, PythonTests, PythonTestsSources
from pants.base.specs import AddressSpecs, MaybeEmptyDescendantAddresses
from pants.core.goals.init import PutativeTarget, PutativeTargets, PutativeTargetsRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Sources, Targets
from pants.engine.unions import UnionRule
from pants.source.filespec import Filespec, matches_filespec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PutativePythonTargetsRequest:
    pass


def classify_source_files(paths: Iterable[str]) -> Dict[str, Set[str]]:
    """Returns a dict of target type alias -> files that belong to targets of that type."""
    tests_filespec = Filespec(includes=list(PythonTestsSources.default))
    test_filenames = set(
        matches_filespec(tests_filespec, paths=[os.path.basename(path) for path in paths])
    )
    test_files = {path for path in paths if os.path.basename(path) in test_filenames}
    library_files = set(paths) - test_files
    return {PythonTests.alias: test_files, PythonLibrary.alias: library_files}


def group_by_dir(paths: Iterable[str]) -> Dict[str, Set[str]]:
    """For a list of file paths, returns a dict of directory path -> files in that dir."""
    ret = defaultdict(set)
    for path in paths:
        dirname, filename = os.path.split(path)
        ret[dirname].add(filename)
    return ret


@rule
async def find_putative_targets(
    req: PutativePythonTargetsRequest,
) -> PutativeTargets:
    all_tgts = await Get(Targets, AddressSpecs([MaybeEmptyDescendantAddresses("")]))
    all_owned_sources = await Get(
        SourceFiles, SourceFilesRequest([tgt.get(Sources) for tgt in all_tgts])
    )

    all_py_files = await Get(Paths, PathGlobs(["**/*.py"]))
    unowned_py_files = set(all_py_files.files) - set(all_owned_sources.files)
    classified_unowned_py_files = classify_source_files(unowned_py_files)
    pts = []
    for tgt_type, paths in classified_unowned_py_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            name = "tests" if tgt_type == PythonTests.alias else os.path.basename(dirname)
            kwargs = {"name": name} if tgt_type == PythonTests.alias else {}
            pts.append(PutativeTarget(dirname, name, tgt_type, sorted(filenames), kwargs=kwargs))
    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativePythonTargetsRequest),
    ]
