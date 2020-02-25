# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import itertools
import json
import os
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional, Tuple, Type

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
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    DirectoryToMaterialize,
    DirectoryWithPrefixToAdd,
    FileContent,
    FilesContent,
    InputFilesContent,
    Snapshot,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, goal_rule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.python.pex_build_util import identify_missing_init_files
from pants.rules.core.distdir import DistDir
from pants.rules.core.test import (
    AddressAndTestResult,
    CoverageData,
    CoverageDataBatch,
    CoverageReport,
)
from pants.source.source_root import SourceRootConfig, SourceRoots

COVERAGE_PLUGIN_MODULE_NAME = "__coverage_coverage_plugin__"

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


def get_coverage_plugin_input():
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


def ensure_section(config_parser: configparser.ConfigParser, section: str) -> None:
    """Ensure a section exists in a ConfigParser."""
    if not config_parser.has_section(section):
        config_parser.add_section(section)


def construct_coverage_config(
    source_roots: SourceRoots, python_files: List[str], test_time: Optional[bool] = False,
) -> str:
    # A map from source root stripped source to its source root. eg:
    #  {'pants/testutil/subsystem/util.py': 'src/python'}
    # This is so coverage reports referencing /chroot/path/pants/testutil/subsystem/util.py can be mapped
    # back to the actual sources they reference when merging coverage reports.
    init_files = list(identify_missing_init_files(list(python_files)))

    def source_root_stripped_source_and_source_root(file_name):
        source_root = source_roots.find_by_path(file_name)
        source_root_stripped_path = file_name[len(source_root.path) + 1 :]
        return (source_root_stripped_path, source_root.path)

    source_to_target_base = dict(
        source_root_stripped_source_and_source_root(filename)
        for filename in sorted(python_files) + init_files
    )
    config_parser = configparser.ConfigParser()
    config_parser.read_file(StringIO(DEFAULT_COVERAGE_CONFIG))
    ensure_section(config_parser, "run")
    config_parser.set("run", "plugins", COVERAGE_PLUGIN_MODULE_NAME)
    config_parser.add_section(COVERAGE_PLUGIN_MODULE_NAME)
    config_parser.set(
        COVERAGE_PLUGIN_MODULE_NAME, "source_to_target_base", json.dumps(source_to_target_base)
    )
    config_parser.set(COVERAGE_PLUGIN_MODULE_NAME, "test_time", json.dumps(test_time))
    config = StringIO()
    config_parser.write(config)
    return config.getvalue()


class ReportType(Enum):
    XML = "xml"
    HTML = "html"


class PytestCoverage(PythonToolBase):
    options_scope = "pytest-coverage"
    default_version = "coverage==5.0.3"
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
async def setup_coverage(coverage: PytestCoverage,) -> CoverageSetup:
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
class MergedCoverageData:
    coverage_data: Digest


@rule(name="Merge coverage reports")
async def merge_coverage_reports(
    transitive_targets: TransitiveHydratedTargets,
    python_setup: PythonSetup,
    coverage_setup: CoverageSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    addresses: BuildFileAddresses,
) -> MergedCoverageData:
    """Takes all python test results and merges their coverage data into a single sql file."""
    test_results = await MultiGet(
        Get[AddressAndTestResult](Address, addr.to_address()) for addr in addresses
    )

    coveragerc_digest = await Get[Digest](
        InputFilesContent, get_coveragerc_input(DEFAULT_COVERAGE_CONFIG)
    )

    coverage_directory_digests = await MultiGet(
        Get[Digest](
            DirectoryWithPrefixToAdd(
                directory_digest=result.test_result._python_sqlite_coverage_file,
                prefix=result.address.to_address().path_safe_spec,
            )
        )
        for result in test_results
        if result.test_result is not None
        and result.test_result._python_sqlite_coverage_file is not None
    )
    sources_snapshot = await Get[Snapshot](
        DirectoriesToMerge(
            tuple(
                hydrated_target.adaptor.sources.snapshot.directory_digest
                for hydrated_target in transitive_targets.closure
                if hasattr(hydrated_target.adaptor, "sources")
            )
        )
    )
    sources_with_inits_snapshot = await Get[InitInjectedSnapshot](
        InjectInitRequest(sources_snapshot)
    )
    merged_input_files: Digest = await Get(
        Digest,
        DirectoriesToMerge(
            directories=(
                *coverage_directory_digests,
                sources_with_inits_snapshot.snapshot.directory_digest,
                coveragerc_digest,
                coverage_setup.requirements_pex.directory_digest,
            )
        ),
    )

    prefixes = [
        f"{result.address.to_address().path_safe_spec}/.coverage" for result in test_results
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


@dataclass(frozen=True)
class PytestCoverageDataBatch(CoverageDataBatch):
    addresses_and_test_results: Tuple[AddressAndTestResult, ...]


@dataclass(frozen=True)
class PytestCoverageReport:
    report_directory_digest: Digest
    directory_to_materialize_to: PurePath


@rule(name="Generate coverage report")
async def generate_coverage_report(
    transitive_targets: TransitiveHydratedTargets,
    python_setup: PythonSetup,
    coverage_setup: CoverageSetup,
    merged_coverage_data: MergedCoverageData,
    coverage_toolbase: PytestCoverage,
    source_root_config: SourceRootConfig,
    data_batch: PytestCoverageDataBatch,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> PytestCoverageReport:
    """Takes all python test results and generates a single coverage report."""
    requirements_pex = coverage_setup.requirements_pex
    # TODO(#4535) We need a better way to do this kind of check that covers synthetic targets and rules extensibility.
    python_targets = [
        target
        for target in transitive_targets.closure
        if target.adaptor.type_alias == "python_library"
        or target.adaptor.type_alias == "python_tests"
    ]

    source_roots = source_root_config.get_source_roots()
    python_files = set(
        itertools.chain.from_iterable(
            target.adaptor.sources.snapshot.files for target in python_targets
        )
    )
    coverage_config_content = construct_coverage_config(source_roots, sorted(python_files))

    coveragerc_digest = await Get[Digest](
        InputFilesContent, get_coveragerc_input(coverage_config_content)
    )
    sources_digests = [
        hydrated_target.adaptor.sources.snapshot.directory_digest
        for hydrated_target in transitive_targets.closure
        if hasattr(hydrated_target.adaptor, "sources")
    ]
    sources_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(sources_digests)))
    inits_digest = await Get[InitInjectedSnapshot](Digest, sources_digest)

    merged_input_files: Digest = await Get(
        Digest,
        DirectoriesToMerge(
            directories=(
                merged_coverage_data.coverage_data,
                coveragerc_digest,
                requirements_pex.directory_digest,
                *sources_digests,
                inits_digest.directory_digest,
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
    return PytestCoverageReport(
        result.output_directory_digest, coverage_toolbase.options.report_output_path
    )



def rules():
    return [generate_coverage_report, UnionRule(CoverageDataBatch, PytestCoverageDataBatch)]
