# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from abc import ABC, ABCMeta
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Dict, Iterable, List, Optional, Tuple, Type, TypeVar, cast

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.core.util_rules.filter_empty_sources import (
    FieldSetsWithSources,
    FieldSetsWithSourcesRequest,
)
from pants.engine import desktop
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAware
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult, InteractiveProcess, InteractiveRunner
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSetWithOrigin,
    Sources,
    TargetsToValidFieldSets,
    TargetsToValidFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel


class Status(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class CoverageReportType(Enum):
    CONSOLE = ("console", "report")
    XML = ("xml", None)
    HTML = ("html", None)
    RAW = ("raw", None)

    _report_name: str

    def __new__(cls, value: str, report_name: Optional[str] = None) -> "CoverageReportType":
        member: "CoverageReportType" = object.__new__(cls)
        member._value_ = value
        member._report_name = report_name if report_name is not None else value
        return member

    @property
    def report_name(self) -> str:
        return self._report_name


@dataclass(frozen=True)
class TestResult(EngineAware):
    status: Status
    stdout: str
    stderr: str
    coverage_data: Optional["CoverageData"]
    xml_results: Optional[Digest]
    address_ref: str = ""

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult,
        *,
        coverage_data: Optional["CoverageData"] = None,
        xml_results: Optional[Digest] = None,
        address_ref: str = "",
    ) -> "TestResult":
        return TestResult(
            status=Status.SUCCESS if process_result.exit_code == 0 else Status.FAILURE,
            stdout=process_result.stdout.decode(),
            stderr=process_result.stderr.decode(),
            coverage_data=coverage_data,
            xml_results=xml_results,
            address_ref=address_ref,
        )

    def level(self):
        if self.status == Status.FAILURE:
            return LogLevel.ERROR
        return None

    def message(self):
        result = "succeeded" if self.status == Status.SUCCESS else "failed"
        return f"tests {result}: {self.address_ref}"


@dataclass(frozen=True)
class TestDebugRequest:
    process: InteractiveProcess

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


@union
class TestFieldSet(FieldSetWithOrigin, metaclass=ABCMeta):
    """The fields necessary to run tests on a target."""

    sources: Sources

    __test__ = False


# NB: This is only used for the sake of coordinator_of_tests. Consider inlining that rule so that
# we can remove this wrapper type.
@dataclass(frozen=True)
class WrappedTestFieldSet:
    field_set: TestFieldSet


@dataclass(frozen=True)
class AddressAndTestResult:
    address: Address
    test_result: TestResult


class CoverageData(ABC):
    """Base class for inputs to a coverage report.

    Subclasses should add whichever fields they require - snapshots of coverage output, XML files,
    etc.
    """


_CD = TypeVar("_CD", bound=CoverageData)


@union
class CoverageDataCollection(Collection[_CD]):
    element_type: Type[_CD]


class CoverageReport(ABC):
    """Represents a code coverage report that can be materialized to the terminal or disk."""

    def materialize(self, console: Console, workspace: Workspace) -> Optional[PurePath]:
        """Materialize this code coverage report to the terminal or disk.

        :param console: A handle to the terminal.
        :param workspace: A handle to local disk.
        :return: If a report was materialized to disk, the path of the file in the report one might
                 open first to start examining the report.
        """
        ...


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

    result_digest: Digest
    directory_to_materialize_to: PurePath
    report_file: Optional[PurePath]
    report_type: CoverageReportType

    def materialize(self, console: Console, workspace: Workspace) -> Optional[PurePath]:
        workspace.write_digest(
            self.result_digest, path_prefix=str(self.directory_to_materialize_to)
        )
        console.print_stderr(
            f"\nWrote {self.report_type.report_name} coverage report to `{self.directory_to_materialize_to}`"
        )
        return self.report_file


@dataclass(frozen=True)
class CoverageReports:
    reports: Tuple[CoverageReport, ...]

    def materialize(self, console: Console, workspace: Workspace) -> Tuple[PurePath, ...]:
        report_paths = []
        for report in self.reports:
            report_path = report.materialize(console, workspace)
            if report_path:
                report_paths.append(report_path)
        return tuple(report_paths)


class ShowOutput(Enum):
    """Which tests to emit detailed output for."""

    ALL = "all"
    FAILED = "failed"
    NONE = "none"


class TestSubsystem(GoalSubsystem):
    """Run tests."""

    name = "test"

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
                "Run a single test target in an interactive process. This is necessary, for "
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
    interactive_runner: InteractiveRunner,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Test:
    if test_subsystem.debug:
        targets_to_valid_field_sets = await Get(
            TargetsToValidFieldSets,
            TargetsToValidFieldSetsRequest(
                TestFieldSet,
                goal_description="`test --debug`",
                error_if_no_valid_targets=True,
                expect_single_field_set=True,
            ),
        )
        field_set = targets_to_valid_field_sets.field_sets[0]
        request = await Get(TestDebugRequest, TestFieldSet, field_set)
        debug_result = interactive_runner.run(request.process)
        return Test(debug_result.exit_code)

    targets_to_valid_field_sets = await Get(
        TargetsToValidFieldSets,
        TargetsToValidFieldSetsRequest(
            TestFieldSet,
            goal_description=f"the `{test_subsystem.name}` goal",
            error_if_no_valid_targets=False,
        ),
    )
    field_sets_with_sources = await Get(
        FieldSetsWithSources, FieldSetsWithSourcesRequest(targets_to_valid_field_sets.field_sets)
    )

    results = await MultiGet(
        Get(AddressAndTestResult, WrappedTestFieldSet(field_set))
        for field_set in field_sets_with_sources
    )

    # Print details.
    for result in results:
        if test_subsystem.options.output == ShowOutput.NONE or (
            test_subsystem.options.output == ShowOutput.FAILED
            and result.test_result.status == Status.SUCCESS
        ):
            continue
        has_output = result.test_result.stdout or result.test_result.stderr
        if has_output:
            status = (
                console.green("✓")
                if result.test_result.status == Status.SUCCESS
                else console.red("𐄂")
            )
            console.print_stderr(f"{status} {result.address}")
        if result.test_result.stdout:
            console.print_stderr(result.test_result.stdout)
        if result.test_result.stderr:
            console.print_stderr(result.test_result.stderr)
        if has_output and result != results[-1]:
            console.print_stderr("")

    # Print summary
    console.print_stderr("")
    for result in results:
        color = console.green if result.test_result.status == Status.SUCCESS else console.red
        # The right-align logic sees the color control codes as characters, so we have
        # to account for that. In f-strings the alignment field widths must be literals,
        # so we have to indirect via a call to .format().
        right_align = 19 if console.use_colors else 10
        format_str = f"{{addr:80}}.....{{result:>{right_align}}}"
        console.print_stderr(
            format_str.format(
                addr=result.address.reference(), result=color(result.test_result.status.value)
            )
        )

    merged_xml_results = await Get(
        Digest,
        MergeDigests(
            result.test_result.xml_results for result in results if result.test_result.xml_results
        ),
    )
    workspace.write_digest(merged_xml_results)

    if test_subsystem.use_coverage:
        all_coverage_data: Iterable[CoverageData] = [
            result.test_result.coverage_data
            for result in results
            if result.test_result.coverage_data is not None
        ]

        coverage_types_to_collection_types: Dict[
            Type[CoverageData], Type[CoverageDataCollection]
        ] = {
            collection_cls.element_type: collection_cls
            for collection_cls in union_membership.get(CoverageDataCollection)
        }
        coverage_collections: List[CoverageDataCollection] = []
        for data_cls, data in itertools.groupby(all_coverage_data, lambda data: type(data)):
            collection_cls = coverage_types_to_collection_types[data_cls]
            coverage_collections.append(collection_cls(data))
        # We can create multiple reports for each coverage data (console, xml and html)
        coverage_reports_collections = await MultiGet(
            Get(CoverageReports, CoverageDataCollection, coverage_collection)
            for coverage_collection in coverage_collections
        )

        coverage_report_files: List[PurePath] = []
        for coverage_reports in coverage_reports_collections:
            report_files = coverage_reports.materialize(console, workspace)
            coverage_report_files.extend(report_files)

        if coverage_report_files and test_subsystem.open_coverage:
            desktop.ui_open(console, interactive_runner, coverage_report_files)

    exit_code = (
        PANTS_FAILED_EXIT_CODE
        if any(res.test_result.status == Status.FAILURE for res in results)
        else PANTS_SUCCEEDED_EXIT_CODE
    )

    return Test(exit_code)


@rule(desc="Run test target")
async def coordinator_of_tests(wrapped_field_set: WrappedTestFieldSet) -> AddressAndTestResult:
    field_set = wrapped_field_set.field_set
    result = await Get(TestResult, TestFieldSet, field_set)
    return AddressAndTestResult(field_set.address, result)


def rules():
    return collect_rules()
