# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from pants.backend.python.goals.coverage_py import (
    CoverageConfig,
    CoverageSubsystem,
    PytestCoverageData,
)
from pants.backend.python.subsystems.pytest import PyTest, PythonTestFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
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
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
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
from pants.engine.target import Target, TransitiveTargets, TransitiveTargetsRequest, WrappedTarget
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel

logger = logging.getLogger()


# -----------------------------------------------------------------------------------------
# Plugin hook
# -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PytestPluginSetup:
    """The result of custom set up logic before Pytest runs.

    Please reach out it if you would like certain functionality, such as allowing your plugin to set
    environment variables.
    """

    digest: Digest = EMPTY_DIGEST


@union
@dataclass(frozen=True)  # type: ignore[misc]
class PytestPluginSetupRequest(ABC):
    """A request to set up the test environment before Pytest runs, e.g. to set up databases.

    To use, subclass PytestPluginSetupRequest, register the rule
    `UnionRule(PytestPluginSetupRequest, MyCustomPytestPluginSetupRequest)`, and add a rule that
    takes your subclass as a parameter and returns `PytestPluginSetup`.
    """

    target: Target

    @classmethod
    @abstractmethod
    def is_applicable(cls, target: Target) -> bool:
        """Whether the setup implementation should be used for this target or not."""


class AllPytestPluginSetups(Collection[PytestPluginSetup]):
    pass


# TODO: Why is this necessary? We should be able to use `PythonTestFieldSet` as the rule param.
@dataclass(frozen=True)
class AllPytestPluginSetupsRequest:
    address: Address


@rule
async def run_all_setup_plugins(
    request: AllPytestPluginSetupsRequest, union_membership: UnionMembership
) -> AllPytestPluginSetups:
    wrapped_tgt = await Get(WrappedTarget, Address, request.address)
    applicable_setup_request_types = tuple(
        request
        for request in union_membership.get(PytestPluginSetupRequest)
        if request.is_applicable(wrapped_tgt.target)
    )
    setups = await MultiGet(
        Get(PytestPluginSetup, PytestPluginSetupRequest, request(wrapped_tgt.target))  # type: ignore[misc, abstract]
        for request in applicable_setup_request_types
    )
    return AllPytestPluginSetups(setups)


# -----------------------------------------------------------------------------------------
# Core logic
# -----------------------------------------------------------------------------------------


# If a user wants extra pytest output (e.g., plugin output) to show up in dist/
# they must ensure that output goes under this directory. E.g.,
# ./pants test <target> -- --html=extra-output/report.html
_EXTRA_OUTPUT_DIR = "extra-output"


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
) -> TestSetup:
    transitive_targets, plugin_setups = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest([request.field_set.address])),
        Get(AllPytestPluginSetups, AllPytestPluginSetupsRequest(request.field_set.address)),
    )
    all_targets = transitive_targets.closure

    interpreter_constraints = InterpreterConstraints.create_from_targets(all_targets, python_setup)

    requirements_pex_get = Get(Pex, RequirementsPexRequest([request.field_set.address]))
    pytest_pex_get = Get(
        Pex,
        PexRequest(
            output_filename="pytest.pex",
            requirements=pytest.pex_requirements(),
            interpreter_constraints=interpreter_constraints,
            internal_only=True,
        ),
    )

    # Ensure that the empty extra output dir exists.
    extra_output_directory_digest_get = Get(Digest, CreateDigest([Directory(_EXTRA_OUTPUT_DIR)]))

    prepared_sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(all_targets, include_files=True)
    )

    # Get the file names for the test_target so that we can specify to Pytest precisely which files
    # to test, rather than using auto-discovery.
    field_set_source_files_get = Get(SourceFiles, SourceFilesRequest([request.field_set.source]))

    field_set_extra_env_get = Get(
        Environment, EnvironmentRequest(request.field_set.extra_env_vars.value or ())
    )

    (
        pytest_pex,
        requirements_pex,
        prepared_sources,
        field_set_source_files,
        field_set_extra_env,
        extra_output_directory_digest,
    ) = await MultiGet(
        pytest_pex_get,
        requirements_pex_get,
        prepared_sources_get,
        field_set_source_files_get,
        field_set_extra_env_get,
        extra_output_directory_digest_get,
    )

    local_dists = await Get(
        LocalDistsPex,
        LocalDistsPexRequest(
            [request.field_set.address],
            internal_only=True,
            interpreter_constraints=interpreter_constraints,
            sources=prepared_sources,
        ),
    )

    pytest_runner_pex_get = Get(
        VenvPex,
        PexRequest(
            output_filename="pytest_runner.pex",
            interpreter_constraints=interpreter_constraints,
            main=pytest.main,
            internal_only=True,
            pex_path=[pytest_pex, requirements_pex, local_dists.pex],
        ),
    )
    config_files_get = Get(
        ConfigFiles,
        ConfigFilesRequest,
        pytest.config_request(field_set_source_files.snapshot.dirs),
    )
    pytest_runner_pex, config_files = await MultiGet(pytest_runner_pex_get, config_files_get)

    # The coverage and pytest config may live in the same config file (e.g., setup.cfg, tox.ini
    # or pyproject.toml), and wee may have rewritten those files to augment the coverage config,
    # in which case we must ensure that the original and rewritten files don't collide.
    pytest_config_digest = config_files.snapshot.digest
    if coverage_config.path in config_files.snapshot.files:
        subset_paths = list(config_files.snapshot.files)
        # Remove the original file, and rely on the rewritten file, which contains all the
        # pytest-related config unchanged.
        subset_paths.remove(coverage_config.path)
        pytest_config_digest = await Get(
            Digest, DigestSubset(pytest_config_digest, PathGlobs(subset_paths))
        )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                coverage_config.digest,
                local_dists.remaining_sources.source_files.snapshot.digest,
                pytest_config_digest,
                extra_output_directory_digest,
                *(plugin_setup.digest for plugin_setup in plugin_setups),
            )
        ),
    )

    add_opts = [f"--color={'yes' if global_options.colors else 'no'}"]
    output_files = []

    results_file_name = None
    if not request.is_debug:
        results_file_name = f"{request.field_set.address.path_safe_spec}.xml"
        add_opts.extend(
            (f"--junitxml={results_file_name}", "-o", f"junit_family={pytest.junit_family}")
        )
        output_files.append(results_file_name)

    coverage_args = []
    if test_subsystem.use_coverage and not request.is_debug:
        pytest.validate_pytest_cov_included()
        output_files.append(".coverage")

        if coverage_subsystem.filter:
            cov_args = [f"--cov={morf}" for morf in coverage_subsystem.filter]
        else:
            # N.B.: Passing `--cov=` or `--cov=.` to communicate "record coverage for all sources"
            # fails in certain contexts as detailed in:
            #   https://github.com/pantsbuild/pants/issues/12390
            # Instead we focus coverage on just the directories containing python source files
            # materialized to the Process chroot.
            cov_args = [f"--cov={source_root}" for source_root in prepared_sources.source_roots]

        coverage_args = [
            "--cov-report=",  # Turn off output.
            f"--cov-config={coverage_config.path}",
            *cov_args,
        ]

    extra_env = {
        "PYTEST_ADDOPTS": " ".join(add_opts),
        "PEX_EXTRA_SYS_PATH": ":".join(prepared_sources.source_roots),
        **test_extra_env.env,
        # NOTE: field_set_extra_env intentionally after `test_extra_env` to allow overriding within
        # `python_tests`.
        **field_set_extra_env,
    }

    # Cache test runs only if they are successful, or not at all if `--test-force`.
    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )
    process = await Get(
        Process,
        VenvPexProcess(
            pytest_runner_pex,
            argv=(*pytest.args, *coverage_args, *field_set_source_files.files),
            extra_env=extra_env,
            input_digest=input_digest,
            output_directories=(_EXTRA_OUTPUT_DIR,),
            output_files=output_files,
            timeout_seconds=request.field_set.timeout.calculate_from_global_options(pytest),
            execution_slot_variable=pytest.execution_slot_var,
            description=f"Run Pytest for {request.field_set.address}",
            level=LogLevel.DEBUG,
            cache_scope=cache_scope,
        ),
    )
    return TestSetup(process, results_file_name=results_file_name)


@rule(desc="Run Pytest", level=LogLevel.DEBUG)
async def run_python_test(
    field_set: PythonTestFieldSet,
    test_subsystem: TestSubsystem,
) -> TestResult:
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
        if xml_results_snapshot.files != (setup.results_file_name,):
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
        output_setting=test_subsystem.output,
        coverage_data=coverage_data,
        xml_results=xml_results_snapshot,
        extra_output=extra_output_snapshot,
    )


@rule(desc="Set up Pytest to run interactively", level=LogLevel.DEBUG)
async def debug_python_test(field_set: PythonTestFieldSet) -> TestDebugRequest:
    setup = await Get(TestSetup, TestSetupRequest(field_set, is_debug=True))
    return TestDebugRequest(
        InteractiveProcess.from_process(
            setup.process, forward_signals_to_process=False, restartable=True
        )
    )


# -----------------------------------------------------------------------------------------
# `runtime_package_dependencies` plugin
# -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimePackagesPluginRequest(PytestPluginSetupRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        return bool(target.get(RuntimePackageDependenciesField).value)


@rule
async def setup_runtime_packages(request: RuntimePackagesPluginRequest) -> PytestPluginSetup:
    built_packages = await Get(
        BuiltPackageDependencies,
        BuildPackageDependenciesRequest(request.target.get(RuntimePackageDependenciesField)),
    )
    digest = await Get(Digest, MergeDigests(pkg.digest for pkg in built_packages))
    return PytestPluginSetup(digest)


def rules():
    return [
        *collect_rules(),
        UnionRule(TestFieldSet, PythonTestFieldSet),
        UnionRule(PytestPluginSetupRequest, RuntimePackagesPluginRequest),
    ]
