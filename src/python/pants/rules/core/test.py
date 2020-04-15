# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import itertools
import logging
from abc import ABC
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import ClassVar, Dict, Iterable, List, Optional, Tuple, Type, TypeVar

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import OriginSpec
from pants.build_graph.address import Address
from pants.engine import desktop
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.isolated_process import FallibleProcessResult
from pants.engine.objects import Collection, union
from pants.engine.rules import UnionMembership, goal_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    Field,
    RegisteredTargetTypes,
    Sources,
    Target,
    TargetsWithOrigins,
    TargetWithOrigin,
)
from pants.rules.core.filter_empty_sources import (
    ConfigurationsWithSources,
    ConfigurationsWithSourcesRequest,
)

# TODO(#6004): use proper Logging singleton, rather than static logger.
logger = logging.getLogger(__name__)


class Status(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class TestResult:
    status: Status
    stdout: str
    stderr: str
    coverage_data: Optional["CoverageData"] = None

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult, *, coverage_data: Optional["CoverageData"] = None,
    ) -> "TestResult":
        return TestResult(
            status=Status.SUCCESS if process_result.exit_code == 0 else Status.FAILURE,
            stdout=process_result.stdout.decode(),
            stderr=process_result.stderr.decode(),
            coverage_data=coverage_data,
        )


@dataclass(frozen=True)
class TestDebugRequest:
    ipr: InteractiveProcessRequest

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


# TODO: Factor this out once porting fmt.py and lint.py to the Target API. See `binary.py` for a
#  similar implementation (that one doesn't keep the `OriginSpec`).
@union
@dataclass(frozen=True)
class TestConfiguration(ABC):
    """An ad hoc collection of the fields necessary to run tests on a target."""

    required_fields: ClassVar[Tuple[Type[Field], ...]]

    address: Address
    origin: OriginSpec

    sources: Sources

    __test__ = False

    @classmethod
    def is_valid(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields)

    @classmethod
    def valid_target_types(
        cls, target_types: Iterable[Type[Target]], *, union_membership: UnionMembership
    ) -> Tuple[Type[Target], ...]:
        return tuple(
            target_type
            for target_type in target_types
            if target_type.class_has_fields(cls.required_fields, union_membership=union_membership)
        )

    @classmethod
    def create(cls, target_with_origin: TargetWithOrigin) -> "TestConfiguration":
        all_expected_fields: Dict[str, Type[Field]] = {
            dataclass_field.name: dataclass_field.type
            for dataclass_field in dataclasses.fields(cls)
            if isinstance(dataclass_field.type, type) and issubclass(dataclass_field.type, Field)  # type: ignore[unreachable]
        }
        tgt = target_with_origin.target
        return cls(
            address=tgt.address,
            origin=target_with_origin.origin,
            **{  # type: ignore[arg-type]
                dataclass_field_name: (
                    tgt[field_cls] if field_cls in cls.required_fields else tgt.get(field_cls)
                )
                for dataclass_field_name, field_cls in all_expected_fields.items()
            },
        )


# NB: This is only used for the sake of coordinator_of_tests. Consider inlining that rule so that
# we can remove this wrapper type.
@dataclass(frozen=True)
class WrappedTestConfiguration:
    config: TestConfiguration


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

    def materialize(self, console: Console, workspace: Workspace) -> Optional[PurePath]:
        console.print_stdout(f"\n{self.report}")
        return None


@dataclass(frozen=True)
class FilesystemCoverageReport(CoverageReport):
    """Materializes a code coverage report to disk."""

    result_digest: Digest
    directory_to_materialize_to: PurePath
    report_file: Optional[PurePath]

    def materialize(self, console: Console, workspace: Workspace) -> Optional[PurePath]:
        workspace.materialize_directory(
            DirectoryToMaterialize(
                self.result_digest, path_prefix=str(self.directory_to_materialize_to),
            )
        )
        console.print_stdout(f"\nWrote coverage report to `{self.directory_to_materialize_to}`")
        return self.report_file


class TestOptions(GoalSubsystem):
    """Runs tests."""

    name = "test"

    required_union_implementations = (TestConfiguration,)

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--debug",
            type=bool,
            default=False,
            help="Run a single test target in an interactive process. This is necessary, for "
            "example, when you add breakpoints in your code.",
        )
        register(
            "--run-coverage",
            type=bool,
            default=False,
            help="Generate a coverage report for this test run.",
        )
        register(
            "--open-coverage",
            type=bool,
            default=False,
            help="If a coverage report file is generated, open it on the local system if the "
            "system supports this.",
        )


class Test(Goal):
    subsystem_cls = TestOptions

    __test__ = False


@goal_rule
async def run_tests(
    console: Console,
    options: TestOptions,
    interactive_runner: InteractiveRunner,
    targets_with_origins: TargetsWithOrigins,
    workspace: Workspace,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> Test:
    config_types: Iterable[Type[TestConfiguration]] = union_membership.union_rules[
        TestConfiguration
    ]

    if options.values.debug:
        target_with_origin = targets_with_origins.expect_single()
        target = target_with_origin.target
        valid_config_types = [
            config_type for config_type in config_types if config_type.is_valid(target)
        ]
        if not valid_config_types:
            all_valid_target_types = itertools.chain.from_iterable(
                config_type.valid_target_types(
                    registered_target_types.types, union_membership=union_membership
                )
                for config_type in config_types
            )
            formatted_target_types = sorted(
                target_type.alias for target_type in all_valid_target_types
            )
            raise ValueError(
                f"The `test` goal only works with the following target types: "
                f"{formatted_target_types}\n\nYou used {target.address} with target "
                f"type {repr(target.alias)}."
            )
        if len(valid_config_types) > 1:
            possible_config_types = sorted(
                config_type.__name__ for config_type in valid_config_types
            )
            raise ValueError(
                f"Multiple of the registered test implementations work for {target.address} "
                f"(target type {repr(target.alias)}). It is ambiguous which implementation to use. "
                f"Possible implementations: {possible_config_types}."
            )
        config_type = valid_config_types[0]
        logger.info(f"Starting test in debug mode: {target.address.reference()}")
        request = await Get[TestDebugRequest](
            TestConfiguration, config_type.create(target_with_origin)
        )
        debug_result = interactive_runner.run_local_interactive_process(request.ipr)
        return Test(debug_result.process_exit_code)

    configs = tuple(
        config_type.create(target_with_origin)
        for target_with_origin in targets_with_origins
        for config_type in config_types
        if config_type.is_valid(target_with_origin.target)
    )
    configs_with_sources = await Get[ConfigurationsWithSources](
        ConfigurationsWithSourcesRequest(configs)
    )

    results = await MultiGet(
        Get[AddressAndTestResult](WrappedTestConfiguration(config))
        for config in configs_with_sources
    )

    did_any_fail = False
    for result in results:
        if result.test_result.status == Status.FAILURE:
            did_any_fail = True
        if result.test_result.stdout:
            console.write_stdout(
                f"{result.address.reference()} stdout:\n{result.test_result.stdout}\n"
            )
        if result.test_result.stderr:
            # NB: we write to stdout, rather than to stderr, to avoid potential issues interleaving
            # the two streams.
            console.write_stdout(
                f"{result.address.reference()} stderr:\n{result.test_result.stderr}\n"
            )

    console.write_stdout("\n")

    for result in results:
        console.print_stdout(
            f"{result.address.reference():80}.....{result.test_result.status.value:>10}"
        )

    if did_any_fail:
        console.print_stderr(console.red("\nTests failed"))
        exit_code = PANTS_FAILED_EXIT_CODE
    else:
        exit_code = PANTS_SUCCEEDED_EXIT_CODE

    if options.values.run_coverage:
        all_coverage_data: Iterable[CoverageData] = [
            result.test_result.coverage_data
            for result in results
            if result.test_result.coverage_data is not None
        ]

        coverage_types_to_collection_types: Dict[
            Type[CoverageData], Type[CoverageDataCollection]
        ] = {
            collection_cls.element_type: collection_cls
            for collection_cls in union_membership.union_rules[CoverageDataCollection]
        }
        coverage_collections: List[CoverageDataCollection] = []
        for data_cls, data in itertools.groupby(all_coverage_data, lambda data: type(data)):
            collection_cls = coverage_types_to_collection_types[data_cls]
            coverage_collections.append(collection_cls(data))

        coverage_reports = await MultiGet(
            Get[CoverageReport](CoverageDataCollection, coverage_collection)
            for coverage_collection in coverage_collections
        )

        coverage_report_files = []
        for report in coverage_reports:
            report_file = report.materialize(console, workspace)
            if report_file is not None:
                coverage_report_files.append(report_file)

        if coverage_report_files and options.values.open_coverage:
            desktop.ui_open(console, interactive_runner, coverage_report_files)

    return Test(exit_code)


@rule
async def coordinator_of_tests(wrapped_config: WrappedTestConfiguration) -> AddressAndTestResult:
    config = wrapped_config.config

    # TODO(#6004): when streaming to live TTY, rely on V2 UI for this information. When not a
    # live TTY, periodically dump heavy hitters to stderr. See
    # https://github.com/pantsbuild/pants/issues/6004#issuecomment-492699898.
    logger.info(f"Starting tests: {config.address.reference()}")
    result = await Get[TestResult](TestConfiguration, config)
    logger.info(
        f"Tests {'succeeded' if result.status == Status.SUCCESS else 'failed'}: "
        f"{config.address.reference()}"
    )
    return AddressAndTestResult(config.address, result)


def rules():
    return [coordinator_of_tests, run_tests]
