# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from pathlib import PurePath
from typing import List, Optional, Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.test import (
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReport,
    CoverageReports,
    FilesystemCoverageReport,
)
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option
from pants.util.logging import LogLevel

"""
An overview:

Step 1: Run each test with the appropriate `--cov` arguments.
In `python_test_runner.py`, we pass options so that the pytest-cov plugin runs and records which
lines were encountered in the test. For each test, it will save a `.coverage` file (SQLite DB
format).

Step 2: Merge the results with `coverage combine`.
We now have a bunch of individual `PytestCoverageData` values, each with their own `.coverage` file.
We run `coverage combine` to convert this into a single `.coverage` file.

Step 3: Generate the report with `coverage {html,xml,console}`.
All the files in the single merged `.coverage` file are still stripped, and we want to generate a
report with the source roots restored. Coverage requires that the files it's reporting on be present
when it generates the report, so we populate all the source files.

Step 4: `test.py` outputs the final report.
"""


class CoverageReportType(Enum):
    CONSOLE = ("console", "report")
    XML = ("xml", None)
    HTML = ("html", None)
    RAW = ("raw", None)
    JSON = ("json", None)

    _report_name: str

    def __new__(cls, value: str, report_name: Optional[str] = None) -> "CoverageReportType":
        member: "CoverageReportType" = object.__new__(cls)
        member._value_ = value
        member._report_name = report_name if report_name is not None else value
        return member

    @property
    def report_name(self) -> str:
        return self._report_name

    @property
    def value(self) -> str:
        return cast(str, super().value)


class CoverageSubsystem(PythonToolBase):
    """Configuration for Python test coverage measurement."""

    options_scope = "coverage-py"
    default_version = "coverage>=5.0.3,<5.1"
    default_entry_point = "coverage"
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--filter",
            type=list,
            member_type=str,
            default=None,
            help=(
                "A list of Python modules to use in the coverage report, e.g. "
                "`['helloworld_test', 'helloworld.util.dirutil']. The modules are recursive: any "
                "submodules will be included. If you leave this off, the coverage report will "
                "include every file in the transitive closure of the address/file arguments; "
                "for example, `test ::` will include every Python file in your project, whereas "
                "`test project/app_test.py` will include `app_test.py` and any of its transitive "
                "dependencies."
            ),
        )
        register(
            "--report",
            type=list,
            member_type=CoverageReportType,
            default=[CoverageReportType.CONSOLE],
            help="Which coverage report type(s) to emit.",
        )
        register(
            "--output-dir",
            type=str,
            default=str(PurePath("dist", "coverage", "python")),
            advanced=True,
            help="Path to write the Pytest Coverage report to. Must be relative to build root.",
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help="Path to `.coveragerc` or alternative coverage config file",
        )

    @property
    def filter(self) -> Tuple[str, ...]:
        return tuple(self.options.filter)

    @property
    def reports(self) -> Tuple[CoverageReportType, ...]:
        return tuple(self.options.report)

    @property
    def output_dir(self) -> PurePath:
        return PurePath(self.options.output_dir)

    @property
    def config(self) -> Optional[str]:
        return cast(Optional[str], self.options.config)


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    address: Address
    digest: Digest


class PytestCoverageDataCollection(CoverageDataCollection):
    element_type = PytestCoverageData


@dataclass(frozen=True)
class CoverageConfig:
    digest: Digest


def _validate_and_update_config(
    coverage_config: configparser.ConfigParser, config_path: Optional[str]
) -> None:
    if not coverage_config.has_section("run"):
        coverage_config.add_section("run")
    run_section = coverage_config["run"]
    relative_files_str = run_section.get("relative_files", "True")
    if relative_files_str.lower() != "true":
        raise ValueError(
            f"relative_files under the 'run' section must be set to True. config file: {config_path}"
        )
    coverage_config.set("run", "relative_files", "True")
    omit_elements = [em for em in run_section.get("omit", "").split("\n")] or ["\n"]
    if "pytest.pex/*" not in omit_elements:
        omit_elements.append("pytest.pex/*")
    run_section["omit"] = "\n".join(omit_elements)


@rule
async def create_coverage_config(coverage: CoverageSubsystem) -> CoverageConfig:
    coverage_config = configparser.ConfigParser()
    if coverage.config:
        config_contents = await Get(
            DigestContents,
            PathGlobs(
                globs=(coverage.config,),
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"the option `--{coverage.options_scope}-config`",
            ),
        )
        coverage_config.read_string(config_contents[0].content.decode())
    _validate_and_update_config(coverage_config, coverage.config)
    config_stream = StringIO()
    coverage_config.write(config_stream)
    config_content = config_stream.getvalue()
    digest = await Get(Digest, CreateDigest([FileContent(".coveragerc", config_content.encode())]))
    return CoverageConfig(digest)


@dataclass(frozen=True)
class CoverageSetup:
    pex: Pex


@rule
async def setup_coverage(coverage: CoverageSubsystem) -> CoverageSetup:
    pex = await Get(
        Pex,
        PexRequest(
            output_filename="coverage.pex",
            internal_only=True,
            requirements=PexRequirements(coverage.all_requirements),
            interpreter_constraints=PexInterpreterConstraints(coverage.interpreter_constraints),
            entry_point=coverage.entry_point,
        ),
    )
    return CoverageSetup(pex)


@dataclass(frozen=True)
class MergedCoverageData:
    coverage_data: Digest


@rule(desc="Merge Pytest coverage data", level=LogLevel.DEBUG)
async def merge_coverage_data(
    data_collection: PytestCoverageDataCollection, coverage_setup: CoverageSetup
) -> MergedCoverageData:
    if len(data_collection) == 1:
        return MergedCoverageData(data_collection[0].digest)
    # We prefix each .coverage file with its corresponding address to avoid collisions.
    coverage_digests = await MultiGet(
        Get(Digest, AddPrefix(data.digest, prefix=data.address.path_safe_spec))
        for data in data_collection
    )
    input_digest = await Get(Digest, MergeDigests((*coverage_digests, coverage_setup.pex.digest)))
    prefixes = sorted(f"{data.address.path_safe_spec}/.coverage" for data in data_collection)
    result = await Get(
        ProcessResult,
        PexProcess(
            coverage_setup.pex,
            argv=("combine", *prefixes),
            input_digest=input_digest,
            output_files=(".coverage",),
            description=f"Merge {len(prefixes)} Pytest coverage reports.",
            level=LogLevel.DEBUG,
        ),
    )
    return MergedCoverageData(result.output_digest)


@rule(desc="Generate Pytest coverage reports", level=LogLevel.DEBUG)
async def generate_coverage_reports(
    merged_coverage_data: MergedCoverageData,
    coverage_setup: CoverageSetup,
    coverage_config: CoverageConfig,
    coverage_subsystem: CoverageSubsystem,
    all_used_addresses: Addresses,
) -> CoverageReports:
    """Takes all Python test results and generates a single coverage report."""
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(all_used_addresses))
    sources = await Get(
        PythonSourceFiles,
        # Coverage sometimes includes non-Python files in its `.coverage` data. We need to
        # ensure that they're present when generating the report. We include all the files included
        # by `pytest_runner.py`.
        PythonSourceFilesRequest(
            transitive_targets.closure, include_files=True, include_resources=True
        ),
    )
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                merged_coverage_data.coverage_data,
                coverage_config.digest,
                coverage_setup.pex.digest,
                sources.source_files.snapshot.digest,
            )
        ),
    )

    pex_processes = []
    report_types = []
    result_snapshot = await Get(Snapshot, Digest, merged_coverage_data.coverage_data)
    coverage_reports: List[CoverageReport] = []
    for report_type in coverage_subsystem.reports:
        if report_type == CoverageReportType.RAW:
            coverage_reports.append(
                FilesystemCoverageReport(
                    report_type=CoverageReportType.RAW.value,
                    result_snapshot=result_snapshot,
                    directory_to_materialize_to=coverage_subsystem.output_dir,
                    report_file=coverage_subsystem.output_dir / ".coverage",
                )
            )
            continue
        report_types.append(report_type)
        output_file = (
            f"coverage.{report_type.value}"
            if report_type in {CoverageReportType.XML, CoverageReportType.JSON}
            else None
        )
        pex_processes.append(
            PexProcess(
                coverage_setup.pex,
                argv=(report_type.report_name,),
                input_digest=input_digest,
                output_directories=("htmlcov",) if report_type == CoverageReportType.HTML else None,
                output_files=(output_file,) if output_file else None,
                description=f"Generate Pytest {report_type.report_name} coverage report.",
                level=LogLevel.DEBUG,
            )
        )
    results = await MultiGet(Get(ProcessResult, PexProcess, process) for process in pex_processes)
    result_stdouts = tuple(res.stdout for res in results)
    result_snapshots = await MultiGet(Get(Snapshot, Digest, res.output_digest) for res in results)

    coverage_reports.extend(
        _get_coverage_report(coverage_subsystem.output_dir, report_type, stdout, snapshot)
        for (report_type, stdout, snapshot) in zip(report_types, result_stdouts, result_snapshots)
    )

    return CoverageReports(tuple(coverage_reports))


def _get_coverage_report(
    output_dir: PurePath,
    report_type: CoverageReportType,
    result_stdout: bytes,
    result_snapshot: Snapshot,
) -> CoverageReport:
    if report_type == CoverageReportType.CONSOLE:
        return ConsoleCoverageReport(result_stdout.decode())

    report_file: Optional[PurePath]
    if report_type == CoverageReportType.HTML:
        report_file = output_dir / "htmlcov" / "index.html"
    elif report_type == CoverageReportType.XML:
        report_file = output_dir / "coverage.xml"
    elif report_type == CoverageReportType.JSON:
        report_file = output_dir / "coverage.json"
    else:
        raise ValueError(f"Invalid coverage report type: {report_type}")

    return FilesystemCoverageReport(
        report_type=report_type.value,
        result_snapshot=result_snapshot,
        directory_to_materialize_to=output_dir,
        report_file=report_file,
    )


def rules():
    return [*collect_rules(), UnionRule(CoverageDataCollection, PytestCoverageDataCollection)]
