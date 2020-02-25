# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Tuple, Type

from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, FileContent, InputFilesContent
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, rule
from pants.rules.core.test import (
    AddressAndTestResult,
    CoverageData,
    CoverageDataBatch,
    CoverageReport,
)

DEFAULT_COVERAGE_CONFIG = dedent(
    f"""
    [run]
    branch = True
    timid = False
    relative_files = True
    """
)


def get_coveragerc_input(coveragerc_content: str) -> InputFilesContent:
    return InputFilesContent(
        [FileContent(path=".coveragerc", content=coveragerc_content.encode()),]
    )


def get_packages_to_cover(
    *, target: PythonTestsAdaptor, source_root_stripped_file_paths: Tuple[str, ...],
) -> Tuple[str, ...]:
    if hasattr(target, "coverage"):
        return tuple(sorted(set(target.coverage)))
    return tuple(
        sorted(
            {
                os.path.dirname(source_root_stripped_source_file_path).replace(
                    os.sep, "."
                )  # Turn file paths into package names.
                for source_root_stripped_source_file_path in source_root_stripped_file_paths
            }
        )
    )


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    digest: Digest

    @property
    def batch_cls(self) -> Type["PytestCoverageDataBatch"]:
        return PytestCoverageDataBatch


@dataclass(frozen=True)
class PytestCoverageDataBatch(CoverageDataBatch):
    addresses_and_test_results: Tuple[AddressAndTestResult, ...]


@rule
def generate_coverage_report(data_batch: PytestCoverageDataBatch,) -> CoverageReport:
    return CoverageReport(EMPTY_DIRECTORY_DIGEST, PurePath("fake"))


def rules():
    return [generate_coverage_report, UnionRule(CoverageDataBatch, PytestCoverageDataBatch)]
