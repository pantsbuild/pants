# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
from dataclasses import dataclass
from io import StringIO
from pathlib import PurePath
from typing import List, Optional, Sequence, Tuple

from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.python_sources import (
    UnstrippedPythonSources,
    UnstrippedPythonSourcesRequest,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.core.goals.test import (
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReport,
    CoverageReports,
    CoverageReportType,
    FilesystemCoverageReport,
)
from pants.engine.addresses import Address
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import TransitiveTargets
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup

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


class CoverageSubsystem(PythonToolBase):
    """Configuration for Python test coverage measurement."""

    options_scope = "coverage-py"
    default_version = "coverage>=5.0.3,<5.1"
    default_entry_point = "coverage"
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
    if "test_runner.pex/*" not in omit_elements:
        omit_elements.append("test_runner.pex/*")
    run_section["omit"] = "\n".join(omit_elements)


@rule
async def create_coverage_config(coverage: CoverageSubsystem) -> CoverageConfig:
    config_path: Optional[str] = coverage.options.config
    coverage_config = configparser.ConfigParser()
    if config_path:
        config_snapshot = await Get(
            Snapshot,
            PathGlobs(
                globs=config_path,
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"the option `--{coverage.options_scope}-config`",
            ),
        )
        config_contents = await Get(DigestContents, Digest, config_snapshot.digest)
        coverage_config.read_string(config_contents[0].content.decode())
    _validate_and_update_config(coverage_config, config_path)
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
            requirements=PexRequirements(coverage.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                coverage.default_interpreter_constraints
            ),
            entry_point=coverage.get_entry_point(),
        ),
    )
    return CoverageSetup(pex)


@dataclass(frozen=True)
class MergedCoverageData:
    coverage_data: Digest


@rule(desc="Merge Pytest coverage data")
async def merge_coverage_data(
    data_collection: PytestCoverageDataCollection,
    coverage_setup: CoverageSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
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
    process = coverage_setup.pex.create_process(
        pex_path=f"./{coverage_setup.pex.output_filename}",
        pex_args=("combine", *prefixes),
        input_digest=input_digest,
        output_files=(".coverage",),
        description=f"Merge {len(prefixes)} Pytest coverage reports.",
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
    )
    result = await Get(ProcessResult, Process, process)
    return MergedCoverageData(result.output_digest)


@rule(desc="Generate Pytest coverage reports")
async def generate_coverage_reports(
    merged_coverage_data: MergedCoverageData,
    coverage_setup: CoverageSetup,
    coverage_config: CoverageConfig,
    coverage_subsystem: CoverageSubsystem,
    transitive_targets: TransitiveTargets,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CoverageReports:
    """Takes all Python test results and generates a single coverage report."""
    sources = await Get(
        UnstrippedPythonSources,
        UnstrippedPythonSourcesRequest(transitive_targets.closure, include_resources=False),
    )
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                merged_coverage_data.coverage_data,
                coverage_config.digest,
                coverage_setup.pex.digest,
                sources.snapshot.digest,
            )
        ),
    )

    processes = []
    report_types = []
    coverage_reports: List[CoverageReport] = []
    for report_type in coverage_subsystem.reports:
        if report_type == CoverageReportType.RAW:
            coverage_reports.append(
                FilesystemCoverageReport(
                    report_type=CoverageReportType.RAW,
                    result_digest=merged_coverage_data.coverage_data,
                    directory_to_materialize_to=coverage_subsystem.output_dir,
                    report_file=coverage_subsystem.output_dir / ".coverage",
                )
            )
            continue
        report_types.append(report_type)
        processes.append(
            coverage_setup.pex.create_process(
                pex_path=f"./{coverage_setup.pex.output_filename}",
                # We pass `--ignore-errors` because Pants dynamically injects missing `__init__.py` files
                # and this will cause Coverage to fail.
                pex_args=(report_type.report_name, "--ignore-errors"),
                input_digest=input_digest,
                output_directories=("htmlcov",) if report_type == CoverageReportType.HTML else None,
                output_files=("coverage.xml",) if report_type == CoverageReportType.XML else None,
                description=f"Generate Pytest {report_type.report_name} coverage report.",
                python_setup=python_setup,
                subprocess_encoding_environment=subprocess_encoding_environment,
            )
        )
    results = await MultiGet(Get(ProcessResult, Process, process) for process in processes)
    coverage_reports.extend(
        _get_coverage_reports(coverage_subsystem.output_dir, report_types, results)
    )
    return CoverageReports(tuple(coverage_reports))


def _get_coverage_reports(
    output_dir: PurePath,
    report_types: Sequence[CoverageReportType],
    results: Tuple[ProcessResult, ...],
) -> List[CoverageReport]:
    coverage_reports: List[CoverageReport] = []
    for result, report_type in zip(results, report_types):
        if report_type == CoverageReportType.CONSOLE:
            coverage_reports.append(ConsoleCoverageReport(result.stdout.decode()))
            continue

        report_file: Optional[PurePath] = None
        if report_type == CoverageReportType.HTML:
            report_file = output_dir / "htmlcov" / "index.html"
        elif report_type == CoverageReportType.XML:
            report_file = output_dir / "coverage.xml"
        else:
            raise ValueError(f"Invalid coverage report type: {report_type}")
        coverage_reports.append(
            FilesystemCoverageReport(
                report_type=report_type,
                result_digest=result.output_digest,
                directory_to_materialize_to=output_dir,
                report_file=report_file,
            )
        )

    return coverage_reports


def rules():
    return [
        create_coverage_config,
        generate_coverage_reports,
        merge_coverage_data,
        setup_coverage,
        SubsystemRule(CoverageSubsystem),
        UnionRule(CoverageDataCollection, PytestCoverageDataCollection),
    ]
