# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from abc import ABC, ABCMeta
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, ClassVar, Iterable, Optional, Sequence, TypeVar, cast

from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.goals.package import BuiltPackage, EnvironmentAwarePackageRequest, PackageFieldSet
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import (
    ChosenLocalEnvironmentName,
    EnvironmentName,
    SingleEnvironmentNameRequest,
)
from pants.core.util_rules.partitions import (
    PartitionerType,
    PartitionMetadataT,
    Partitions,
    _BatchBase,
    _PartitionFieldSetsRequestBase,
)
from pants.engine.addresses import Address, UnparsedAddressInputs
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.desktop import OpenFiles, OpenFilesRequest
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import EMPTY_FILE_DIGEST, Digest, FileDigest, MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.session import RunId
from pants.engine.process import (
    FallibleProcessResult,
    InteractiveProcess,
    InteractiveProcessResult,
    ProcessResultMetadata,
)
from pants.engine.rules import Effect, Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    IntField,
    NoApplicableTargetsBehavior,
    SourcesField,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
    ValidNumbers,
    parse_shard_spec,
)
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.option_types import BoolOption, EnumOption, IntOption, StrListOption, StrOption
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.meta import classproperty
from pants.util.strutil import Simplifier, help_text, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TestResult(EngineAwareReturnType):
    # A None exit_code indicates a backend that performs its own test discovery/selection
    # (rather than delegating that to the underlying test tool), and discovered no tests.
    exit_code: int | None
    stdout_bytes: bytes
    stdout_digest: FileDigest
    stderr_bytes: bytes
    stderr_digest: FileDigest
    addresses: tuple[Address, ...]
    output_setting: ShowOutput
    # A None result_metadata indicates a backend that performs its own test discovery/selection
    # and either discovered no tests, or encounted an error, such as a compilation error, in
    # the attempt.
    result_metadata: ProcessResultMetadata | None
    partition_description: str | None = None

    coverage_data: CoverageData | None = None
    # TODO: Rename this to `reports`. There is no guarantee that every language will produce
    #  XML reports, or only XML reports.
    xml_results: Snapshot | None = None
    # Any extra output (such as from plugins) that the test runner was configured to output.
    extra_output: Snapshot | None = None
    # True if the core test rules should log that extra output was written.
    log_extra_output: bool = False

    output_simplifier: Simplifier = Simplifier()

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @staticmethod
    def no_tests_found(address: Address, output_setting: ShowOutput) -> TestResult:
        """Used when we do test discovery ourselves, and we didn't find any."""
        return TestResult(
            exit_code=None,
            stdout_bytes=b"",
            stderr_bytes=b"",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            addresses=(address,),
            output_setting=output_setting,
            result_metadata=None,
        )

    @staticmethod
    def no_tests_found_in_batch(
        batch: TestRequest.Batch[_TestFieldSetT, Any], output_setting: ShowOutput
    ) -> TestResult:
        """Used when we do test discovery ourselves, and we didn't find any."""
        return TestResult(
            exit_code=None,
            stdout_bytes=b"",
            stderr_bytes=b"",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            addresses=tuple(field_set.address for field_set in batch.elements),
            output_setting=output_setting,
            result_metadata=None,
            partition_description=batch.partition_metadata.description,
        )

    @staticmethod
    def from_fallible_process_result(
        process_result: FallibleProcessResult,
        address: Address,
        output_setting: ShowOutput,
        *,
        coverage_data: CoverageData | None = None,
        xml_results: Snapshot | None = None,
        extra_output: Snapshot | None = None,
        log_extra_output: bool = False,
        output_simplifier: Simplifier = Simplifier(),
    ) -> TestResult:
        return TestResult(
            exit_code=process_result.exit_code,
            stdout_bytes=process_result.stdout,
            stdout_digest=process_result.stdout_digest,
            stderr_bytes=process_result.stderr,
            stderr_digest=process_result.stderr_digest,
            addresses=(address,),
            output_setting=output_setting,
            result_metadata=process_result.metadata,
            coverage_data=coverage_data,
            xml_results=xml_results,
            extra_output=extra_output,
            log_extra_output=log_extra_output,
            output_simplifier=output_simplifier,
        )

    @staticmethod
    def from_batched_fallible_process_result(
        process_result: FallibleProcessResult,
        batch: TestRequest.Batch[_TestFieldSetT, Any],
        output_setting: ShowOutput,
        *,
        coverage_data: CoverageData | None = None,
        xml_results: Snapshot | None = None,
        extra_output: Snapshot | None = None,
        log_extra_output: bool = False,
        output_simplifier: Simplifier = Simplifier(),
    ) -> TestResult:
        return TestResult(
            exit_code=process_result.exit_code,
            stdout_bytes=process_result.stdout,
            stdout_digest=process_result.stdout_digest,
            stderr_bytes=process_result.stderr,
            stderr_digest=process_result.stderr_digest,
            addresses=tuple(field_set.address for field_set in batch.elements),
            output_setting=output_setting,
            result_metadata=process_result.metadata,
            coverage_data=coverage_data,
            xml_results=xml_results,
            extra_output=extra_output,
            log_extra_output=log_extra_output,
            output_simplifier=output_simplifier,
            partition_description=batch.partition_metadata.description,
        )

    @property
    def description(self) -> str:
        if len(self.addresses) == 1:
            return self.addresses[0].spec

        return f"{self.addresses[0].spec} and {len(self.addresses)-1} other files"

    @property
    def path_safe_description(self) -> str:
        if len(self.addresses) == 1:
            return self.addresses[0].path_safe_spec

        return f"{self.addresses[0].path_safe_spec}+{len(self.addresses)-1}"

    def __lt__(self, other: Any) -> bool:
        """We sort first by exit code, then alphanumerically within each group."""
        if not isinstance(other, TestResult):
            return NotImplemented
        if self.exit_code == other.exit_code:
            return self.description < other.description
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
        if self.exit_code is None:
            return LogLevel.DEBUG
        return LogLevel.INFO if self.exit_code == 0 else LogLevel.ERROR

    def _simplified_output(self, v: bytes) -> str:
        return self.output_simplifier.simplify(v.decode(errors="replace"))

    def message(self) -> str:
        if self.exit_code is None:
            return "no tests found."
        status = "succeeded" if self.exit_code == 0 else f"failed (exit code {self.exit_code})"
        message = f"{status}."
        if self.partition_description:
            message += f"\nPartition: {self.partition_description}"
        if self.output_setting == ShowOutput.NONE or (
            self.output_setting == ShowOutput.FAILED and self.exit_code == 0
        ):
            return message
        output = ""
        if self.stdout_bytes:
            output += f"\n{self._simplified_output(self.stdout_bytes)}"
        if self.stderr_bytes:
            output += f"\n{self._simplified_output(self.stderr_bytes)}"
        if output:
            output = f"{output.rstrip()}\n\n"
        return f"{message}{output}"

    def metadata(self) -> dict[str, Any]:
        return {"addresses": [address.spec for address in self.addresses]}

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
    process: InteractiveProcess

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False


class TestDebugAdapterRequest(TestDebugRequest):
    """Like TestDebugRequest, but launches the test process using the relevant Debug Adapter server.

    The process should be launched waiting for the client to connect.
    """


@union
@dataclass(frozen=True)
class TestFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to run tests on a target."""

    sources: SourcesField

    __test__ = False


_TestFieldSetT = TypeVar("_TestFieldSetT", bound=TestFieldSet)


@union
class TestRequest:
    """Base class for plugin types wanting to be run as part of `test`.

    Plugins should define a new type which subclasses this type, and set the
    appropriate class variables.
    E.g.
        class DryCleaningRequest(TestRequest):
            tool_subsystem = DryCleaningSubsystem
            field_set_type = DryCleaningFieldSet

    Then register the rules which tell Pants about your plugin.
    E.g.
        def rules():
            return [
                *collect_rules(),
                *DryCleaningRequest.rules(),
            ]
    """

    tool_subsystem: ClassVar[type[SkippableSubsystem]]
    field_set_type: ClassVar[type[TestFieldSet]]
    partitioner_type: ClassVar[PartitionerType] = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT

    supports_debug: ClassVar[bool] = False
    supports_debug_adapter: ClassVar[bool] = False

    __test__ = False

    @classproperty
    def tool_name(cls) -> str:
        return cls.tool_subsystem.options_scope

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    class PartitionRequest(_PartitionFieldSetsRequestBase[_TestFieldSetT]):
        def metadata(self) -> dict[str, Any]:
            return {"addresses": [field_set.address.spec for field_set in self.field_sets]}

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    class Batch(_BatchBase[_TestFieldSetT, PartitionMetadataT]):
        @property
        def single_element(self) -> _TestFieldSetT:
            """Return the single element of this batch.

            NOTE: Accessing this property will raise a `TypeError` if this `Batch` contains
            >1 elements. It is only safe to be used by test runners utilizing the "default"
            one-input-per-partition partitioner type.
            """

            if len(self.elements) != 1:
                description = ""
                if self.partition_metadata.description:
                    description = f" from partition '{self.partition_metadata.description}'"
                raise TypeError(
                    f"Expected a single element in batch{description}, but found {len(self.elements)}"
                )

            return self.elements[0]

        @property
        def description(self) -> str:
            if self.partition_metadata and self.partition_metadata.description:
                return f"test batch from partition '{self.partition_metadata.description}'"
            return "test batch"

        def debug_hint(self) -> str:
            if len(self.elements) == 1:
                return self.elements[0].address.spec

            return f"{self.elements[0].address.spec} and {len(self.elements)-1} other files"

        def metadata(self) -> dict[str, Any]:
            return {
                "addresses": [field_set.address.spec for field_set in self.elements],
                "partition_description": self.partition_metadata.description,
            }

    @classmethod
    def rules(cls) -> Iterable:
        yield from cls.partitioner_type.default_rules(cls, by_file=False)

        yield UnionRule(TestFieldSet, cls.field_set_type)
        yield UnionRule(TestRequest, cls)
        yield UnionRule(TestRequest.PartitionRequest, cls.PartitionRequest)
        yield UnionRule(TestRequest.Batch, cls.Batch)

        if not cls.supports_debug:
            yield from _unsupported_debug_rules(cls)

        if not cls.supports_debug_adapter:
            yield from _unsupported_debug_adapter_rules(cls)


class CoverageData(ABC):
    """Base class for inputs to a coverage report.

    Subclasses should add whichever fields they require - snapshots of coverage output, XML files,
    etc.
    """


_CD = TypeVar("_CD", bound=CoverageData)


@union(in_scope_types=[EnvironmentName])
class CoverageDataCollection(Collection[_CD]):
    element_type: ClassVar[type[_CD]]  # type: ignore[misc]


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

    # Prevent this class from being detected by pytest as a test class.
    __test__ = False

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return TestRequest in union_membership

    class EnvironmentAware:
        extra_env_vars = StrListOption(
            help=softwrap(
                """
                Additional environment variables to include in test processes.
                Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
                `ENV_VAR` to copy the value of a variable in Pants's own environment.
                """
            ),
        )

    debug = BoolOption(
        default=False,
        help=softwrap(
            """
            Run tests sequentially in an interactive process. This is necessary, for
            example, when you add breakpoints to your code.
            """
        ),
    )
    # See also `run.py`'s same option
    debug_adapter = BoolOption(
        default=False,
        help=softwrap(
            """
            Run tests sequentially in an interactive process, using a Debug Adapter
            (https://microsoft.github.io/debug-adapter-protocol/) for the language if supported.

            The interactive process used will be immediately blocked waiting for a client before
            continuing.

            This option implies `--debug`.
            """
        ),
    )
    force = BoolOption(
        default=False,
        help="Force the tests to run, even if they could be satisfied from cache.",
    )
    output = EnumOption(
        default=ShowOutput.FAILED,
        help="Show stdout/stderr for these tests.",
    )
    use_coverage = BoolOption(
        default=False,
        help="Generate a coverage report if the test runner supports it.",
    )
    open_coverage = BoolOption(
        default=False,
        help=softwrap(
            """
            If a coverage report file is generated, open it on the local system if the
            system supports this.
            """
        ),
    )
    report = BoolOption(default=False, advanced=True, help="Write test reports to `--report-dir`.")
    default_report_path = str(PurePath("{distdir}", "test", "reports"))
    _report_dir = StrOption(
        default=default_report_path,
        advanced=True,
        help="Path to write test reports to. Must be relative to the build root.",
    )
    shard = StrOption(
        default="",
        help=softwrap(
            """
            A shard specification of the form "k/N", where N is a positive integer and k is a
            non-negative integer less than N.

            If set, the request input targets will be deterministically partitioned into N disjoint
            subsets of roughly equal size, and only the k'th subset will be used, with all others
            discarded.

            Useful for splitting large numbers of test files across multiple machines in CI.
            For example, you can run three shards with `--shard=0/3`, `--shard=1/3`, `--shard=2/3`.

            Note that the shards are roughly equal in size as measured by number of files.
            No attempt is made to consider the size of different files, the time they have
            taken to run in the past, or other such sophisticated measures.
            """
        ),
    )
    timeouts = BoolOption(
        default=True,
        help=softwrap(
            """
            Enable test target timeouts. If timeouts are enabled then test targets with a
            `timeout=` parameter set on their target will time out after the given number of
            seconds if not completed. If no timeout is set, then either the default timeout
            is used or no timeout is configured.
            """
        ),
    )
    timeout_default = IntOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            The default timeout (in seconds) for a test target if the `timeout` field is not
            set on the target.
            """
        ),
    )
    timeout_maximum = IntOption(
        default=None,
        advanced=True,
        help="The maximum timeout (in seconds) that may be used on a test target.",
    )
    batch_size = IntOption(
        "--batch-size",
        default=128,
        advanced=True,
        help=softwrap(
            """
            The target maximum number of files to be included in each run of batch-enabled
            test runners.

            Some test runners can execute tests from multiple files in a single run. Test
            implementations will return all tests that _can_ run together as a single group -
            and then this may be further divided into smaller batches, based on this option.
            This is done:

              1. to avoid OS argument length limits (in processes which don't support argument files)
              2. to support more stable cache keys than would be possible if all files were operated \
                 on in a single batch
              3. to allow for parallelism in test runners which don't have internal \
                 parallelism, or -- if they do support internal parallelism -- to improve scheduling \
                 behavior when multiple processes are competing for cores and so internal parallelism \
                 cannot be used perfectly

            In order to improve cache hit rates (see 2.), batches are created at stable boundaries,
            and so this value is only a "target" max batch size (rather than an exact value).

            NOTE: This parameter has no effect on test runners/plugins that do not implement support
            for batched testing.
            """
        ),
    )

    def report_dir(self, distdir: DistDir) -> PurePath:
        return PurePath(self._report_dir.format(distdir=distdir.relpath))


class Test(Goal):
    subsystem_cls = TestSubsystem
    environment_behavior = Goal.EnvironmentBehavior.USES_ENVIRONMENTS

    __test__ = False


class TestTimeoutField(IntField, metaclass=ABCMeta):
    """Base field class for implementing timeouts for test targets.

    Each test target that wants to implement a timeout needs to provide with its own concrete field
    class extending this one.
    """

    alias = "timeout"
    required = False
    valid_numbers = ValidNumbers.positive_only
    help = help_text(
        """
        A timeout (in seconds) used by each test file belonging to this target.

        If unset, will default to `[test].timeout_default`; if that option is also unset,
        then the test will never time out. Will never exceed `[test].timeout_maximum`. Only
        applies if the option `--test-timeouts` is set to true (the default).
        """
    )

    def calculate_from_global_options(self, test: TestSubsystem) -> Optional[int]:
        if not test.timeouts:
            return None
        if self.value is None:
            if test.timeout_default is None:
                return None
            result = test.timeout_default
        else:
            result = self.value
        if test.timeout_maximum is not None:
            return min(result, test.timeout_maximum)
        return result


class TestExtraEnvVarsField(StringSequenceField, metaclass=ABCMeta):
    alias = "extra_env_vars"
    help = help_text(
        """
         Additional environment variables to include in test processes.

         Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
         `ENV_VAR` to copy the value of a variable in Pants's own environment.

         This will be merged with and override values from `[test].extra_env_vars`.
        """
    )

    def sorted(self) -> tuple[str, ...]:
        return tuple(sorted(self.value or ()))


class TestsBatchCompatibilityTagField(StringField, metaclass=ABCMeta):
    alias = "batch_compatibility_tag"

    @classmethod
    def format_help(cls, target_name: str, test_runner_name: str) -> str:
        return f"""
        An arbitrary value used to mark the test files belonging to this target as valid for
        batched execution.

        It's _sometimes_ safe to run multiple `{target_name}`s within a single test runner process,
        and doing so can give significant wins by allowing reuse of expensive test setup /
        teardown logic. To opt into this behavior, set this field to an arbitrary non-empty
        string on all the `{target_name}` targets that are safe/compatible to run in the same
        process.

        If this field is left unset on a target, the target is assumed to be incompatible with
        all others and will run in a dedicated `{test_runner_name}` process.

        If this field is set on a target, and its value is different from the value on some
        other test `{target_name}`, then the two targets are explicitly incompatible and are guaranteed
        to not run in the same `{test_runner_name}` process.

        If this field is set on a target, and its value is the same as the value on some other
        `{target_name}`, then the two targets are explicitly compatible and _may_ run in the same
        test runner process. Compatible tests may not end up in the same test runner batch if:

          * There are "too many" compatible tests in a partition, as determined by the \
            `[test].batch_size` config parameter, or
          * Compatible tests have some incompatibility in Pants metadata (i.e. different \
            `resolve`s or `extra_env_vars`).

        When tests with the same `batch_compatibility_tag` have incompatibilities in some other
        Pants metadata, they will be automatically split into separate batches. This way you can
        set a high-level `batch_compatibility_tag` using `__defaults__` and then have tests
        continue to work as you tweak BUILD metadata on specific targets.
        """


async def _get_test_batches(
    core_request_types: Iterable[type[TestRequest]],
    targets_to_field_sets: TargetRootsToFieldSets,
    local_environment_name: ChosenLocalEnvironmentName,
    test_subsystem: TestSubsystem,
) -> list[TestRequest.Batch]:
    def partitions_get(request_type: type[TestRequest]) -> Get[Partitions]:
        partition_type = cast(TestRequest, request_type)
        field_set_type = partition_type.field_set_type
        applicable_field_sets: list[TestFieldSet] = []
        for target, field_sets in targets_to_field_sets.mapping.items():
            if field_set_type.is_applicable(target):
                applicable_field_sets.extend(field_sets)

        partition_request = partition_type.PartitionRequest(tuple(applicable_field_sets))
        return Get(
            Partitions,
            {
                partition_request: TestRequest.PartitionRequest,
                local_environment_name.val: EnvironmentName,
            },
        )

    all_partitions = await MultiGet(
        partitions_get(request_type) for request_type in core_request_types
    )

    return [
        request_type.Batch(
            cast(TestRequest, request_type).tool_name, tuple(batch), partition.metadata
        )
        for request_type, partitions in zip(core_request_types, all_partitions)
        for partition in partitions
        for batch in partition_sequentially(
            partition.elements,
            key=lambda x: str(x.address) if isinstance(x, FieldSet) else str(x),
            size_target=test_subsystem.batch_size,
            size_max=2 * test_subsystem.batch_size,
        )
    ]


async def _run_debug_tests(
    batches: Iterable[TestRequest.Batch],
    environment_names: Sequence[EnvironmentName],
    test_subsystem: TestSubsystem,
    debug_adapter: DebugAdapterSubsystem,
) -> Test:
    debug_requests = await MultiGet(
        (
            Get(
                TestDebugRequest,
                {batch: TestRequest.Batch, environment_name: EnvironmentName},
            )
            if not test_subsystem.debug_adapter
            else Get(
                TestDebugAdapterRequest,
                {batch: TestRequest.Batch, environment_name: EnvironmentName},
            )
        )
        for batch, environment_name in zip(batches, environment_names)
    )
    exit_code = 0
    for debug_request, environment_name in zip(debug_requests, environment_names):
        if test_subsystem.debug_adapter:
            logger.info(
                softwrap(
                    f"""
                    Launching debug adapter at '{debug_adapter.host}:{debug_adapter.port}',
                    which will wait for a client connection...
                    """
                )
            )

        debug_result = await Effect(
            InteractiveProcessResult,
            {
                debug_request.process: InteractiveProcess,
                environment_name: EnvironmentName,
            },
        )
        if debug_result.exit_code != 0:
            exit_code = debug_result.exit_code
    return Test(exit_code)


@goal_rule
async def run_tests(
    console: Console,
    test_subsystem: TestSubsystem,
    debug_adapter: DebugAdapterSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
    distdir: DistDir,
    run_id: RunId,
    local_environment_name: ChosenLocalEnvironmentName,
) -> Test:
    if test_subsystem.debug_adapter:
        goal_description = f"`{test_subsystem.name} --debug-adapter`"
        no_applicable_targets_behavior = NoApplicableTargetsBehavior.error
    elif test_subsystem.debug:
        goal_description = f"`{test_subsystem.name} --debug`"
        no_applicable_targets_behavior = NoApplicableTargetsBehavior.error
    else:
        goal_description = f"The `{test_subsystem.name}` goal"
        no_applicable_targets_behavior = NoApplicableTargetsBehavior.warn

    shard, num_shards = parse_shard_spec(test_subsystem.shard, "the [test].shard option")
    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            TestFieldSet,
            goal_description=goal_description,
            no_applicable_targets_behavior=no_applicable_targets_behavior,
            shard=shard,
            num_shards=num_shards,
        ),
    )

    request_types = union_membership.get(TestRequest)
    test_batches = await _get_test_batches(
        request_types,
        targets_to_valid_field_sets,
        local_environment_name,
        test_subsystem,
    )

    environment_names = await MultiGet(
        Get(
            EnvironmentName,
            SingleEnvironmentNameRequest,
            SingleEnvironmentNameRequest.from_field_sets(batch.elements, batch.description),
        )
        for batch in test_batches
    )

    if test_subsystem.debug or test_subsystem.debug_adapter:
        return await _run_debug_tests(
            test_batches, environment_names, test_subsystem, debug_adapter
        )

    results = await MultiGet(
        Get(TestResult, {batch: TestRequest.Batch, environment_name: EnvironmentName})
        for batch, environment_name in zip(test_batches, environment_names)
    )

    # Print summary.
    exit_code = 0
    if results:
        console.print_stderr("")
    for result in sorted(results):
        if result.exit_code is None:
            # We end up here, e.g., if we implemented test discovery and found no tests.
            continue
        if result.exit_code != 0:
            exit_code = result.exit_code
        if result.result_metadata is None:
            # We end up here, e.g., if compilation failed during self-implemented test discovery.
            continue

        console.print_stderr(_format_test_summary(result, run_id, console))

        if result.extra_output and result.extra_output.files:
            path_prefix = str(distdir.relpath / "test" / result.path_safe_description)
            workspace.write_digest(
                result.extra_output.digest,
                path_prefix=path_prefix,
            )
            if result.log_extra_output:
                logger.info(
                    f"Wrote extra output from test `{result.addresses[0]}` to `{path_prefix}`."
                )

    if test_subsystem.report:
        report_dir = test_subsystem.report_dir(distdir)
        merged_reports = await Get(
            Digest,
            MergeDigests(result.xml_results.digest for result in results if result.xml_results),
        )
        workspace.write_digest(merged_reports, path_prefix=str(report_dir))
        console.print_stderr(f"\nWrote test reports to {report_dir}")

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
            Get(
                CoverageReports,
                {
                    coverage_collection: CoverageDataCollection,
                    local_environment_name.val: EnvironmentName,
                },
            )
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
                _ = await Effect(
                    InteractiveProcessResult,
                    {process: InteractiveProcess, local_environment_name.val: EnvironmentName},
                )

        for coverage_reports in coverage_reports_collections:
            if coverage_reports.coverage_insufficient:
                logger.error(
                    softwrap(
                        """
                        Test goal failed due to insufficient coverage.
                        See coverage reports for details.
                        """
                    )
                )
                # coverage.py uses 2 to indicate failure due to insufficient coverage.
                # We may as well follow suit in the general case, for all languages.
                exit_code = 2

    return Test(exit_code)


_SOURCE_MAP = {
    ProcessResultMetadata.Source.MEMOIZED: "memoized",
    ProcessResultMetadata.Source.RAN: "ran",
    ProcessResultMetadata.Source.HIT_LOCALLY: "cached locally",
    ProcessResultMetadata.Source.HIT_REMOTELY: "cached remotely",
}


def _format_test_summary(result: TestResult, run_id: RunId, console: Console) -> str:
    """Format the test summary printed to the console."""
    assert (
        result.result_metadata is not None
    ), "Skipped test results should not be outputted in the test summary"
    if result.exit_code == 0:
        sigil = console.sigil_succeeded()
        status = "succeeded"
    else:
        sigil = console.sigil_failed()
        status = "failed"

    environment = result.result_metadata.execution_environment.name
    environment_type = result.result_metadata.execution_environment.environment_type
    source = result.result_metadata.source(run_id)
    source_str = _SOURCE_MAP[source]
    if environment:
        preposition = "in" if source == ProcessResultMetadata.Source.RAN else "for"
        source_desc = (
            f" ({source_str} {preposition} {environment_type} environment `{environment}`)"
        )
    elif source == ProcessResultMetadata.Source.RAN:
        source_desc = ""
    else:
        source_desc = f" ({source_str})"

    elapsed_print = ""
    total_elapsed_ms = result.result_metadata.total_elapsed_ms
    if total_elapsed_ms is not None:
        elapsed_secs = total_elapsed_ms / 1000
        elapsed_print = f"in {elapsed_secs:.2f}s"

    suffix = f" {elapsed_print}{source_desc}"
    return f"{sigil} {result.description} {status}{suffix}."


@dataclass(frozen=True)
class TestExtraEnv:
    env: EnvironmentVars


@rule
async def get_filtered_environment(test_env_aware: TestSubsystem.EnvironmentAware) -> TestExtraEnv:
    return TestExtraEnv(
        await Get(EnvironmentVars, EnvironmentVarsRequest(test_env_aware.extra_env_vars))
    )


@memoized
def _unsupported_debug_rules(cls: type[TestRequest]) -> Iterable:
    """Returns a rule that implements TestDebugRequest by raising an error."""

    @rule(canonical_name_suffix=cls.__name__, _param_type_overrides={"request": cls.Batch})
    async def get_test_debug_request(request: TestRequest.Batch) -> TestDebugRequest:
        raise NotImplementedError("Testing this target with --debug is not yet supported.")

    return collect_rules(locals())


@memoized
def _unsupported_debug_adapter_rules(cls: type[TestRequest]) -> Iterable:
    """Returns a rule that implements TestDebugAdapterRequest by raising an error."""

    @rule(canonical_name_suffix=cls.__name__, _param_type_overrides={"request": cls.Batch})
    async def get_test_debug_adapter_request(request: TestRequest.Batch) -> TestDebugAdapterRequest:
        raise NotImplementedError(
            "Testing this target type with a debug adapter is not yet supported."
        )

    return collect_rules(locals())


# -------------------------------------------------------------------------------------------
# `runtime_package_dependencies` field
# -------------------------------------------------------------------------------------------


class RuntimePackageDependenciesField(SpecialCasedDependencies):
    alias = "runtime_package_dependencies"
    help = help_text(
        f"""
        Addresses to targets that can be built with the `{bin_name()} package` goal and whose
        resulting artifacts should be included in the test run.

        Pants will build the artifacts as if you had run `{bin_name()} package`.
        It will include the results in your test's chroot, using the same name they would normally
        have, but without the `--distdir` prefix (e.g. `dist/`).

        You can include anything that can be built by `{bin_name()} package`, e.g. a `pex_binary`,
        `python_aws_lambda_function`, or an `archive`.
        """
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
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in field_sets_per_tgt.field_sets
    )
    return BuiltPackageDependencies(packages)


def rules():
    return [
        *collect_rules(),
    ]
