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
from pants.backend.python.rules.pex_from_targets import LegacyPexFromTargetsRequest
from pants.backend.python.rules.pytest_coverage import (
    Coveragerc,
    CoveragercRequest,
    PytestCoverageData,
    get_coverage_plugin_input,
)
from pants.backend.python.rules.targets import PythonCoverage, PythonTestsTimeout
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.addressable import Addresses
from pants.engine.fs import Digest, DirectoriesToMerge, InputFilesContent
from pants.engine.interactive_runner import InteractiveProcessRequest
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import (
    FilesAdaptor,
    PythonTargetAdaptor,
    PythonTestsAdaptorWithOrigin,
    ResourcesAdaptor,
    TargetAdaptorWithOrigin,
)
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.option.global_options import GlobalOptions
from pants.python.python_setup import PythonSetup
from pants.rules.core.determine_source_files import LegacySpecifiedSourceFilesRequest, SourceFiles
from pants.rules.core.test import TestDebugRequest, TestOptions, TestResult, TestRunner


@dataclass(frozen=True)
class PytestRunner(TestRunner):
    @staticmethod
    def is_valid_target(adaptor_with_origin: TargetAdaptorWithOrigin) -> bool:
        return isinstance(adaptor_with_origin, PythonTestsAdaptorWithOrigin)


@dataclass(frozen=True)
class TestTargetSetup:
    test_runner_pex: Pex
    args: Tuple[str, ...]
    input_files_digest: Digest
    timeout_seconds: Optional[int]

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


@rule
async def setup_pytest_for_target(
    pytest_runner: PytestRunner,
    pytest: PyTest,
    test_options: TestOptions,
    python_setup: PythonSetup,
) -> TestTargetSetup:
    # TODO: Rather than consuming the TestOptions subsystem, the TestRunner should pass on coverage
    # configuration via #7490.

    adaptor_with_origin = pytest_runner.adaptor_with_origin
    adaptor = adaptor_with_origin.adaptor
    test_addresses = Addresses((adaptor.address,))

    # TODO(John Sirois): PexInterpreterConstraints are gathered in the same way by the
    #  `create_pex_from_target_closure` rule, factor up.
    transitive_hydrated_targets = await Get[TransitiveHydratedTargets](Addresses, test_addresses)
    all_targets = transitive_hydrated_targets.closure
    all_target_adaptors = [t.adaptor for t in all_targets]
    interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
        adaptors=all_target_adaptors, python_setup=python_setup
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
        await Get[Digest](InputFilesContent, get_coverage_plugin_input()) if run_coverage else None
    )

    pytest_pex_request = pex_request(
        output_filename="pytest.pex",
        requirements=PexRequirements(pytest.get_requirement_strings()),
        additional_args=additional_args_for_pytest,
        input_files_digest=plugin_file_digest,
    )

    requirements_pex_request = LegacyPexFromTargetsRequest(
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
    specified_source_files_request = LegacySpecifiedSourceFilesRequest(
        [adaptor_with_origin], strip_source_roots=True
    )

    # TODO: Replace this with appropriate target API logic.
    python_targets = [t for t in all_targets if isinstance(t.adaptor, PythonTargetAdaptor)]
    resource_targets = [
        t for t in all_targets if isinstance(t.adaptor, (FilesAdaptor, ResourcesAdaptor))
    ]

    # TODO(John Sirois): Support exploiting concurrency better:
    #   https://github.com/pantsbuild/pants/issues/9294
    # Some awkward code follows in order to execute 5-6 items concurrently given the current state
    # of MultiGet typing / API. Improve this since we should encourage full concurrency in general.
    requests: List[Get[Any]] = [
        Get[Pex](PexRequest, pytest_pex_request),
        Get[Pex](LegacyPexFromTargetsRequest, requirements_pex_request),
        Get[Pex](PexRequest, test_runner_pex_request),
        Get[ImportablePythonSources](HydratedTargets(python_targets + resource_targets)),
        Get[SourceFiles](LegacySpecifiedSourceFilesRequest, specified_source_files_request),
    ]
    if run_coverage:
        requests.append(
            Get[Coveragerc](CoveragercRequest(HydratedTargets(python_targets), test_time=True)),
        )

    (
        pytest_pex,
        requirements_pex,
        test_runner_pex,
        chrooted_sources,
        specified_source_files,
        *rest,
    ) = cast(
        Union[
            Tuple[Pex, Pex, Pex, ImportablePythonSources, SourceFiles],
            Tuple[Pex, Pex, Pex, ImportablePythonSources, SourceFiles, Coveragerc],
        ],
        await MultiGet(requests),
    )

    directories_to_merge = [
        chrooted_sources.snapshot.directory_digest,
        requirements_pex.directory_digest,
        pytest_pex.directory_digest,
        test_runner_pex.directory_digest,
    ]
    if run_coverage:
        coveragerc = rest[0]
        directories_to_merge.append(coveragerc.digest)

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(directories=tuple(directories_to_merge))
    )

    coverage_args = []
    if run_coverage:
        coverage_args = [
            "--cov-report=",  # To not generate any output. https://pytest-cov.readthedocs.io/en/latest/config.html
        ]
        # TODO: replace this with proper usage of the Target API.
        coverage_field = PythonCoverage(getattr(adaptor, "coverage", None), address=adaptor.address)
        for package in coverage_field.determine_packages_to_cover(
            specified_source_files=specified_source_files
        ):
            coverage_args.extend(["--cov", package])

    # TODO: replace this with proper usage of the Target API.
    timeout_field = PythonTestsTimeout(getattr(adaptor, "timeout", None), address=adaptor.address)

    specified_source_file_names = sorted(specified_source_files.snapshot.files)
    return TestTargetSetup(
        test_runner_pex=test_runner_pex,
        args=(*pytest.options.args, *coverage_args, *specified_source_file_names),
        input_files_digest=merged_input_files,
        timeout_seconds=timeout_field.calculate_from_global_options(pytest),
    )


@rule(name="Run pytest")
async def run_python_test(
    pytest_runner: PytestRunner,
    test_setup: TestTargetSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    global_options: GlobalOptions,
    test_options: TestOptions,
) -> TestResult:
    """Runs pytest for one target."""
    env = {"PYTEST_ADDOPTS": f"--color={'yes' if global_options.options.colors else 'no'}"}
    run_coverage = test_options.values.run_coverage
    request = test_setup.test_runner_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./{test_setup.test_runner_pex.output_filename}",
        pex_args=test_setup.args,
        input_files=test_setup.input_files_digest,
        output_directories=(".coverage",) if run_coverage else None,
        description=f"Run Pytest for {pytest_runner.adaptor_with_origin.adaptor.address.reference()}",
        timeout_seconds=(
            test_setup.timeout_seconds if test_setup.timeout_seconds is not None else 9999
        ),
        env=env,
    )
    result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, request)
    coverage_data = PytestCoverageData(result.output_directory_digest) if run_coverage else None
    return TestResult.from_fallible_execute_process_result(result, coverage_data=coverage_data)


@rule(name="Run pytest in an interactive process")
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
        UnionRule(TestRunner, PytestRunner),
        subsystem_rule(PyTest),
        subsystem_rule(PythonSetup),
    ]
