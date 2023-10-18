# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Tuple

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.goals.coverage_py import (
    CoverageConfig,
    CoverageSubsystem,
    PytestCoverageData,
)
from pants.backend.python.subsystems import pytest
from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.subsystems.pytest import PyTest, PythonTestFieldSet
from pants.backend.python.subsystems.python_tool_base import get_lockfile_metadata
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.backend.python.util_rules.lockfile_metadata import (
    PythonLockfileMetadataV2,
    PythonLockfileMetadataV3,
)
from pants.backend.python.util_rules.pex import Pex, PexRequest, ReqStrings, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.test import (
    BuildPackageDependenciesRequest,
    BuiltPackageDependencies,
    RuntimePackageDependenciesField,
    TestDebugAdapterRequest,
    TestDebugRequest,
    TestExtraEnv,
    TestRequest,
    TestResult,
    TestSubsystem,
)
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import Partition, PartitionerType, Partitions
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    Directory,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import (
    InteractiveProcess,
    Process,
    ProcessCacheScope,
    ProcessResultWithRetries,
    RunProcWithRetry,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.global_options import GlobalOptions
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import softwrap

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


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
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
    addresses: tuple[Address, ...]


@rule
async def run_all_setup_plugins(
    request: AllPytestPluginSetupsRequest, union_membership: UnionMembership
) -> AllPytestPluginSetups:
    wrapped_tgts = await MultiGet(
        Get(WrappedTarget, WrappedTargetRequest(address, description_of_origin="<infallible>"))
        for address in request.addresses
    )
    setup_requests = [
        request_type(wrapped_tgt.target)  # type: ignore[abstract]
        for request_type in union_membership.get(PytestPluginSetupRequest)
        for wrapped_tgt in wrapped_tgts
        if request_type.is_applicable(wrapped_tgt.target)
    ]
    setups = await MultiGet(
        Get(PytestPluginSetup, PytestPluginSetupRequest, request) for request in setup_requests
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
class TestMetadata:
    """Parameters that must be constant for all test targets in a `pytest` batch."""

    interpreter_constraints: InterpreterConstraints
    extra_env_vars: tuple[str, ...]
    xdist_concurrency: int | None
    resolve: str
    environment: str
    compatability_tag: str | None = None

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @property
    def description(self) -> str | None:
        if not self.compatability_tag:
            return None

        # TODO: Put more info here.
        return self.compatability_tag


@dataclass(frozen=True)
class TestSetupRequest:
    field_sets: Tuple[PythonTestFieldSet, ...]
    metadata: TestMetadata
    is_debug: bool
    extra_env: FrozenDict[str, str] = FrozenDict()
    prepend_argv: Tuple[str, ...] = ()
    additional_pexes: Tuple[Pex, ...] = ()


@dataclass(frozen=True)
class TestSetup:
    process: Process
    results_file_name: Optional[str]

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


_TEST_PATTERN = re.compile(b"def\\s+test_")


def _count_pytest_tests(contents: DigestContents) -> int:
    return sum(len(_TEST_PATTERN.findall(file.content)) for file in contents)


async def validate_pytest_cov_included(_pytest: PyTest):
    if _pytest.requirements:
        # We'll only be using this subset of the lockfile.
        req_strings = (await Get(ReqStrings, PexRequirements(_pytest.requirements))).req_strings
        requirements = {PipRequirement.parse(req_string) for req_string in req_strings}
    else:
        # We'll be using the entire lockfile.
        lockfile_metadata = await get_lockfile_metadata(_pytest)
        if not isinstance(lockfile_metadata, (PythonLockfileMetadataV2, PythonLockfileMetadataV3)):
            return
        requirements = lockfile_metadata.requirements
    if not any(canonicalize_project_name(req.project_name) == "pytest-cov" for req in requirements):
        raise ValueError(
            softwrap(
                f"""\
                You set `[test].use_coverage`, but the custom resolve
                `{_pytest.install_from_resolve}` used to install pytest is missing
                `pytest-cov`, which is needed to collect coverage data.

                See {doc_url("python-test-goal#pytest-version-and-plugins")} for details
                on how to set up a custom resolve for use by pytest.
                """
            )
        )


@rule(level=LogLevel.DEBUG)
async def setup_pytest_for_target(
    request: TestSetupRequest,
    pytest: PyTest,
    test_subsystem: TestSubsystem,
    coverage_config: CoverageConfig,
    coverage_subsystem: CoverageSubsystem,
    test_extra_env: TestExtraEnv,
) -> TestSetup:
    addresses = tuple(field_set.address for field_set in request.field_sets)

    transitive_targets, plugin_setups = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest(addresses)),
        Get(AllPytestPluginSetups, AllPytestPluginSetupsRequest(addresses)),
    )
    all_targets = transitive_targets.closure

    interpreter_constraints = request.metadata.interpreter_constraints

    requirements_pex_get = Get(Pex, RequirementsPexRequest(addresses))
    pytest_pex_get = Get(
        Pex, PexRequest, pytest.to_pex_request(interpreter_constraints=interpreter_constraints)
    )

    # Ensure that the empty extra output dir exists.
    extra_output_directory_digest_get = Get(Digest, CreateDigest([Directory(_EXTRA_OUTPUT_DIR)]))

    prepared_sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(all_targets, include_files=True)
    )

    # Get the file names for the test_target so that we can specify to Pytest precisely which files
    # to test, rather than using auto-discovery.
    field_set_source_files_get = Get(
        SourceFiles, SourceFilesRequest([field_set.source for field_set in request.field_sets])
    )

    field_set_extra_env_get = Get(
        EnvironmentVars, EnvironmentVarsRequest(request.metadata.extra_env_vars)
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
            addresses,
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
            pex_path=[pytest_pex, requirements_pex, local_dists.pex, *request.additional_pexes],
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

    # Don't forget to keep "Customize Pytest command line options per target" section in
    # docs/markdown/Python/python-goals/python-test-goal.md up to date when changing
    # which flags are added to `pytest_args`.
    pytest_args = [
        # Always include colors and strip them out for display below (if required), for better cache
        # hit rates
        "--color=yes"
    ]
    output_files = []

    results_file_name = None
    if not request.is_debug:
        results_file_prefix = request.field_sets[0].address.path_safe_spec
        if len(request.field_sets) > 1:
            results_file_prefix = (
                f"batch-of-{results_file_prefix}+{len(request.field_sets)-1}-files"
            )
        results_file_name = f"{results_file_prefix}.xml"
        pytest_args.extend(
            (f"--junit-xml={results_file_name}", "-o", f"junit_family={pytest.junit_family}")
        )
        output_files.append(results_file_name)

    if test_subsystem.use_coverage and not request.is_debug:
        await validate_pytest_cov_included(pytest)
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

        pytest_args.extend(
            (
                "--cov-report=",  # Turn off output.
                f"--cov-config={coverage_config.path}",
                *cov_args,
            )
        )

    extra_env = {
        "PEX_EXTRA_SYS_PATH": ":".join(prepared_sources.source_roots),
        **request.extra_env,
        **test_extra_env.env,
        # NOTE: field_set_extra_env intentionally after `test_extra_env` to allow overriding within
        # `python_tests`.
        **field_set_extra_env,
    }

    # Cache test runs only if they are successful, or not at all if `--test-force`.
    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    xdist_concurrency = 0
    if pytest.xdist_enabled and not request.is_debug:
        concurrency = request.metadata.xdist_concurrency
        if concurrency is None:
            contents = await Get(DigestContents, Digest, field_set_source_files.snapshot.digest)
            concurrency = _count_pytest_tests(contents)
        xdist_concurrency = concurrency

    timeout_seconds: int | None = None
    for field_set in request.field_sets:
        timeout = field_set.timeout.calculate_from_global_options(test_subsystem, pytest)
        if timeout:
            if timeout_seconds:
                timeout_seconds += timeout
            else:
                timeout_seconds = timeout

    run_description = request.field_sets[0].address.spec
    if len(request.field_sets) > 1:
        run_description = f"batch of {run_description} and {len(request.field_sets)-1} other files"
    process = await Get(
        Process,
        VenvPexProcess(
            pytest_runner_pex,
            argv=(
                *request.prepend_argv,
                *pytest.args,
                *(("-c", pytest.config) if pytest.config else ()),
                *(("-n", "{pants_concurrency}") if xdist_concurrency else ()),
                # N.B.: Now that we're using command-line options instead of the PYTEST_ADDOPTS
                # environment variable, it's critical that `pytest_args` comes after `pytest.args`.
                *pytest_args,
                *field_set_source_files.files,
            ),
            extra_env=extra_env,
            input_digest=input_digest,
            output_directories=(_EXTRA_OUTPUT_DIR,),
            output_files=output_files,
            timeout_seconds=timeout_seconds,
            execution_slot_variable=pytest.execution_slot_var,
            concurrency_available=xdist_concurrency,
            description=f"Run Pytest for {run_description}",
            level=LogLevel.DEBUG,
            cache_scope=cache_scope,
        ),
    )
    return TestSetup(process, results_file_name=results_file_name)


class PyTestRequest(TestRequest):
    tool_subsystem = PyTest
    field_set_type = PythonTestFieldSet
    partitioner_type = PartitionerType.CUSTOM
    supports_debug = True
    supports_debug_adapter = True


@rule(desc="Partition Pytest", level=LogLevel.DEBUG)
async def partition_python_tests(
    request: PyTestRequest.PartitionRequest[PythonTestFieldSet],
    python_setup: PythonSetup,
) -> Partitions[PythonTestFieldSet, TestMetadata]:
    partitions = []
    compatible_tests = defaultdict(list)

    for field_set in request.field_sets:
        metadata = TestMetadata(
            interpreter_constraints=InterpreterConstraints.create_from_compatibility_fields(
                [field_set.interpreter_constraints], python_setup
            ),
            extra_env_vars=field_set.extra_env_vars.sorted(),
            xdist_concurrency=field_set.xdist_concurrency.value,
            resolve=field_set.resolve.normalized_value(python_setup),
            environment=field_set.environment.value,
            compatability_tag=field_set.batch_compatibility_tag.value,
        )

        if not metadata.compatability_tag:
            # Tests without a compatibility tag are assumed to be incompatible with all others.
            partitions.append(Partition((field_set,), metadata))
        else:
            # Group tests by their common metadata.
            compatible_tests[metadata].append(field_set)

    for metadata, field_sets in compatible_tests.items():
        partitions.append(Partition(tuple(field_sets), metadata))

    return Partitions(partitions)


@rule(desc="Run Pytest", level=LogLevel.DEBUG)
async def run_python_tests(
    batch: PyTestRequest.Batch[PythonTestFieldSet, TestMetadata],
    test_subsystem: TestSubsystem,
    global_options: GlobalOptions,
) -> TestResult:
    setup = await Get(
        TestSetup, TestSetupRequest(batch.elements, batch.partition_metadata, is_debug=False)
    )
    HARDCODED_RETRY_COUNT = 5  # TODO: get from global option or batch
    results = await Get(
        ProcessResultWithRetries, RunProcWithRetry(setup.process, HARDCODED_RETRY_COUNT)
    )
    last_result = results.last

    def warning_description() -> str:
        description = batch.elements[0].address.spec
        if len(batch.elements) > 1:
            description = f"batch containing {description} and {len(batch.elements)-1} other files"
        if batch.partition_metadata.description:
            description = f"{description} ({batch.partition_metadata.description})"
        return description

    coverage_data = None
    if test_subsystem.use_coverage:
        coverage_snapshot = await Get(
            Snapshot, DigestSubset(last_result.output_digest, PathGlobs([".coverage"]))
        )
        if coverage_snapshot.files == (".coverage",):
            coverage_data = PytestCoverageData(
                tuple(field_set.address for field_set in batch.elements), coverage_snapshot.digest
            )
        else:
            logger.warning(f"Failed to generate coverage data for {warning_description()}.")

    xml_results_snapshot = None
    if setup.results_file_name:
        xml_results_snapshot = await Get(
            Snapshot, DigestSubset(last_result.output_digest, PathGlobs([setup.results_file_name]))
        )
        if xml_results_snapshot.files != (setup.results_file_name,):
            logger.warning(f"Failed to generate JUnit XML data for {warning_description()}.")
    extra_output_snapshot = await Get(
        Snapshot, DigestSubset(last_result.output_digest, PathGlobs([f"{_EXTRA_OUTPUT_DIR}/**"]))
    )
    extra_output_snapshot = await Get(
        Snapshot, RemovePrefix(extra_output_snapshot.digest, _EXTRA_OUTPUT_DIR)
    )

    return TestResult.from_batched_fallible_process_result(
        last_result,
        batch=batch,
        output_setting=test_subsystem.output,
        coverage_data=coverage_data,
        xml_results=xml_results_snapshot,
        extra_output=extra_output_snapshot,
        all_results=results.results,
        output_simplifier=global_options.output_simplifier(),
    )


@rule(desc="Set up Pytest to run interactively", level=LogLevel.DEBUG)
async def debug_python_test(
    batch: PyTestRequest.Batch[PythonTestFieldSet, TestMetadata]
) -> TestDebugRequest:
    setup = await Get(
        TestSetup, TestSetupRequest(batch.elements, batch.partition_metadata, is_debug=True)
    )
    return TestDebugRequest(
        InteractiveProcess.from_process(
            setup.process, forward_signals_to_process=False, restartable=True
        )
    )


@rule(desc="Set up debugpy to run an interactive Pytest session", level=LogLevel.DEBUG)
async def debugpy_python_test(
    batch: PyTestRequest.Batch[PythonTestFieldSet, TestMetadata],
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
    python_setup: PythonSetup,
) -> TestDebugAdapterRequest:
    debugpy_pex = await Get(
        Pex,
        PexRequest,
        debugpy.to_pex_request(
            interpreter_constraints=InterpreterConstraints.create_from_compatibility_fields(
                [field_set.interpreter_constraints for field_set in batch.elements], python_setup
            )
        ),
    )

    setup = await Get(
        TestSetup,
        TestSetupRequest(
            batch.elements,
            batch.partition_metadata,
            is_debug=True,
            prepend_argv=debugpy.get_args(debug_adapter),
            extra_env=FrozenDict(PEX_MODULE="debugpy"),
            additional_pexes=(debugpy_pex,),
        ),
    )
    return TestDebugAdapterRequest(
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
        *pytest.rules(),
        UnionRule(PytestPluginSetupRequest, RuntimePackagesPluginRequest),
        *PyTestRequest.rules(),
    ]
