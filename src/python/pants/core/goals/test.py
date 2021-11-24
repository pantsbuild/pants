# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from abc import ABC, ABCMeta
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, ClassVar, List, TypeVar, cast

from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address, UnparsedAddressInputs
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.desktop import OpenFiles, OpenFilesRequest
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import EMPTY_FILE_DIGEST, Digest, FileDigest, MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult, InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    NoApplicableTargetsBehavior,
    SourcesField,
    SpecialCasedDependencies,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
)
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TestResult(EngineAwareReturnType):
    exit_code: int | None
    stdout: str
    stdout_digest: FileDigest
    stderr: str
    stderr_digest: FileDigest
    address: Address
    output_setting: ShowOutput

    coverage_data: CoverageData | None = None
    xml_results: Snapshot | None = None
    # Any extra output (such as from plugins) that the test runner was configured to output.
    extra_output: Snapshot | None = None

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @classmethod
    def skip(cls, address: Address, output_setting: ShowOutput) -> TestResult:
        return cls(
            exit_code=None,
            stdout="",
            stderr="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            address=address,
            output_setting=output_setting,
        )

    @classmethod
    def from_fallible_process_result(
        cls,
        process_result: FallibleProcessResult,
        address: Address,
        output_setting: ShowOutput,
        *,
        coverage_data: CoverageData | None = None,
        xml_results: Snapshot | None = None,
        extra_output: Snapshot | None = None,
    ) -> TestResult:
        return cls(
            exit_code=process_result.exit_code,
            stdout=process_result.stdout.decode(),
            stdout_digest=process_result.stdout_digest,
            stderr=process_result.stderr.decode(),
            stderr_digest=process_result.stderr_digest,
            address=address,
            output_setting=output_setting,
            coverage_data=coverage_data,
            xml_results=xml_results,
            extra_output=extra_output,
        )

    @property
    def skipped(self) -> bool:
        return self.exit_code is None and not self.stdout and not self.stderr

    def __lt__(self, other: Any) -> bool:
        """We sort first by status (skipped vs failed vs succeeded), then alphanumerically within
        each group."""
        if not isinstance(other, TestResult):
            return NotImplemented
        if self.exit_code == other.exit_code:
            return self.address.spec < other.address.spec
        if self.exit_code is None:
            return True
        if other.exit_code is None:
            return False
        return abs(self.exit_code) < abs(other.exit_code)

    def artifacts(self) -> dict[str, FileDigest | Snapshot] | None:
        output: dict[str, FileDigest | Snapshot] = {
            "stdout": self.stdout_digest,
            "stderr": self.stderr_digest,
        }
        if self.xml_results:
            output["xml_results"] = self.xml_results
        return output

    def level(self) -> LogLevel:
        if self.skipped:
            return LogLevel.DEBUG
        return LogLevel.INFO if self.exit_code == 0 else LogLevel.ERROR

    def message(self) -> str:
        if self.skipped:
            return f"{self.address} skipped."
        status = "succeeded" if self.exit_code == 0 else f"failed (exit code {self.exit_code})"
        message = f"{self.address} {status}."
        if self.output_setting == ShowOutput.NONE or (
            self.output_setting == ShowOutput.FAILED and self.exit_code == 0
        ):
            return message
        output = ""
        if self.stdout:
            output += f"\n{self.stdout}"
        if self.stderr:
            output += f"\n{self.stderr}"
        if output:
            output = f"{output.rstrip()}\n\n"
        return f"{message}{output}"

    def metadata(self) -> dict[str, Any]:
        return {"address": self.address.spec}

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


class ShowOutput(Enum):
    """Which tests to emit detailed output for."""

    ALL = "all"
    FAILED = "failed"
    NONE = "none"


@dataclass(frozen=True)
class TestDebugRequest:
    process: InteractiveProcess | None

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


@union
@dataclass(frozen=True)
class TestFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to run tests on a target."""

    sources: SourcesField

    __test__ = False


class CoverageData(ABC):
    """Base class for inputs to a coverage report.

    Subclasses should add whichever fields they require - snapshots of coverage output, XML files,
    etc.
    """


_CD = TypeVar("_CD", bound=CoverageData)


@union
class CoverageDataCollection(Collection[_CD]):
    element_type: ClassVar[type[_CD]]


@dataclass(frozen=True)
class CoverageReport(ABC):
    """Represents a code coverage report that can be materialized to the terminal or disk."""

    # Some coverage systems can determine, based on a configurable threshold, whether coverage
    # was sufficient or not. The test goal will fail the build if coverage was deemed insufficient.
    coverage_insufficient: bool

    def materialize(self, console: Console, workspace: Workspace) -> PurePath | None:
        """Materialize this code coverage report to the terminal or disk.

        :param console: A handle to the terminal.
        :param workspace: A handle to local disk.
        :return: If a report was materialized to disk, the path of the file in the report one might
                 open first to start examining the report.
        """
        ...

    def get_artifact(self) -> tuple[str, Snapshot] | None:
        return None


@dataclass(frozen=True)
class ConsoleCoverageReport(CoverageReport):
    """Materializes a code coverage report to the terminal."""

    report: str

    def materialize(self, console: Console, workspace: Workspace) -> None:
        console.print_stderr(f"\n{self.report}")
        return None


@dataclass(frozen=True)
class FilesystemCoverageReport(CoverageReport):
    """Materializes a code coverage report to disk."""

    result_snapshot: Snapshot
    directory_to_materialize_to: PurePath
    report_file: PurePath | None
    report_type: str

    def materialize(self, console: Console, workspace: Workspace) -> PurePath | None:
        workspace.write_digest(
            self.result_snapshot.digest, path_prefix=str(self.directory_to_materialize_to)
        )
        console.print_stderr(
            f"\nWrote {self.report_type} coverage report to `{self.directory_to_materialize_to}`"
        )
        return self.report_file

    def get_artifact(self) -> tuple[str, Snapshot] | None:
        return f"coverage_{self.report_type}", self.result_snapshot


@dataclass(frozen=True)
class CoverageReports(EngineAwareReturnType):
    reports: tuple[CoverageReport, ...]

    @property
    def coverage_insufficient(self) -> bool:
        """Whether to fail the build due to insufficient coverage."""
        return any(report.coverage_insufficient for report in self.reports)

    def materialize(self, console: Console, workspace: Workspace) -> tuple[PurePath, ...]:
        report_paths = []
        for report in self.reports:
            report_path = report.materialize(console, workspace)
            if report_path:
                report_paths.append(report_path)
        return tuple(report_paths)

    def artifacts(self) -> dict[str, Snapshot | FileDigest] | None:
        artifacts: dict[str, Snapshot | FileDigest] = {}
        for report in self.reports:
            artifact = report.get_artifact()
            if not artifact:
                continue
            artifacts[artifact[0]] = artifact[1]
        return artifacts or None


class TestSubsystem(GoalSubsystem):
    name = "test"
    help = "Run tests."

    required_union_implementations = (TestFieldSet,)

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--debug",
            type=bool,
            default=False,
            help=(
                "Run tests sequentially in an interactive process. This is necessary, for "
                "example, when you add breakpoints to your code."
            ),
        )
        register(
            "--force",
            type=bool,
            default=False,
            help="Force the tests to run, even if they could be satisfied from cache.",
        )
        register(
            "--output",
            type=ShowOutput,
            default=ShowOutput.FAILED,
            help="Show stdout/stderr for these tests.",
        )
        register(
            "--use-coverage",
            type=bool,
            default=False,
            help="Generate a coverage report if the test runner supports it.",
        )
        register(
            "--open-coverage",
            type=bool,
            default=False,
            help=(
                "If a coverage report file is generated, open it on the local system if the "
                "system supports this."
            ),
        )
        register(
            "--xml-dir",
            type=str,
            metavar="<DIR>",
            default=None,
            advanced=True,
            help=(
                "Specifying a directory causes Junit XML result files to be emitted under "
                "that dir for each test run that supports producing them."
            ),
        )
        register(
            "--extra-env-vars",
            type=list,
            member_type=str,
            default=[],
            help=(
                "Additional environment variables to include in test processes. "
                "Entries are strings in the form `ENV_VAR=value` to use explicitly; or just "
                "`ENV_VAR` to copy the value of a variable in Pants's own environment."
            ),
        )

    @property
    def extra_env_vars(self) -> list[str]:
        return cast(List[str], self.options.extra_env_vars)

    @property
    def debug(self) -> bool:
        return cast(bool, self.options.debug)

    @property
    def force(self) -> bool:
        return cast(bool, self.options.force)

    @property
    def output(self) -> ShowOutput:
        return cast(ShowOutput, self.options.output)

    @property
    def use_coverage(self) -> bool:
        return cast(bool, self.options.use_coverage)

    @property
    def open_coverage(self) -> bool:
        return cast(bool, self.options.open_coverage)


class Test(Goal):
    subsystem_cls = TestSubsystem

    __test__ = False


@goal_rule
async def run_tests(
    console: Console,
    test_subsystem: TestSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
    dist_dir: DistDir,
) -> Test:
    if test_subsystem.debug:
        targets_to_valid_field_sets = await Get(
            TargetRootsToFieldSets,
            TargetRootsToFieldSetsRequest(
                TestFieldSet,
                goal_description="`test --debug`",
                no_applicable_targets_behavior=NoApplicableTargetsBehavior.error,
            ),
        )
        debug_requests = await MultiGet(
            Get(TestDebugRequest, TestFieldSet, field_set)
            for field_set in targets_to_valid_field_sets.field_sets
        )
        exit_code = 0
        for debug_request, field_set in zip(debug_requests, targets_to_valid_field_sets.field_sets):
            if debug_request.process is None:
                logger.debug(f"Skipping tests for {field_set.address}")
                continue
            debug_result = await Effect(
                InteractiveProcessResult, InteractiveProcess, debug_request.process
            )
            if debug_result.exit_code != 0:
                exit_code = debug_result.exit_code
        return Test(exit_code)

    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            TestFieldSet,
            goal_description=f"the `{test_subsystem.name}` goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.warn,
        ),
    )
    results = await MultiGet(
        Get(TestResult, TestFieldSet, field_set)
        for field_set in targets_to_valid_field_sets.field_sets
    )

    # Print summary.
    exit_code = 0
    if results:
        console.print_stderr("")
    for result in sorted(results):
        if result.skipped:
            continue
        if result.exit_code == 0:
            sigil = console.sigil_succeeded()
            status = "succeeded"
        else:
            sigil = console.sigil_failed()
            status = "failed"
            exit_code = cast(int, result.exit_code)
        console.print_stderr(f"{sigil} {result.address} {status}.")
        if result.extra_output and result.extra_output.files:
            workspace.write_digest(
                result.extra_output.digest,
                path_prefix=str(dist_dir.relpath / "test" / result.address.path_safe_spec),
            )

    if test_subsystem.options.xml_dir:
        xml_dir = test_subsystem.options.xml_dir
        merged_xml_results = await Get(
            Digest,
            MergeDigests(result.xml_results.digest for result in results if result.xml_results),
        )
        workspace.write_digest(merged_xml_results, path_prefix=xml_dir)
        console.print_stderr(f"\nWrote test XML to `{xml_dir}`")

    if test_subsystem.use_coverage:
        # NB: We must pre-sort the data for itertools.groupby() to work properly, using the same
        # key function for both. However, you can't sort by `types`, so we call `str()` on it.
        all_coverage_data = sorted(
            (result.coverage_data for result in results if result.coverage_data is not None),
            key=lambda cov_data: str(type(cov_data)),
        )

        coverage_types_to_collection_types = {
            collection_cls.element_type: collection_cls  # type: ignore[misc]
            for collection_cls in union_membership.get(CoverageDataCollection)
        }
        coverage_collections = []
        for data_cls, data in itertools.groupby(all_coverage_data, lambda data: type(data)):
            collection_cls = coverage_types_to_collection_types[data_cls]
            coverage_collections.append(collection_cls(data))
        # We can create multiple reports for each coverage data (e.g., console, xml, html)
        coverage_reports_collections = await MultiGet(
            Get(CoverageReports, CoverageDataCollection, coverage_collection)
            for coverage_collection in coverage_collections
        )

        coverage_report_files: list[PurePath] = []
        for coverage_reports in coverage_reports_collections:
            report_files = coverage_reports.materialize(console, workspace)
            coverage_report_files.extend(report_files)

        if coverage_report_files and test_subsystem.open_coverage:
            open_files = await Get(
                OpenFiles, OpenFilesRequest(coverage_report_files, error_if_open_not_found=False)
            )
            for process in open_files.processes:
                _ = await Effect(InteractiveProcessResult, InteractiveProcess, process)

        for coverage_reports in coverage_reports_collections:
            if coverage_reports.coverage_insufficient:
                logger.error(
                    "Test goal failed due to insufficient coverage. "
                    "See coverage reports for details."
                )
                # coverage.py uses 2 to indicate failure due to insufficient coverage.
                # We may as well follow suit in the general case, for all languages.
                exit_code = 2

    return Test(exit_code)


@dataclass(frozen=True)
class TestExtraEnv:
    env: Environment


@rule
async def get_filtered_environment(test_subsystem: TestSubsystem) -> TestExtraEnv:
    return TestExtraEnv(await Get(Environment, EnvironmentRequest(test_subsystem.extra_env_vars)))


# -------------------------------------------------------------------------------------------
# `runtime_package_dependencies` field
# -------------------------------------------------------------------------------------------


class RuntimePackageDependenciesField(SpecialCasedDependencies):
    alias = "runtime_package_dependencies"
    help = (
        "Addresses to targets that can be built with the `./pants package` goal and whose "
        "resulting artifacts should be included in the test run.\n\nPants will build the artifacts "
        "as if you had run `./pants package`. It will include the results in your test's chroot, "
        "using the same name they would normally have, but without the `--distdir` prefix (e.g. "
        "`dist/`).\n\nYou can include anything that can be built by `./pants package`, e.g. a "
        "`pex_binary`, `python_awslambda`, or an `archive`."
    )


class BuiltPackageDependencies(Collection[BuiltPackage]):
    pass


@dataclass(frozen=True)
class BuildPackageDependenciesRequest:
    field: RuntimePackageDependenciesField


@rule(desc="Build runtime package dependencies for tests", level=LogLevel.DEBUG)
async def build_runtime_package_dependencies(
    request: BuildPackageDependenciesRequest,
) -> BuiltPackageDependencies:
    unparsed_addresses = request.field.to_unparsed_address_inputs()
    if not unparsed_addresses:
        return BuiltPackageDependencies()
    tgts = await Get(Targets, UnparsedAddressInputs, unparsed_addresses)
    field_sets_per_tgt = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, tgts)
    )
    packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in field_sets_per_tgt.field_sets
    )
    return BuiltPackageDependencies(packages)


def rules():
    return [
        *collect_rules(),
    ]
