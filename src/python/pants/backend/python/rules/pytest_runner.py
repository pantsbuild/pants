# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union, cast

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
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestOptions, TestResult
from pants.core.util_rules.determine_source_files import SourceFiles, SpecifiedSourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    AddPrefix,
    Digest,
    InputFilesContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
    SnapshotSubset,
)
from pants.engine.interactive_runner import InteractiveProcessRequest
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, named_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Targets, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.python.python_setup import PythonSetup


@dataclass(frozen=True)
class PythonTestFieldSet(TestFieldSet):
    required_fields = (PythonTestsSources,)

    sources: PythonTestsSources
    timeout: PythonTestsTimeout
    coverage: PythonCoverage


@dataclass(frozen=True)
class TestTargetSetup:
    test_runner_pex: Pex
    args: Tuple[str, ...]
    input_digest: Digest
    timeout_seconds: Optional[int]
    xml_dir: Optional[str]
    junit_family: str

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


@rule
async def setup_pytest_for_target(
    field_set: PythonTestFieldSet,
    pytest: PyTest,
    test_options: TestOptions,
    python_setup: PythonSetup,
) -> TestTargetSetup:
    # TODO: Rather than consuming the TestOptions subsystem, the TestRunner should pass on coverage
    # configuration via #7490.

    test_addresses = Addresses((field_set.address,))

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

    use_coverage = test_options.values.use_coverage
    plugin_file_digest: Optional[Digest] = (
        await Get[Digest](InputFilesContent, COVERAGE_PLUGIN_INPUT) if use_coverage else None
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
        [(field_set.sources, field_set.origin)], strip_source_roots=True
    )

    # TODO(John Sirois): Support exploiting concurrency better:
    #   https://github.com/pantsbuild/pants/issues/9294
    # Some awkward code follows in order to execute 5-6 items concurrently given the current state
    # of MultiGet typing / API. Improve this since we should encourage full concurrency in general.
    requests: List[Get] = [
        Get[Pex](PexRequest, pytest_pex_request),
        Get[Pex](PexFromTargetsRequest, requirements_pex_request),
        Get[Pex](PexRequest, test_runner_pex_request),
        Get[ImportablePythonSources](Targets(all_targets)),
        Get[SourceFiles](SpecifiedSourceFilesRequest, specified_source_files_request),
    ]
    if use_coverage:
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

    digests_to_merge = [
        prepared_sources.snapshot.digest,
        requirements_pex.digest,
        pytest_pex.digest,
        test_runner_pex.digest,
    ]
    if use_coverage:
        coverage_config = rest[0]
        digests_to_merge.append(coverage_config.digest)
    input_digest = await Get[Digest](MergeDigests(digests_to_merge))

    coverage_args = []
    if use_coverage:
        coverage_args = [
            "--cov-report=",  # To not generate any output. https://pytest-cov.readthedocs.io/en/latest/config.html
        ]
        for package in field_set.coverage.determine_packages_to_cover(
            specified_source_files=specified_source_files
        ):
            coverage_args.extend(["--cov", package])

    specified_source_file_names = sorted(specified_source_files.snapshot.files)
    return TestTargetSetup(
        test_runner_pex=test_runner_pex,
        args=(*pytest.options.args, *coverage_args, *specified_source_file_names),
        input_digest=input_digest,
        timeout_seconds=field_set.timeout.calculate_from_global_options(pytest),
        xml_dir=pytest.options.junit_xml_dir,
        junit_family=pytest.options.junit_family,
    )


@named_rule(desc="Run pytest")
async def run_python_test(
    field_set: PythonTestFieldSet,
    test_setup: TestTargetSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    global_options: GlobalOptions,
    test_options: TestOptions,
) -> TestResult:
    """Runs pytest for one target."""
    add_opts = [f"--color={'yes' if global_options.options.colors else 'no'}"]
    if test_setup.xml_dir:
        test_results_file = f"{field_set.address.path_safe_spec}.xml"
        add_opts.extend(
            (f"--junitxml={test_results_file}", f"-o junit_family={test_setup.junit_family}",)
        )
    env = {"PYTEST_ADDOPTS": " ".join(add_opts)}

    use_coverage = test_options.values.use_coverage
    output_dirs = [".coverage"] if use_coverage else []
    if test_setup.xml_dir:
        output_dirs.append(test_results_file)
    process = test_setup.test_runner_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./{test_setup.test_runner_pex.output_filename}",
        pex_args=test_setup.args,
        input_digest=test_setup.input_digest,
        output_directories=tuple(output_dirs) if output_dirs else None,
        description=f"Run Pytest for {field_set.address.reference()}",
        timeout_seconds=test_setup.timeout_seconds,
        env=env,
    )
    result = await Get[FallibleProcessResult](Process, process)

    coverage_data = None
    if use_coverage:
        coverage_snapshot = await Get[Snapshot](
            SnapshotSubset(result.output_digest, PathGlobs([".coverage"]))
        )
        coverage_data = PytestCoverageData(field_set.address, coverage_snapshot.digest)

    xml_results_digest = None
    if test_setup.xml_dir:
        xml_results_snapshot = await Get[Snapshot](
            SnapshotSubset(result.output_digest, PathGlobs([test_results_file]))
        )
        xml_results_digest = await Get[Digest](
            AddPrefix(xml_results_snapshot.digest, test_setup.xml_dir)
        )

    return TestResult.from_fallible_process_result(
        result, coverage_data=coverage_data, xml_results=xml_results_digest
    )


@named_rule(desc="Run pytest in an interactive process")
async def debug_python_test(test_setup: TestTargetSetup) -> TestDebugRequest:
    run_request = InteractiveProcessRequest(
        argv=(test_setup.test_runner_pex.output_filename, *test_setup.args),
        run_in_workspace=False,
        input_digest=test_setup.input_digest,
    )
    return TestDebugRequest(run_request)


def rules():
    return [
        run_python_test,
        debug_python_test,
        setup_pytest_for_target,
        UnionRule(TestFieldSet, PythonTestFieldSet),
        SubsystemRule(PyTest),
        SubsystemRule(PythonSetup),
    ]
