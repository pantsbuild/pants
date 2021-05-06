# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional

from pants.backend.python.goals.coverage_py import (
    CoverageConfig,
    CoverageSubsystem,
    PytestCoverageData,
)
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.target_types import (
    ConsoleScript,
    PythonTestsExtraEnvVars,
    PythonTestsSources,
    PythonTestsTimeout,
)
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
    VenvPex,
    VenvPexProcess,
)
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.test import (
    BuildPackageDependenciesRequest,
    BuiltPackageDependencies,
    RuntimePackageDependenciesField,
    TestDebugRequest,
    TestExtraEnv,
    TestFieldSet,
    TestResult,
    TestSubsystem,
)
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.environment import CompleteEnvironment
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    Process,
    ProcessCacheScope,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel

logger = logging.getLogger()


# If a user wants extra pytest output (e.g., plugin output) to show up in dist/
# they must ensure that output goes under this directory. E.g.,
# ./pants test <target> -- --html=extra-output/report.html
_EXTRA_OUTPUT_DIR = "extra-output"


@dataclass(frozen=True)
class PythonTestFieldSet(TestFieldSet):
    required_fields = (PythonTestsSources,)

    sources: PythonTestsSources
    timeout: PythonTestsTimeout
    runtime_package_dependencies: RuntimePackageDependenciesField
    extra_env_vars: PythonTestsExtraEnvVars

    def is_conftest_or_type_stub(self) -> bool:
        """We skip both `conftest.py` and `.pyi` stubs, even though though they often belong to a
        `python_tests` target, because neither contain any tests to run on."""
        if not self.address.is_file_target:
            return False
        file_name = PurePath(self.address.filename)
        return file_name.name == "conftest.py" or file_name.suffix == ".pyi"


@dataclass(frozen=True)
class TestSetupRequest:
    field_set: PythonTestFieldSet
    is_debug: bool


@dataclass(frozen=True)
class TestSetup:
    process: Process
    results_file_name: Optional[str]

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


@rule(level=LogLevel.DEBUG)
async def setup_pytest_for_target(
    request: TestSetupRequest,
    pytest: PyTest,
    test_subsystem: TestSubsystem,
    python_setup: PythonSetup,
    coverage_config: CoverageConfig,
    coverage_subsystem: CoverageSubsystem,
    test_extra_env: TestExtraEnv,
    global_options: GlobalOptions,
    complete_env: CompleteEnvironment,
) -> TestSetup:
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest([request.field_set.address])
    )
    all_targets = transitive_targets.closure

    interpreter_constraints = PexInterpreterConstraints.create_from_targets(
        all_targets, python_setup
    )

    requirements_pex_get = Get(
        Pex,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements([request.field_set.address], internal_only=True),
    )
    pytest_pex_get = Get(
        Pex,
        PexRequest(
            output_filename="pytest.pex",
            requirements=PexRequirements(pytest.get_requirement_strings()),
            interpreter_constraints=interpreter_constraints,
            internal_only=True,
        ),
    )

    extra_output_directory_digest_get = Get(Digest, CreateDigest([Directory(_EXTRA_OUTPUT_DIR)]))

    prepared_sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(all_targets, include_files=True)
    )

    build_package_dependencies_get = Get(
        BuiltPackageDependencies,
        BuildPackageDependenciesRequest(request.field_set.runtime_package_dependencies),
    )

    # Get the file names for the test_target so that we can specify to Pytest precisely which files
    # to test, rather than using auto-discovery.
    field_set_source_files_get = Get(SourceFiles, SourceFilesRequest([request.field_set.sources]))

    (
        pytest_pex,
        requirements_pex,
        prepared_sources,
        field_set_source_files,
        built_package_dependencies,
        extra_output_directory_digest,
    ) = await MultiGet(
        pytest_pex_get,
        requirements_pex_get,
        prepared_sources_get,
        field_set_source_files_get,
        build_package_dependencies_get,
        extra_output_directory_digest_get,
    )

    pytest_runner_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="pytest_runner.pex",
            interpreter_constraints=interpreter_constraints,
            main=ConsoleScript("pytest"),
            internal_only=True,
            pex_path=[pytest_pex, requirements_pex],
        ),
    )
    config_files_get = Get(
        ConfigFiles,
        ConfigFilesRequest,
        pytest.config_request(field_set_source_files.snapshot.dirs),
    )
    pytest_runner_pex, config_files = await MultiGet(pytest_runner_pex_get, config_files_get)

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                coverage_config.digest,
                prepared_sources.source_files.snapshot.digest,
                config_files.snapshot.digest,
                extra_output_directory_digest,
                *(pkg.digest for pkg in built_package_dependencies),
            )
        ),
    )

    add_opts = [f"--color={'yes' if global_options.options.colors else 'no'}"]
    output_files = []

    results_file_name = None
    if pytest.options.junit_xml_dir and not request.is_debug:
        results_file_name = f"{request.field_set.address.path_safe_spec}.xml"
        add_opts.extend(
            (f"--junitxml={results_file_name}", "-o", f"junit_family={pytest.options.junit_family}")
        )
        output_files.append(results_file_name)

    coverage_args = []
    if test_subsystem.use_coverage and not request.is_debug:
        output_files.append(".coverage")
        cov_paths = coverage_subsystem.filter if coverage_subsystem.filter else (".",)
        coverage_args = [
            "--cov-report=",  # Turn off output.
            f"--cov-config={coverage_config.path}",
            *itertools.chain.from_iterable(["--cov", cov_path] for cov_path in cov_paths),
        ]

    extra_env = {
        "PYTEST_ADDOPTS": " ".join(add_opts),
        "PEX_EXTRA_SYS_PATH": ":".join(prepared_sources.source_roots),
        **test_extra_env.env,
        # NOTE: `complete_env` intentionally after `test_extra_env` to allow overriding within `python_tests`
        **complete_env.get_subset(request.field_set.extra_env_vars.value or ()),
    }

    # Cache test runs only if they are successful, or not at all if `--test-force`.
    cache_scope = ProcessCacheScope.NEVER if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    process = await Get(
        Process,
        VenvPexProcess(
            pytest_runner_pex,
            argv=(*pytest.options.args, *coverage_args, *field_set_source_files.files),
            extra_env=extra_env,
            input_digest=input_digest,
            output_directories=(_EXTRA_OUTPUT_DIR,),
            output_files=output_files,
            timeout_seconds=request.field_set.timeout.calculate_from_global_options(pytest),
            execution_slot_variable=pytest.options.execution_slot_var,
            description=f"Run Pytest for {request.field_set.address}",
            level=LogLevel.DEBUG,
            cache_scope=cache_scope,
        ),
    )
    return TestSetup(process, results_file_name=results_file_name)


@rule(desc="Run Pytest", level=LogLevel.DEBUG)
async def run_python_test(
    field_set: PythonTestFieldSet, test_subsystem: TestSubsystem, pytest: PyTest
) -> TestResult:
    if field_set.is_conftest_or_type_stub():
        return TestResult.skip(field_set.address)

    setup = await Get(TestSetup, TestSetupRequest(field_set, is_debug=False))
    result = await Get(FallibleProcessResult, Process, setup.process)

    coverage_data = None
    if test_subsystem.use_coverage:
        coverage_snapshot = await Get(
            Snapshot, DigestSubset(result.output_digest, PathGlobs([".coverage"]))
        )
        if coverage_snapshot.files == (".coverage",):
            coverage_data = PytestCoverageData(field_set.address, coverage_snapshot.digest)
        else:
            logger.warning(f"Failed to generate coverage data for {field_set.address}.")

    xml_results_snapshot = None
    if setup.results_file_name:
        xml_results_snapshot = await Get(
            Snapshot, DigestSubset(result.output_digest, PathGlobs([setup.results_file_name]))
        )
        if xml_results_snapshot.files == (setup.results_file_name,):
            xml_results_snapshot = await Get(
                Snapshot,
                AddPrefix(xml_results_snapshot.digest, pytest.options.junit_xml_dir),
            )
        else:
            logger.warning(f"Failed to generate JUnit XML data for {field_set.address}.")
    extra_output_snapshot = await Get(
        Snapshot, DigestSubset(result.output_digest, PathGlobs([f"{_EXTRA_OUTPUT_DIR}/**"]))
    )
    extra_output_snapshot = await Get(
        Snapshot, RemovePrefix(extra_output_snapshot.digest, _EXTRA_OUTPUT_DIR)
    )

    return TestResult.from_fallible_process_result(
        result,
        address=field_set.address,
        coverage_data=coverage_data,
        xml_results=xml_results_snapshot,
        extra_output=extra_output_snapshot,
    )


@rule(desc="Set up Pytest to run interactively", level=LogLevel.DEBUG)
async def debug_python_test(field_set: PythonTestFieldSet) -> TestDebugRequest:
    if field_set.is_conftest_or_type_stub():
        return TestDebugRequest(None)
    setup = await Get(TestSetup, TestSetupRequest(field_set, is_debug=True))
    return TestDebugRequest(
        InteractiveProcess.from_process(setup.process, forward_signals_to_process=False)
    )


def rules():
    return [*collect_rules(), UnionRule(TestFieldSet, PythonTestFieldSet)]
