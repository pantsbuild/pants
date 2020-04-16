# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import json
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from pathlib import PurePath
from textwrap import dedent
from typing import Optional, Tuple

import pkg_resources

from pants.backend.python.rules.inject_init import InitInjectedSnapshot, InjectInitRequest
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.targets import PythonSources
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.address import Address
from pants.engine.fs import (
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    FileContent,
    FilesContent,
    InputFilesContent,
)
from pants.engine.isolated_process import Process, ProcessResult
from pants.engine.rules import RootRule, UnionRule, named_rule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Sources, Targets, TransitiveTargets
from pants.python.python_setup import PythonSetup
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.rules.core.test import (
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReport,
    FilesystemCoverageReport,
)
from pants.source.source_root import SourceRootConfig

# There are many moving parts in coverage, so here is a high level view of what's going on.

# Step 1.
# Test Time: the `run_python_test` rule executes pytest with `--cov` arguments.
#
# When we run tests on individual targets (in `python_test_runner.py`) we include a couple of
# arguments to pytest telling it to use coverage. We also add a coverage configuration file and a
# custom plugin to the environment in which the test is run (`.coveragerc` is generated, but the
# plugin code lives in `src/python/pants/backend/python/rules/coverage_plugin/plugin.py` and is
# copied in as is.). The test runs and coverage collects data and stores it in a sqlite db, which
# you can see in the working directory as `.coverage`. Along with the coverage data, it also
# stores some metadata about any plugins it was run with.
#
# Note: The pants coverage plugin does nothing at all during test time other than have itself
# mentioned in that DB. If the plugin is not mentioned in that DB then when we merge the data or
# generate the report coverage will not use the plugin, regardless of what is in it's configuration
# file. Because we run tests in an environment without source roots (meaning
# `src/python/foo/bar.py` is in the environment as `foo/bar.py`) all of the data in the resulting
# .coverage file references the files the source root stripped name - `foo/bar.py`
#
#
# Step 2.
# Merging the Results: The `merge_coverage_data` rule executes `coverage combine`.
#
# Once we've run the tests, we have a bunch `TestResult`s, each with its own coverage data file,
# named `.coverage`. In `merge_coverage_data` We stuff all these `.coverage` files into the same
# PEX, which requires prefixing the filenames with a unique identifier so they don't clobber each
# other. We then run `coverage combine foo/.coverage bar/.coverage baz/.coverage` to combine all
# that data into a single .coverage file.
#
#
# Step 3.
# Generating the Report: The `generate_coverage_report` rule executes `coverage html` or
# `coverage xml`
#
# Now we have one single `.coverage` file containing all our merged coverage data, with all the
# files referenced as `foo/bar.py` and we want to generate a single report where all those files
# will be referenced with their buildroot relative paths (`src/python/foo/bar.py`). Coverage
# requires that the files it's reporting on be present in its environment when it generates the
# report, so we build a pex with all the source files with their source roots intact, and
# *finally* our custom plugin starts doing some work. In our config file we've given a map from
# source root stripped file path to source root - `{'foo/bar.py': 'src/python`}` - As the report is
# generated, every time coverage needs a file, it asks our plugin and the plugin says, "Oh, you
# want `foo/bar.py`? Sure! Here's `src/python/foo/bar.py`". And then we get a nice report that
# references all the files with their buildroot relative names.
#
#
# Step 4.
# Materializing the Report on Disk: The `run_tests` rule exposes the report to the user.
#
# Now we have a directory full of html or an xml file full of coverage data and we want to expose
# it to the user. This step happens in `test.py` and should handle all kinds of coverage reports,
# not just pytest coverage. The test runner grabs all our individual test results and requests
# a CoverageReport, and once it has one, it writes it down in `dist/coverage` (or wherever the user
# has configured it.)


COVERAGE_PLUGIN_MODULE_NAME = "__pants_coverage_plugin__"
COVERAGE_PLUGIN_INPUT = InputFilesContent(
    FilesContent(
        (
            FileContent(
                path=f"{COVERAGE_PLUGIN_MODULE_NAME}.py",
                content=pkg_resources.resource_string(__name__, "coverage_plugin/plugin.py"),
            ),
        )
    )
)


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    address: Address
    digest: Digest


class PytestCoverageDataCollection(CoverageDataCollection):
    element_type = PytestCoverageData


@dataclass(frozen=True)
class CoverageConfigRequest:
    targets: Targets
    is_test_time: bool


@dataclass(frozen=True)
class CoverageConfig:
    digest: Digest


@rule
async def create_coverage_config(
    coverage_config_request: CoverageConfigRequest, source_root_config: SourceRootConfig
) -> CoverageConfig:
    sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in coverage_config_request.targets), strip_source_roots=False,
        )
    )
    init_injected = await Get[InitInjectedSnapshot](InjectInitRequest(sources.snapshot))
    source_roots = source_root_config.get_source_roots()

    # Generate a map from source root stripped source to its source root. eg:
    #  {'pants/testutil/subsystem/util.py': 'src/python'}. This is so that coverage reports
    #  referencing /chroot/path/pants/testutil/subsystem/util.py can be mapped back to the actual
    #  sources they reference when generating coverage reports.
    def stripped_file_with_source_root(file_name: str) -> Tuple[str, str]:
        source_root_object = source_roots.find_by_path(file_name)
        source_root = source_root_object.path if source_root_object is not None else ""
        stripped_path = file_name[len(source_root) + 1 :]
        return stripped_path, source_root

    stripped_files_to_source_roots = dict(
        stripped_file_with_source_root(filename)
        for filename in sorted(init_injected.snapshot.files)
    )

    default_config = dedent(
        """
        [run]
        branch = True
        timid = False
        relative_files = True
        """
    )

    config_parser = configparser.ConfigParser()
    config_parser.read_file(StringIO(default_config))
    config_parser.set("run", "plugins", COVERAGE_PLUGIN_MODULE_NAME)
    config_parser.add_section(COVERAGE_PLUGIN_MODULE_NAME)
    config_parser.set(
        COVERAGE_PLUGIN_MODULE_NAME,
        "source_to_target_base",
        json.dumps(stripped_files_to_source_roots),
    )
    config_parser.set(
        COVERAGE_PLUGIN_MODULE_NAME, "test_time", json.dumps(coverage_config_request.is_test_time)
    )

    config_io_stream = StringIO()
    config_parser.write(config_io_stream)
    digest = await Get[Digest](
        InputFilesContent(
            [FileContent(".coveragerc", content=config_io_stream.getvalue().encode())]
        )
    )
    return CoverageConfig(digest)


class ReportType(Enum):
    CONSOLE = ("console", "report")
    XML = ("xml", None)
    HTML = ("html", None)

    _report_name: str

    def __new__(cls, value: str, report_name: Optional[str] = None) -> "ReportType":
        member: "ReportType" = object.__new__(cls)
        member._value_ = value
        member._report_name = report_name if report_name is not None else value
        return member

    @property
    def report_name(self) -> str:
        return self._report_name


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
            type=ReportType,
            default=ReportType.CONSOLE,
            help="Which coverage report type to emit.",
        )


@dataclass(frozen=True)
class CoverageSetup:
    requirements_pex: Pex


@rule
async def setup_coverage(coverage: PytestCoverage) -> CoverageSetup:
    plugin_file_digest = await Get[Digest](InputFilesContent, COVERAGE_PLUGIN_INPUT)
    output_pex_filename = "coverage.pex"
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename=output_pex_filename,
            requirements=PexRequirements(coverage.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                coverage.default_interpreter_constraints
            ),
            entry_point=coverage.get_entry_point(),
            sources=plugin_file_digest,
        )
    )
    return CoverageSetup(requirements_pex)


@dataclass(frozen=True)
class MergedCoverageData:
    coverage_data: Digest


@named_rule(desc="Merge Pytest coverage reports")
async def merge_coverage_data(
    data_collection: PytestCoverageDataCollection,
    coverage_setup: CoverageSetup,
    transitive_targets: TransitiveTargets,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> MergedCoverageData:
    """Takes all Python test results and merges their coverage data into a single SQL file."""
    # We start with a bunch of test results, each of which has a coverage data file called
    # `.coverage`. We prefix each of these with their address so that we can write them all into a
    # single PEX.
    coverage_directory_digests = await MultiGet(
        Get[Digest](DirectoryWithPrefixToAdd(data.digest, prefix=data.address.path_safe_spec))
        for data in data_collection
    )
    sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in transitive_targets.closure), strip_source_roots=False
        )
    )
    sources_with_inits = await Get[InitInjectedSnapshot](InjectInitRequest(sources.snapshot))
    coverage_config = await Get[CoverageConfig](
        CoverageConfigRequest(Targets(transitive_targets.closure), is_test_time=True)
    )
    merged_input_files: Digest = await Get(
        Digest,
        DirectoriesToMerge(
            directories=(
                *coverage_directory_digests,
                sources_with_inits.snapshot.directory_digest,
                coverage_config.digest,
                coverage_setup.requirements_pex.directory_digest,
            )
        ),
    )

    prefixes = [f"{data.address.path_safe_spec}/.coverage" for data in data_collection]
    coverage_args = ("combine", *prefixes)
    process = coverage_setup.requirements_pex.create_execute_request(
        pex_path=f"./{coverage_setup.requirements_pex.output_filename}",
        pex_args=coverage_args,
        input_files=merged_input_files,
        output_files=(".coverage",),
        description=f"Merge Pytest coverage reports.",
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
    )

    result = await Get[ProcessResult](Process, process)
    return MergedCoverageData(coverage_data=result.output_directory_digest)


@named_rule(desc="Generate Pytest coverage report")
async def generate_coverage_report(
    merged_coverage_data: MergedCoverageData,
    coverage_setup: CoverageSetup,
    coverage_subsystem: PytestCoverage,
    transitive_targets: TransitiveTargets,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CoverageReport:
    """Takes all Python test results and generates a single coverage report."""
    requirements_pex = coverage_setup.requirements_pex

    python_targets = [tgt for tgt in transitive_targets.closure if tgt.has_field(PythonSources)]
    coverage_config = await Get[CoverageConfig](
        CoverageConfigRequest(Targets(python_targets), is_test_time=False)
    )

    sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in transitive_targets.closure), strip_source_roots=False
        )
    )
    sources_with_inits_snapshot = await Get[InitInjectedSnapshot](
        InjectInitRequest(sources.snapshot)
    )
    merged_input_files: Digest = await Get(
        Digest,
        DirectoriesToMerge(
            directories=(
                merged_coverage_data.coverage_data,
                coverage_config.digest,
                requirements_pex.directory_digest,
                sources_with_inits_snapshot.snapshot.directory_digest,
            )
        ),
    )

    report_type = coverage_subsystem.options.report
    coverage_args = [report_type.report_name]

    process = requirements_pex.create_execute_request(
        pex_path=f"./{coverage_setup.requirements_pex.output_filename}",
        pex_args=coverage_args,
        input_files=merged_input_files,
        output_directories=("htmlcov",),
        output_files=("coverage.xml",),
        description=f"Generate coverage report.",
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
    )
    result = await Get[ProcessResult](Process, process)

    if report_type == ReportType.CONSOLE:
        return ConsoleCoverageReport(result.stdout.decode())

    report_dir = PurePath(coverage_subsystem.options.report_output_path)

    report_file: Optional[PurePath] = None
    if coverage_subsystem.options.report == ReportType.HTML:
        report_file = report_dir / "htmlcov" / "index.html"
    elif coverage_subsystem.options.report == ReportType.XML:
        report_file = report_dir / "coverage.xml"

    return FilesystemCoverageReport(
        result_digest=result.output_directory_digest,
        directory_to_materialize_to=report_dir,
        report_file=report_file,
    )


def rules():
    return [
        create_coverage_config,
        generate_coverage_report,
        merge_coverage_data,
        setup_coverage,
        subsystem_rule(PytestCoverage),
        UnionRule(CoverageDataCollection, PytestCoverageDataCollection),
        RootRule(CoverageConfigRequest),
    ]
