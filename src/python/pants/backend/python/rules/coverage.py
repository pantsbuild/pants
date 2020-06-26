# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
from dataclasses import dataclass
from io import StringIO
from pathlib import PurePath
from textwrap import dedent
from typing import Optional, Tuple, cast

from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import PythonSources, PythonTestsSources
from pants.core.goals.test import (
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReports,
    CoverageReportType,
    FilesystemCoverageReport,
)
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    AddPrefix,
    Digest,
    FileContent,
    InputFilesContent,
    MergeDigests,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Target, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


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
            type=CoverageReportType,
            default=CoverageReportType.CONSOLE,
            help="Which coverage report type to emit.",
        )
        register(
            "--output-dir",
            type=str,
            default=str(PurePath("dist", "coverage", "python")),
            advanced=True,
            help="Path to write the Pytest Coverage report to. Must be relative to build root.",
        )
        register(
            "--omit-test-sources",
            type=bool,
            default=False,
            advanced=True,
            help="Whether to exclude the test files in coverage measurement.",
        )

    @property
    def filter(self) -> Tuple[str, ...]:
        return tuple(self.options.filter)

    @property
    def report(self) -> CoverageReportType:
        return cast(CoverageReportType, self.options.report)

    @property
    def output_dir(self) -> PurePath:
        return PurePath(self.options.output_dir)

    @property
    def omit_test_sources(self) -> bool:
        return cast(bool, self.options.omit_test_sources)


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    address: Address
    digest: Digest


class PytestCoverageDataCollection(CoverageDataCollection):
    element_type = PytestCoverageData


@dataclass(frozen=True)
class CoverageConfigRequest:
    targets: FrozenOrderedSet[Target]


@dataclass(frozen=True)
class CoverageConfig:
    digest: Digest


@rule
async def create_coverage_config(
    request: CoverageConfigRequest, coverage_subsystem: CoverageSubsystem, log_level: LogLevel
) -> CoverageConfig:
    default_config = dedent(
        """
        [run]
        branch = True
        relative_files = True
        """
    )
    cp = configparser.ConfigParser()
    cp.read_string(default_config)

    test_sources = (
        await Get(
            SourceFiles,
            AllSourceFilesRequest(
                tgt[PythonTestsSources]
                for tgt in request.targets
                if tgt.has_field(PythonTestsSources)
            ),
        )
        if coverage_subsystem.omit_test_sources
        else SourceFiles(EMPTY_SNAPSHOT)
    )
    if coverage_subsystem.omit_test_sources:
        cp.set("run", "omit", ",".join(test_sources.files))

    if log_level in (LogLevel.DEBUG, LogLevel.TRACE):
        # See https://coverage.readthedocs.io/en/coverage-5.1/cmd.html?highlight=debug#diagnostics.
        cp.set("run", "debug", "\n\ttrace\n\tconfig")

    config_stream = StringIO()
    cp.write(config_stream)
    config_content = config_stream.getvalue()

    digest = await Get(
        Digest, InputFilesContent([FileContent(".coveragerc", config_content.encode())])
    )
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
class NoOpData:
    """A run over the entire transitive closure to ensure that every file has coverage data.

    We expect each file to have 0% associated with it. That's okay, because it will get merged in
    with the actual data from tests.
    """

    digest: Digest


@rule
async def prepare_no_op_data(
    coverage_setup: CoverageSetup,
    transitive_targets: TransitiveTargets,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> NoOpData:
    coverage_config_request = Get(CoverageConfig, CoverageConfigRequest(transitive_targets.closure))
    sources_request = Get(
        SourceFiles,
        AllSourceFilesRequest(
            tgt[PythonSources] for tgt in transitive_targets.closure if tgt.has_field(PythonSources)
        ),
    )
    coverage_config, sources = await MultiGet(coverage_config_request, sources_request)
    input_digest = await Get(
        Digest,
        MergeDigests([coverage_config.digest, coverage_setup.pex.digest, sources.snapshot.digest]),
    )
    process = coverage_setup.pex.create_process(
        pex_path=f"./{coverage_setup.pex.output_filename}",
        # `-m pydoc` will simply print out help instructions.
        pex_args=(
            "run",
            "--source=.",
            f"--omit={coverage_setup.pex.output_filename}/*",
            "-m",
            "pydoc",
        ),
        input_digest=input_digest,
        output_files=(".coverage",),
        description=f"Run a no-op Coverage command to ensure that every file is reported on.",
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
    )
    result = await Get(ProcessResult, Process, process)
    prefixed_digest = await Get(Digest, AddPrefix(result.output_digest, "__no_op_data"))
    return NoOpData(prefixed_digest)


@dataclass(frozen=True)
class MergedCoverageData:
    coverage_data: Digest


@rule(desc="Merge Pytest coverage data")
async def merge_coverage_data(
    data_collection: PytestCoverageDataCollection,
    no_op_data: NoOpData,
    coverage_setup: CoverageSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> MergedCoverageData:
    # We prefix each .coverage file with its corresponding address to avoid collisions.
    coverage_digests = await MultiGet(
        Get(Digest, AddPrefix(data.digest, prefix=data.address.path_safe_spec))
        for data in data_collection
    )
    input_digest = await Get(
        Digest, MergeDigests((*coverage_digests, coverage_setup.pex.digest, no_op_data.digest))
    )
    prefixes = (
        # *sorted(f"{data.address.path_safe_spec}/.coverage" for data in data_collection),
        "__no_op_data/.coverage",
    )
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


@rule(desc="Generate Pytest coverage report")
async def generate_coverage_report(
    merged_coverage_data: MergedCoverageData,
    coverage_setup: CoverageSetup,
    coverage_subsystem: CoverageSubsystem,
    transitive_targets: TransitiveTargets,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CoverageReports:
    """Takes all Python test results and generates a single coverage report."""
    coverage_config_request = Get(CoverageConfig, CoverageConfigRequest(transitive_targets.closure))
    sources_request = Get(
        SourceFiles,
        AllSourceFilesRequest(
            tgt[PythonSources] for tgt in transitive_targets.closure if tgt.has_field(PythonSources)
        ),
    )
    coverage_config, sources = await MultiGet(coverage_config_request, sources_request)
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

    report_type = coverage_subsystem.report
    process = coverage_setup.pex.create_process(
        pex_path=f"./{coverage_setup.pex.output_filename}",
        # We pass `--ignore-errors` because Pants dynamically injects missing `__init__.py` files
        # and this will cause Coverage to fail.
        pex_args=(report_type.report_name, "--ignore-errors"),
        input_digest=input_digest,
        output_directories=("htmlcov",),
        output_files=("coverage.xml",),
        description=f"Generate Pytest {report_type.report_name} coverage report.",
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
    )
    result = await Get(ProcessResult, Process, process)

    if report_type == CoverageReportType.CONSOLE:
        return CoverageReports((ConsoleCoverageReport(result.stdout.decode()),))

    report_file: Optional[PurePath] = None
    if report_type == CoverageReportType.HTML:
        report_file = coverage_subsystem.output_dir / "htmlcov" / "index.html"
    elif report_type == CoverageReportType.XML:
        report_file = coverage_subsystem.output_dir / "coverage.xml"
    fs_report = FilesystemCoverageReport(
        report_type=report_type,
        result_digest=result.output_digest,
        directory_to_materialize_to=coverage_subsystem.output_dir,
        report_file=report_file,
    )
    return CoverageReports((fs_report,))


def rules():
    return [
        create_coverage_config,
        generate_coverage_report,
        merge_coverage_data,
        prepare_no_op_data,
        setup_coverage,
        SubsystemRule(CoverageSubsystem),
        UnionRule(CoverageDataCollection, PytestCoverageDataCollection),
    ]
