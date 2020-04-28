# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union, cast

from pants.backend.python.rules.importable_python_sources import ImportablePythonSources
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.pytest_coverage import (
    COVERAGE_PLUGIN_INPUT,
    CoverageConfig,
    CoverageConfigRequest,
    PytestCoverageData,
)
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import (
    PythonCoverage,
    PythonInterpreterCompatibility,
    PythonSources,
    PythonTestsSources,
    PythonTestsTimeout,
)
from pants.core.goals.test import TestConfiguration, TestDebugRequest, TestOptions, TestResult
from pants.core.util_rules.determine_source_files import SourceFiles, SpecifiedSourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    InputFilesContent,
    PathGlobs,
    Snapshot,
    SnapshotSubset,
)
from pants.engine.interactive_runner import InteractiveProcessRequest
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import named_rule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Targets, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.python.python_setup import PythonSetup


@dataclass(frozen=True)
class PythonTestConfiguration(TestConfiguration):
    required_fields = (PythonTestsSources,)

    sources: PythonTestsSources
    timeout: PythonTestsTimeout
    coverage: PythonCoverage


@dataclass(frozen=True)
class TestTargetSetup:
    test_runner_pex: Pex
    args: Tuple[str, ...]
    input_files_digest: Digest
    timeout_seconds: Optional[int]
    xml_dir: Optional[str]
    junit_family: str

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


@rule
async def setup_pytest_for_target(
    config: PythonTestConfiguration,
    pytest: PyTest,
    test_options: TestOptions,
    python_setup: PythonSetup,
) -> TestTargetSetup:
    # TODO: Rather than consuming the TestOptions subsystem, the TestRunner should pass on coverage
    # configuration via #7490.

    test_addresses = Addresses((config.address,))

    transitive_targets = await Get[TransitiveTargets](Addresses, test_addresses)
    all_targets = transitive_targets.closure

    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (
            tgt[PythonInterpreterCompatibility]
            for tgt in all_targets
            if tgt.has_field(PythonInterpreterCompatibility)
        ),
        python_setup,
    )

    # Ensure all pexes we merge via PEX_PATH to form the test runner use the interpreter constraints
    # of the tests. This is handled by CreatePexFromTargetClosure, but we must pass this through for
    # CreatePex requests.
    pex_request = functools.partial(PexRequest, interpreter_constraints=interpreter_constraints)

    # NB: We set `--not-zip-safe` because Pytest plugin discovery, which uses
    # `importlib_metadata` and thus `zipp`, does not play nicely when doing import magic directly
    # from zip files. `zipp` has pathologically bad behavior with large zipfiles.
    # TODO: this does have a performance cost as the pex must now be expanded to disk. Long term,
    # it would be better to fix Zipp (whose fix would then need to be used by importlib_metadata
    # and then by Pytest). See https://github.com/jaraco/zipp/pull/26.
    additional_args_for_pytest = ("--not-zip-safe",)

    run_coverage = test_options.values.run_coverage
    plugin_file_digest: Optional[Digest] = (
        await Get[Digest](InputFilesContent, COVERAGE_PLUGIN_INPUT) if run_coverage else None
    )

    pytest_pex_request = pex_request(
        output_filename="pytest.pex",
        requirements=PexRequirements(pytest.get_requirement_strings()),
        additional_args=additional_args_for_pytest,
        sources=plugin_file_digest,
    )

    requirements_pex_request = PexFromTargetsRequest(
        addresses=test_addresses,
        output_filename="requirements.pex",
        include_source_files=False,
        additional_args=additional_args_for_pytest,
    )

    test_runner_pex_request = pex_request(
        output_filename="test_runner.pex",
        entry_point="pytest:main",
        interpreter_constraints=interpreter_constraints,
        additional_args=(
            "--pex-path",
            # TODO(John Sirois): Support shading python binaries:
            #   https://github.com/pantsbuild/pants/issues/9206
            # Right now any pytest transitive requirements will shadow corresponding user
            # requirements which will lead to problems when APIs that are used by either
            # `pytest:main` or the tests themselves break between the two versions.
            ":".join(
                (pytest_pex_request.output_filename, requirements_pex_request.output_filename)
            ),
        ),
    )

    # Get the file names for the test_target so that we can specify to Pytest precisely which files
    # to test, rather than using auto-discovery.
    specified_source_files_request = SpecifiedSourceFilesRequest(
        [(config.sources, config.origin)], strip_source_roots=True
    )

    # TODO(John Sirois): Support exploiting concurrency better:
    #   https://github.com/pantsbuild/pants/issues/9294
    # Some awkward code follows in order to execute 5-6 items concurrently given the current state
    # of MultiGet typing / API. Improve this since we should encourage full concurrency in general.
    requests: List[Get[Any]] = [
        Get[Pex](PexRequest, pytest_pex_request),
        Get[Pex](PexFromTargetsRequest, requirements_pex_request),
        Get[Pex](PexRequest, test_runner_pex_request),
        Get[ImportablePythonSources](Targets(all_targets)),
        Get[SourceFiles](SpecifiedSourceFilesRequest, specified_source_files_request),
    ]
    if run_coverage:
        requests.append(
            Get[CoverageConfig](
                CoverageConfigRequest(
                    Targets((tgt for tgt in all_targets if tgt.has_field(PythonSources))),
                    is_test_time=True,
                )
            ),
        )

    (
        pytest_pex,
        requirements_pex,
        test_runner_pex,
        prepared_sources,
        specified_source_files,
        *rest,
    ) = cast(
        Union[
            Tuple[Pex, Pex, Pex, ImportablePythonSources, SourceFiles],
            Tuple[Pex, Pex, Pex, ImportablePythonSources, SourceFiles, CoverageConfig],
        ],
        await MultiGet(requests),
    )

    directories_to_merge = [
        prepared_sources.snapshot.directory_digest,
        requirements_pex.directory_digest,
        pytest_pex.directory_digest,
        test_runner_pex.directory_digest,
    ]
    if run_coverage:
        coverage_config = rest[0]
        directories_to_merge.append(coverage_config.digest)

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(directories=tuple(directories_to_merge))
    )

    coverage_args = []
    if run_coverage:
        coverage_args = [
            "--cov-report=",  # To not generate any output. https://pytest-cov.readthedocs.io/en/latest/config.html
        ]
        for package in config.coverage.determine_packages_to_cover(
            specified_source_files=specified_source_files
        ):
            coverage_args.extend(["--cov", package])

    specified_source_file_names = sorted(specified_source_files.snapshot.files)
    return TestTargetSetup(
        test_runner_pex=test_runner_pex,
        args=(*pytest.options.args, *coverage_args, *specified_source_file_names),
        input_files_digest=merged_input_files,
        timeout_seconds=config.timeout.calculate_from_global_options(pytest),
        xml_dir=pytest.options.junit_xml_dir,
        junit_family=pytest.options.junit_family,
    )


@named_rule(desc="Run pytest")
async def run_python_test(
    config: PythonTestConfiguration,
    test_setup: TestTargetSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    global_options: GlobalOptions,
    test_options: TestOptions,
) -> TestResult:
    """Runs pytest for one target."""
    add_opts = [f"--color={'yes' if global_options.options.colors else 'no'}"]
    if test_setup.xml_dir:
        test_results_file = f"{config.address.path_safe_spec}.xml"
        add_opts.extend(
            (f"--junitxml={test_results_file}", f"-o junit_family={test_setup.junit_family}",)
        )
    env = {"PYTEST_ADDOPTS": " ".join(add_opts)}

    run_coverage = test_options.values.run_coverage
    output_dirs = [".coverage"] if run_coverage else []
    if test_setup.xml_dir:
        output_dirs.append(test_results_file)
    process = test_setup.test_runner_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./{test_setup.test_runner_pex.output_filename}",
        pex_args=test_setup.args,
        input_files=test_setup.input_files_digest,
        output_directories=tuple(output_dirs) if output_dirs else None,
        description=f"Run Pytest for {config.address.reference()}",
        timeout_seconds=(
            test_setup.timeout_seconds if test_setup.timeout_seconds is not None else 9999
        ),
        env=env,
    )
    result = await Get[FallibleProcessResult](Process, process)
    output_digest = result.output_directory_digest
    coverage_data = None
    if run_coverage:
        coverage_snapshot_subset = await Get[Snapshot](
            SnapshotSubset(output_digest, PathGlobs([".coverage"]))
        )
        coverage_data = PytestCoverageData(
            config.address, coverage_snapshot_subset.directory_digest
        )

    xml_results_digest: Optional[Digest] = None
    if test_setup.xml_dir:
        xml_results_snapshot = await Get[Snapshot](
            SnapshotSubset(output_digest, PathGlobs([test_results_file]))
        )
        xml_results_digest = await Get[Digest](
            DirectoryWithPrefixToAdd(xml_results_snapshot.directory_digest, test_setup.xml_dir)
        )

    return TestResult.from_fallible_process_result(
        result, coverage_data=coverage_data, xml_results=xml_results_digest
    )


@named_rule(desc="Run pytest in an interactive process")
async def debug_python_test(test_setup: TestTargetSetup) -> TestDebugRequest:
    run_request = InteractiveProcessRequest(
        argv=(test_setup.test_runner_pex.output_filename, *test_setup.args),
        run_in_workspace=False,
        input_files=test_setup.input_files_digest,
    )
    return TestDebugRequest(run_request)


def rules():
    return [
        run_python_test,
        debug_python_test,
        setup_pytest_for_target,
        UnionRule(TestConfiguration, PythonTestConfiguration),
        subsystem_rule(PyTest),
        subsystem_rule(PythonSetup),
    ]
