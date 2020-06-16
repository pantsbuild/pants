# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import json
from dataclasses import dataclass
from io import StringIO
from pathlib import PurePath
from textwrap import dedent
from typing import Optional

import pkg_resources

from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import PythonSources
from pants.core.goals.test import (
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReports,
    CoverageReportType,
    FilesystemCoverageReport,
)
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSourcesFieldRequest,
)
from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, Digest, FileContent, InputFilesContent, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import TransitiveTargets
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup

"""
An overview of how Pytest Coverage works with Pants:

Step 1: Run each test with the appropriate `--cov` arguments.
In `python_test_runner.py`, we pass options so that the pytest-cov plugin runs and records which 
lines were encountered in the test. For each test, it will save a `.coverage` file (SQLite DB 
format). The files stored in `.coverage` will be stripped of source roots. We load up our 
custom Pants coverage plugin, but the plugin doesn't actually do anything yet. We only load our 
plugin because Coverage expects to find the plugin in the `.coverage` file in the later steps.

Step 2: Merge the results with `coverage combine`.
We now have a bunch of individual `PytestCoverageData` values. We run
`coverage combine` to convert this into a single `.coverage` file.

Step 3: Generate the report with `coverage {html,xml,console}`.
All the files in the single merged `.coverage` file are still stripped, and we want to generate a 
report with the source roots restored. Coverage requires that the files it's reporting 
on be present in its environment when it generates the report, so we populate all the unstripped 
source files. Our plugin then uses the stripped filename -> source root mapping to determine the 
correct file name for the report.

Step 4: `test.py` outputs the final report.
"""

COVERAGE_PLUGIN_MODULE_NAME = "__pants_coverage_plugin__"


@dataclass(frozen=True)
class CoveragePlugin:
    digest: Digest


@rule
async def prepare_coverage_plugin() -> CoveragePlugin:
    plugin_file = FileContent(
        f"{COVERAGE_PLUGIN_MODULE_NAME}.py",
        pkg_resources.resource_string(__name__, "coverage_plugin/plugin.py"),
    )
    digest = await Get[Digest](InputFilesContent([plugin_file]))
    return CoveragePlugin(digest)


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    address: Address
    digest: Digest


class PytestCoverageDataCollection(CoverageDataCollection):
    element_type = PytestCoverageData


@dataclass(frozen=True)
class CoverageConfigRequest:
    is_test_time: bool


@dataclass(frozen=True)
class CoverageConfig:
    digest: Digest


@rule
async def create_coverage_config(
    request: CoverageConfigRequest, transitive_targets: TransitiveTargets
) -> CoverageConfig:
    all_stripped_sources = await MultiGet(
        Get(SourceRootStrippedSources, StripSourcesFieldRequest(tgt[PythonSources]))
        for tgt in transitive_targets.closure
        if tgt.has_field(PythonSources)
    )
    # We map stripped file names to their source roots so that we can map back to the actual
    # sources file when generating coverage reports. For example,
    # {'helloworld/project.py': 'src/python'}.
    stripped_files_to_source_roots = {}
    for stripped_sources in all_stripped_sources:
        stripped_files_to_source_roots.update(
            {f: root for root, files in stripped_sources.root_to_relfiles.items() for f in files}
        )

    default_config = dedent(
        """
        [run]
        branch = True
        timid = False
        relative_files = True
        """
    )

    cp = configparser.ConfigParser()
    cp.read_string(default_config)
    cp.set("run", "plugins", COVERAGE_PLUGIN_MODULE_NAME)
    cp.add_section(COVERAGE_PLUGIN_MODULE_NAME)
    cp.set(
        COVERAGE_PLUGIN_MODULE_NAME,
        "stripped_files_to_source_roots",
        json.dumps(stripped_files_to_source_roots),
    )
    cp.set(COVERAGE_PLUGIN_MODULE_NAME, "test_time", json.dumps(request.is_test_time))

    config_stream = StringIO()
    cp.write(config_stream)
    config_content = config_stream.getvalue()

    digest = await Get[Digest](
        InputFilesContent([FileContent(".coveragerc", config_content.encode())])
    )
    return CoverageConfig(digest)


class PytestCoverage(PythonToolBase):
    options_scope = "pytest-coverage"
    default_version = "coverage>=5.0.3,<5.1"
    default_entry_point = "coverage"
    default_interpreter_constraints = ["CPython>=3.6"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--report-output-path",
            type=str,
            default=PurePath("dist", "coverage", "python").as_posix(),
            help="Path to write pytest coverage report to. Must be relative to build root.",
        )
        register(
            "--report",
            type=CoverageReportType,
            default=CoverageReportType.CONSOLE,
            help="Which coverage report type to emit.",
        )


@dataclass(frozen=True)
class CoverageSetup:
    pex: Pex


@rule
async def setup_coverage(coverage: PytestCoverage, plugin: CoveragePlugin) -> CoverageSetup:
    pex = await Get[Pex](
        PexRequest(
            output_filename="coverage.pex",
            requirements=PexRequirements(coverage.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                coverage.default_interpreter_constraints
            ),
            entry_point=coverage.get_entry_point(),
            sources=plugin.digest,
        )
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
    # We prefix each .coverage file with its corresponding address to avoid collisions.
    coverage_digests = await MultiGet(
        Get[Digest](AddPrefix(data.digest, prefix=data.address.path_safe_spec))
        for data in data_collection
    )
    coverage_config = await Get[CoverageConfig](CoverageConfigRequest(is_test_time=True))
    input_digest = await Get[Digest](
        MergeDigests((*coverage_digests, coverage_config.digest, coverage_setup.pex.digest)),
    )

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
    result = await Get[ProcessResult](Process, process)
    return MergedCoverageData(coverage_data=result.output_digest)


@rule(desc="Generate Pytest coverage report")
async def generate_coverage_report(
    merged_coverage_data: MergedCoverageData,
    coverage_setup: CoverageSetup,
    coverage_subsystem: PytestCoverage,
    transitive_targets: TransitiveTargets,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CoverageReports:
    """Takes all Python test results and generates a single coverage report."""
    coverage_config_request = Get(CoverageConfig, CoverageConfigRequest(is_test_time=False))
    unstripped_sources_request = Get(
        SourceFiles,
        AllSourceFilesRequest(
            tgt[PythonSources] for tgt in transitive_targets.closure if tgt.has_field(PythonSources)
        ),
    )
    coverage_config, unstripped_sources = await MultiGet(
        [coverage_config_request, unstripped_sources_request]
    )
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                merged_coverage_data.coverage_data,
                coverage_config.digest,
                coverage_setup.pex.digest,
                unstripped_sources.snapshot.digest,
            )
        ),
    )

    report_type = coverage_subsystem.options.report
    process = coverage_setup.pex.create_process(
        pex_path=f"./{coverage_setup.pex.output_filename}",
        # We pass `--ignore-errors` because Pants dynamically injects missing `__init__.py` files
        # and this will cause Coverage to fail.
        pex_args=(report_type.report_name, "--ignore-errors"),
        input_digest=input_digest,
        output_directories=("htmlcov",),
        output_files=("coverage.xml",),
        description="Generate Pytest coverage report.",
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
    )
    result = await Get[ProcessResult](Process, process)

    if report_type == CoverageReportType.CONSOLE:
        return CoverageReports((ConsoleCoverageReport(result.stdout.decode()),))

    report_dir = PurePath(coverage_subsystem.options.report_output_path)

    report_file: Optional[PurePath] = None
    if report_type == CoverageReportType.HTML:
        report_file = report_dir / "htmlcov" / "index.html"
    elif report_type == CoverageReportType.XML:
        report_file = report_dir / "coverage.xml"
    fs_report = FilesystemCoverageReport(
        result_digest=result.output_digest,
        directory_to_materialize_to=report_dir,
        report_file=report_file,
    )
    return CoverageReports((fs_report,))


def rules():
    return [
        prepare_coverage_plugin,
        create_coverage_config,
        generate_coverage_report,
        merge_coverage_data,
        setup_coverage,
        SubsystemRule(PytestCoverage),
        UnionRule(CoverageDataCollection, PytestCoverageDataCollection),
    ]
