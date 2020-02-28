# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import json
import os
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from textwrap import dedent
from typing import Tuple, Type

import pkg_resources

from pants.backend.python.rules.inject_init import InitInjectedSnapshot, InjectInitRequest
from pants.backend.python.rules.pex import (
    CreatePex,
    Pex,
    PexInterpreterConstraints,
    PexRequirements,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import (
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    FileContent,
    FilesContent,
    InputFilesContent,
)
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import RootRule, UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.rules.core.distdir import DistDir
from pants.rules.core.test import (
    AddressAndTestResult,
    CoverageData,
    CoverageDataBatch,
    CoverageReport,
)
from pants.source.source_root import SourceRootConfig

# There are many moving parts in coverage, so here is a high level view of what's going on.

# Step 1.
# Test Time: the `run_python_test` rule executes pytest with `--cov` arguments.
#
# When we run tests on individual targets (in `python_test_runner.py`) we include a couple of arguments to
# pytest telling it to use coverage. We also add a coverage configuration file and a custom plugin to the
# environment in which the test is run (`.coveragerc` is generated, but the plugin code lives in
# `src/python/pants/backend/python/rules/coverage_plugin/plugin.py` and is copied in as is.).
# The test runs and coverage collects data and stores it in a sqlite db, which you can see in the working
# directory as `.coverage`. Along with the coverage data, it also stores some metadata about any plugins
# it was run with. Note: The pants coverage plugin does nothing at all during test time other than have itself
# mentioned in that DB. If the plugin is not mentioned in that DB then when we merge the data or generate the report
# coverage will not use the plugin, regardless of what is in it's configuration file. Because we run tests
# in an environment without source roots (meaning `src/python/foo/bar.py` is in the environment as `foo/bar.py`)
# all of the data in the resulting .coverage file references the files the source root stripped name - `foo/bar.py`
#
# Step 2.
# Merging the Results: The `merge_coverage_data` rule executes `coverage combine`.
#
# Once we've run the tests, we have a bunch `TestResult`s, each with its own coverage data file, named `.coverage`.
# In `merge_coverage_data` We stuff all these `.coverage` files into the same pex, which requires prefixing the
# filenames with a unique identifier so they don't clobber each other. We then run
# `coverage combine foo/.coverage bar/.coverage baz/.coverage` to combine all that data into a single .coverage file.
#
# Step 3.
# Generating the Report: The `generate_coverage_report` rule executes `coverage html` or `coverage xml`
#
# Now we have one single `.coverage` file containing all our merged coverage data, with all the files referenced
# as `foo/bar.py` and we want to generate a single report where all those files will be referenced with their
# buildroot relative paths (`src/python/foo/bar.py`). Coverage requires that the files it's reporting on be
# present in its environment when it generates the report, so we build a pex with all the source files with
# their source roots intact, and *finally* our custom plugin starts doing some work. In our config file we've
# given a map from sourceroot stripped file path to source root - `{'foo/bar.py': 'src/python`}` - As the report
# is generated, every time coverage needs a file, it asks our plugin and the plugin says,
#   "Oh, you want `foo/bar.py`? Sure! Here's `src/python/foo/bar.py`"
# And then we get a nice report that references all the files with their buildroot relative names.
#
# Step 4.
# Materializing the Report on Disk: The `run_tests` rule exposes the report to the user.
#
# Now we have a directory full of html or an xml file full of coverage data and we want to expose it to the user.
# This step happens in `test.py` and should handle all kinds of coverage reports, not just pytest coverage.
# The test runner grabs all our individual test results and requests a CoverageReport, and once it has one, it
# writes it down in `dist/coverage` (or wherever the user has configured it.)


COVERAGE_PLUGIN_MODULE_NAME = "__coverage_coverage_plugin__"

DEFAULT_COVERAGE_CONFIG = dedent(
    """
    [run]
    branch = True
    timid = False
    relative_files = True
    """
)


def get_coveragerc_input(coveragerc_content: str) -> InputFilesContent:
    return InputFilesContent([FileContent(path=".coveragerc", content=coveragerc_content.encode())])


def get_coverage_plugin_input() -> InputFilesContent:
    return InputFilesContent(
        FilesContent(
            (
                FileContent(
                    path=f"{COVERAGE_PLUGIN_MODULE_NAME}.py",
                    content=pkg_resources.resource_string(__name__, "coverage_plugin/plugin.py"),
                ),
            )
        )
    )


def get_packages_to_cover(
    *, target: PythonTestsAdaptor, specified_source_files: SourceFiles,
) -> Tuple[str, ...]:
    # Assume that tests in some package test the sources in that package.
    # This is the case, e.g., if tests live in the same directories as the sources
    # they test, or if they live in a parallel package structure under a separate
    # source root, such as tests/python/path/to/package testing src/python/path/to/package.

    # Note in particular that this doesn't work for most of Pants's own tests, as those are
    # under the top level package 'pants_tests', rather than just 'pants' (although we
    # are moving towards having tests in the same directories as the sources they test).

    # This heuristic is what is used in V1. If we want coverage data on files tested by tests
    # under `pants_test/` we will need to specify explicitly which files they are testing using
    # the `coverage` field in the relevant build file.
    if hasattr(target, "coverage"):
        return tuple(sorted(set(target.coverage)))
    return tuple(
        sorted(
            {
                # Turn file paths into package names.
                os.path.dirname(source_file).replace(os.sep, ".")
                for source_file in specified_source_files.snapshot.files
            }
        )
    )


def ensure_section(config_parser: configparser.ConfigParser, section: str) -> None:
    """Ensure a section exists in a ConfigParser."""
    if not config_parser.has_section(section):
        config_parser.add_section(section)


@dataclass(frozen=True)
class CoveragercRequest:
    hydrated_targets: HydratedTargets
    test_time: bool = False


@dataclass(frozen=True)
class Coveragerc:
    digest: Digest


@rule
async def construct_coverage_config(
    source_root_config: SourceRootConfig, coverage_config_request: CoveragercRequest
) -> Coveragerc:
    sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (ht.adaptor for ht in coverage_config_request.hydrated_targets),
            strip_source_roots=False,
        )
    )
    init_injected = await Get[InitInjectedSnapshot](InjectInitRequest(sources.snapshot))
    source_roots = source_root_config.get_source_roots()
    # Generate a map from source root stripped source to its source root. eg:
    #  {'pants/testutil/subsystem/util.py': 'src/python'}
    # This is so coverage reports referencing /chroot/path/pants/testutil/subsystem/util.py can be mapped
    # back to the actual sources they reference when generating coverage reports.
    def source_root_stripped_source_and_source_root(file_name: str) -> Tuple[str, str]:
        source_root = source_roots.find_by_path(file_name)
        source_root_path = source_root.path if source_root is not None else ""
        source_root_stripped_path = file_name[len(source_root_path) + 1 :]
        return (source_root_stripped_path, source_root_path)

    source_to_target_base = dict(
        source_root_stripped_source_and_source_root(filename)
        for filename in sorted(init_injected.snapshot.files)
    )
    config_parser = configparser.ConfigParser()
    config_parser.read_file(StringIO(DEFAULT_COVERAGE_CONFIG))
    ensure_section(config_parser, "run")
    config_parser.set("run", "plugins", COVERAGE_PLUGIN_MODULE_NAME)
    config_parser.add_section(COVERAGE_PLUGIN_MODULE_NAME)
    config_parser.set(
        COVERAGE_PLUGIN_MODULE_NAME, "source_to_target_base", json.dumps(source_to_target_base)
    )
    config_parser.set(
        COVERAGE_PLUGIN_MODULE_NAME, "test_time", json.dumps(coverage_config_request.test_time)
    )
    config = StringIO()
    config_parser.write(config)
    coveragerc_digest = await Get[Digest](
        InputFilesContent, get_coveragerc_input(config.getvalue())
    )
    return Coveragerc(coveragerc_digest)


class ReportType(Enum):
    XML = "xml"
    HTML = "html"


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
            default=os.path.join(DistDir(relpath="dist").relpath, "coverage", "python"),
            help="Path to write pytest coverage report to. Must be relative to build root.",
        )
        register(
            "--report",
            type=ReportType,
            default=ReportType.HTML,
            help="Which coverage reports to emit.",
        )


@dataclass(frozen=True)
class CoverageSetup:
    requirements_pex: Pex


@rule
async def setup_coverage(coverage: PytestCoverage) -> CoverageSetup:
    plugin_file_digest = await Get[Digest](InputFilesContent, get_coverage_plugin_input())
    output_pex_filename = "coverage.pex"
    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename=output_pex_filename,
            requirements=PexRequirements(requirements=tuple(coverage.get_requirement_specs())),
            interpreter_constraints=PexInterpreterConstraints(
                constraint_set=tuple(coverage.default_interpreter_constraints)
            ),
            entry_point=coverage.get_entry_point(),
            input_files_digest=plugin_file_digest,
        )
    )
    return CoverageSetup(requirements_pex)


@dataclass(frozen=True)
class PytestCoverageDataBatch(CoverageDataBatch):
    addresses_and_test_results: Tuple[AddressAndTestResult, ...]


@dataclass(frozen=True)
class MergedCoverageData:
    coverage_data: Digest


@rule(name="Merge coverage reports")
async def merge_coverage_data(
    data_batch: PytestCoverageDataBatch,
    transitive_targets: TransitiveHydratedTargets,
    python_setup: PythonSetup,
    coverage_setup: CoverageSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> MergedCoverageData:
    """Takes all python test results and merges their coverage data into a single sql file."""
    # We start with a bunch of test results, each of which has a coverage data file called `.coverage`
    # We prefix each of these with their address so that we can write them all into a single pex.
    coverage_directory_digests = await MultiGet(
        Get[Digest](
            DirectoryWithPrefixToAdd(
                directory_digest=result.test_result.coverage_data.digest,  # type: ignore[attr-defined]
                prefix=result.address.path_safe_spec,
            )
        )
        for result in data_batch.addresses_and_test_results
        if result.test_result is not None and result.test_result.coverage_data is not None
    )
    sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (ht.adaptor for ht in transitive_targets.closure), strip_source_roots=False
        )
    )
    sources_with_inits_snapshot = await Get[InitInjectedSnapshot](
        InjectInitRequest(sources.snapshot)
    )
    coveragerc = await Get[Coveragerc](
        CoveragercRequest(HydratedTargets(transitive_targets.closure), test_time=True)
    )
    merged_input_files: Digest = await Get(
        Digest,
        DirectoriesToMerge(
            directories=(
                *coverage_directory_digests,
                sources_with_inits_snapshot.snapshot.directory_digest,
                coveragerc.digest,
                coverage_setup.requirements_pex.directory_digest,
            )
        ),
    )

    prefixes = [
        f"{result.address.path_safe_spec}/.coverage"
        for result in data_batch.addresses_and_test_results
    ]
    coverage_args = ["combine", *prefixes]
    request = coverage_setup.requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./{coverage_setup.requirements_pex.output_filename}",
        pex_args=coverage_args,
        input_files=merged_input_files,
        output_files=(".coverage",),
        description=f"Merge coverage reports.",
    )

    result = await Get[ExecuteProcessResult](ExecuteProcessRequest, request)
    return MergedCoverageData(coverage_data=result.output_directory_digest)


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    digest: Digest

    @property
    def batch_cls(self) -> Type["PytestCoverageDataBatch"]:
        return PytestCoverageDataBatch


@rule(name="Generate coverage report")
async def generate_coverage_report(
    data_batch: PytestCoverageDataBatch,
    transitive_targets: TransitiveHydratedTargets,
    python_setup: PythonSetup,
    coverage_setup: CoverageSetup,
    merged_coverage_data: MergedCoverageData,
    coverage_toolbase: PytestCoverage,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CoverageReport:
    """Takes all python test results and generates a single coverage report."""
    requirements_pex = coverage_setup.requirements_pex
    # TODO(#4535) We need a better way to do this kind of check that covers synthetic targets and rules extensibility.
    python_targets = [
        target
        for target in transitive_targets.closure
        if target.adaptor.type_alias in ("python_library", "python_tests")
    ]

    coveragerc = await Get[Coveragerc](CoveragercRequest(HydratedTargets(python_targets)))
    sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (ht.adaptor for ht in transitive_targets.closure), strip_source_roots=False
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
                coveragerc.digest,
                requirements_pex.directory_digest,
                sources_with_inits_snapshot.snapshot.directory_digest,
            )
        ),
    )
    coverage_args = [coverage_toolbase.options.report.value]
    request = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./{coverage_setup.requirements_pex.output_filename}",
        pex_args=coverage_args,
        input_files=merged_input_files,
        output_directories=("htmlcov",),
        output_files=("coverage.xml",),
        description=f"Generate coverage report.",
    )

    result = await Get[ExecuteProcessResult](ExecuteProcessRequest, request)
    return CoverageReport(
        result.output_directory_digest, coverage_toolbase.options.report_output_path
    )


def rules():
    return [
        RootRule(PytestCoverageDataBatch),
        RootRule(CoveragercRequest),
        construct_coverage_config,
        generate_coverage_report,
        merge_coverage_data,
        subsystem_rule(PytestCoverage),
        setup_coverage,
        UnionRule(CoverageDataBatch, PytestCoverageDataBatch),
    ]
