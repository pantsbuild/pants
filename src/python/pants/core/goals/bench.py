# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, ClassVar, Iterable, TypeVar, cast

from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import SingleEnvironmentNameRequest
from pants.core.util_rules.partitions import (
    PartitionerType,
    PartitionMetadataT,
    Partitions,
    _BatchBase,
    _PartitionFieldSetsRequestBase,
)
from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import EMPTY_FILE_DIGEST, Digest, FileDigest, MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.session import RunId
from pants.engine.process import FallibleProcessResult, ProcessResultMetadata
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSet,
    IntField,
    NoApplicableTargetsBehavior,
    SourcesField,
    StringField,
    StringSequenceField,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    ValidNumbers,
    parse_shard_spec,
)
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.option_types import BoolOption, EnumOption, IntOption, StrListOption, StrOption
from pants.util.collections import partition_sequentially
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import help_text, softwrap


@dataclass(frozen=True)
class BenchmarkResult(EngineAwareReturnType):
    exit_code: int | None
    stdout: str
    stdout_digest: FileDigest
    stderr: str
    stderr_digest: FileDigest
    address: Address
    output_setting: ShowOutput
    result_metadata: ProcessResultMetadata | None

    reports: Snapshot | None = None

    @classmethod
    def skip(cls, address: Address, output_setting: ShowOutput) -> BenchmarkResult:
        return cls(
            exit_code=None,
            stdout="",
            stderr="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            address=address,
            output_setting=output_setting,
            result_metadata=None,
        )

    @classmethod
    def from_fallible_process_result(
        cls,
        process_result: FallibleProcessResult,
        address: Address,
        output_setting: ShowOutput,
        *,
        reports: Snapshot | None = None,
    ) -> BenchmarkResult:
        return cls(
            exit_code=process_result.exit_code,
            stdout=process_result.stdout.decode(),
            stdout_digest=process_result.stdout_digest,
            stderr=process_result.stderr.decode(),
            stderr_digest=process_result.stderr_digest,
            address=address,
            output_setting=output_setting,
            reports=reports,
            result_metadata=process_result.metadata,
        )

    @property
    def skipped(self) -> bool:
        return self.exit_code is None and not self.stdout and not self.stderr

    def __lt__(self, other: Any) -> bool:
        """We sort first by status (skipped vs failed vs succeeded), then alphanumerically within
        each group."""

        if not isinstance(other, BenchmarkResult):
            return NotImplemented
        if self.exit_code == other.exit_code:
            return self.address.spec < other.address.spec
        if self.exit_code is None:
            return True
        if other.exit_code is None:
            return False
        return abs(self.exit_code) < abs(other.exit_code)

    def artifacts(self) -> dict[str, FileDigest | Snapshot]:
        output: dict[str, FileDigest | Snapshot] = {
            "stdout": self.stdout_digest,
            "stderr": self.stderr_digest,
        }
        return output

    def level(self) -> LogLevel:
        if self.skipped:
            return LogLevel.DEBUG
        return LogLevel.INFO if self.exit_code == 0 else LogLevel.ERROR

    def message(self) -> str:
        if self.skipped:
            return f"{self.address} skipped"

        status = "succeeded" if self.exit_code == 0 else f"failed (exit code {self.exit_code})"
        message = f"{self.address} {status}"
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
    """Which benchmarks to emit output for."""

    ALL = "all"
    FAILED = "failed"
    NONE = "none"


@union
@dataclass(frozen=True)
class BenchmarkFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to run benchmarks on a target."""

    sources: SourcesField


_BenchmarkFieldSetT = TypeVar("_BenchmarkFieldSetT", bound=BenchmarkFieldSet)


@union
class BenchmarkRequest:
    """Base class for plugin types wanting to be run as part of `bench`.

    Plugins should define a new type which subclasses this type, and set the
    appropriate class variables.
    E.g.
        class DryCleaningRequest(BenchmarkRequest):
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
    field_set_type: ClassVar[type[BenchmarkFieldSet]]
    partitioner_type: ClassVar[PartitionerType] = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT

    @classproperty
    def tool_name(cls) -> str:
        return cls.tool_subsystem.options_scope

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    class PartitionRequest(_PartitionFieldSetsRequestBase[_BenchmarkFieldSetT]):
        def metadata(self) -> dict[str, Any]:
            return {"addresses": [field_set.address.spec for field_set in self.field_sets]}

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    class Batch(_BatchBase[_BenchmarkFieldSetT, PartitionMetadataT]):
        @property
        def single_element(self) -> _BenchmarkFieldSetT:
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
                return f"benchmark batch from partition '{self.partition_metadata.description}'"
            return "benchmark batch"

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

        yield UnionRule(BenchmarkFieldSet, cls.field_set_type)
        yield UnionRule(BenchmarkRequest, cls)
        yield UnionRule(BenchmarkRequest.PartitionRequest, cls.PartitionRequest)
        yield UnionRule(BenchmarkRequest.Batch, cls.Batch)


class BenchmarkSubsystem(GoalSubsystem):
    name = "bench"
    help = "Run benchmarks"

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return BenchmarkRequest in union_membership

    class EnvironmentAware:
        extra_env_vars = StrListOption(
            help=softwrap(
                """
                Additional environment variables to include in benchmark processes.
                Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
                `ENV_VAR` to copy the value of a variable in Pants's own environment.
                """
            ),
        )

    force = BoolOption(
        "--force",
        default=False,
        help="Force the benchmarks to run, even if they could be satisfied from cache.",
    )
    output = EnumOption(
        "--output", default=ShowOutput.FAILED, help="Show stdout/stderr for these benchmarks."
    )
    report = BoolOption(
        default=False, advanced=True, help="Write benchmark reports to --report-dir."
    )
    default_report_path = str(PurePath("{distdir}", "bench", "reports"))
    _report_dir = StrOption(
        default=default_report_path,
        advanced=True,
        help="Path to write benchmark reports to. Must be relative to the build root.",
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
            For example, you can run three shards with --shard=0/3, --shard=1/3, --shard=2/3.

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
            Enable benchmark target timeouts. If timeouts are enabled then benchmark targets
            with a `timeout=` parameter set on their target will time out after the given number
            of seconds if not completed. If no timeout is set, then either the default timeout
            is used or no timeout is configured.
            """
        ),
    )
    timeout_default = IntOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            The default timeout (in seconds) for a benchmark target if the `timeout` field is not
            set on the target.
            """
        ),
    )
    timeout_maximum = IntOption(
        default=None,
        advanced=True,
        help="The maximum timeout (in seconds) that may be used on a benchmark target.",
    )
    batch_size = IntOption(
        "--batch-size",
        default=128,
        advanced=True,
        help=softwrap(
            """
            The target maximum number of files to be included in each run of batch-enabled
            benchmark runners.

            Some benchmark runners can execute benchmarks from multiple files in a single run. Benchmark
            implementations will return all benchmarks that _can_ run together as a single group -
            and then this may be further divided into smaller batches, based on this option.
            This is done:

                1. to avoid OS argument length limits (in processes which don't support argument files)
                2. to support more stable cache keys than would be possible if all files were operated \
                    on in a single batch
                3. to allow for parallelism in benchmark runners which don't have internal \
                    parallelism, or -- if they do support internal parallelism -- to improve scheduling \
                    behavior when multiple processes are competing for cores and so internal parallelism \
                    cannot be used perfectly

            In order to improve cache hit rates (see 2.), batches are created at stable boundaries,
            and so this value is only a "target" max batch size (rather than an exact value).

            NOTE: This parameter has no effect on benchmark runners/plugins that do not implement support
            for batched benchmarking.
            """
        ),
    )

    def report_dir(self, distdir: DistDir) -> PurePath:
        return PurePath(self._report_dir.format(distdir=distdir.relpath))


@dataclass(frozen=True)
class Benchmark(Goal):
    subsystem_cls = BenchmarkSubsystem
    environment_behavior = Goal.EnvironmentBehavior.USES_ENVIRONMENTS


class BenchmarkTimeoutField(IntField, metaclass=ABCMeta):
    """Base field class for implementing timeouts for benchmark targets.

    Each benchmark target that wants to implement a timeout needs to provide with its own concrete
    field class extending this one.
    """

    alias = "timeout"
    required = False
    valid_numbers = ValidNumbers.positive_only
    help = help_text(
        """
        A timeout (in seconds) used by each benchmark belonging to this target.

        If unset, will default to `[bench].timeout_default`; if that option is also unset,
        then the test will never time out. Will never exceed `[bench].timeout_maximum`. Only
        applies if the option `--bench-timeouts` is set to true (the default).
        """
    )

    def calculate_from_global_options(self, bench: BenchmarkSubsystem) -> int | None:
        if not bench.timeouts:
            return None
        if self.value is None:
            if bench.timeout_default is None:
                return None
            result = bench.timeout_default
        else:
            result = self.value
        if bench.timeout_maximum is not None:
            return min(result, bench.timeout_maximum)
        return result


class BenchmarkExtraEnvVarsField(StringSequenceField, metaclass=ABCMeta):
    alias = "extra_env_vars"
    help = help_text(
        """
         Additional environment variables to include in benchmark processes.

         Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
         `ENV_VAR` to copy the value of a variable in Pants's own environment.

         This will be merged with and override values from `[bench].extra_env_vars`.
        """
    )

    def sorted(self) -> tuple[str, ...]:
        return tuple(sorted(self.value or ()))


class BenchmarkBatchCompatibilityTagField(StringField, metaclass=ABCMeta):
    alias = "batch_compatibility_tag"

    @classmethod
    def format_help(cls, target_name: str, bench_runner_name: str) -> str:
        return f"""
        An arbitrary value used to mark the benchmark files belonging to this target as valid for
        batched execution.

        It's _sometimes_ safe to run multiple `{target_name}`s within a single test runner process,
        and doing so can give significant wins by allowing reuse of expensive test setup /
        teardown logic. To opt into this behavior, set this field to an arbitrary non-empty
        string on all the `{target_name}` targets that are safe/compatible to run in the same
        process.

        If this field is left unset on a target, the target is assumed to be incompatible with
        all others and will run in a dedicated `{bench_runner_name}` process.

        If this field is set on a target, and its value is different from the value on some
        other test `{target_name}`, then the two targets are explicitly incompatible and are guaranteed
        to not run in the same `{bench_runner_name}` process.

        If this field is set on a target, and its value is the same as the value on some other
        `{target_name}`, then the two targets are explicitly compatible and _may_ run in the same
        test runner process. Compatible tests may not end up in the same test runner batch if:

            * There are "too many" compatible tests in a partition, as determined by the \
                `[bench].batch_size` config parameter, or
            * Compatible tests have some incompatibility in Pants metadata (i.e. different \
                `resolve`s or `extra_env_vars`).

        When tests with the same `batch_compatibility_tag` have incompatibilities in some other
        Pants metadata, they will be automatically split into separate batches. This way you can
        set a high-level `batch_compatibility_tag` using `__defaults__` and then have tests
        continue to work as you tweak BUILD metadata on specific targets.
        """


_SOURCE_MAP = {
    ProcessResultMetadata.Source.MEMOIZED: "memoized",
    ProcessResultMetadata.Source.RAN: "ran",
    ProcessResultMetadata.Source.HIT_LOCALLY: "cached locally",
    ProcessResultMetadata.Source.HIT_REMOTELY: "cached remotely",
}


async def _get_benchmark_batches(
    core_request_types: Iterable[type[BenchmarkRequest]],
    targets_to_field_sets: TargetRootsToFieldSets,
    local_environment_name: ChosenLocalEnvironmentName,
    bench_subsystem: BenchmarkSubsystem,
) -> list[BenchmarkRequest.Batch]:
    def partitions_get(request_type: type[BenchmarkRequest]) -> Get[Partitions]:
        partition_type = cast(BenchmarkRequest, request_type)
        field_set_type = partition_type.field_set_type
        applicable_field_sets: list[BenchmarkFieldSet] = []
        for target, field_sets in targets_to_field_sets.mapping.items():
            if field_set_type.is_applicable(target):
                applicable_field_sets.extend(field_sets)

        partition_request = partition_type.PartitionRequest(tuple(applicable_field_sets))
        return Get(
            Partitions,
            {
                partition_request: BenchmarkRequest.PartitionRequest,
                local_environment_name.val: EnvironmentName,
            },
        )

    all_partitions = await MultiGet(
        partitions_get(request_type) for request_type in core_request_types
    )

    return [
        request_type.Batch(
            cast(BenchmarkRequest, request_type).tool_name, tuple(batch), partition.metadata
        )
        for request_type, partitions in zip(core_request_types, all_partitions)
        for partition in partitions
        for batch in partition_sequentially(
            partition.elements,
            key=lambda x: str(x.address) if isinstance(x, FieldSet) else str(x),
            size_target=bench_subsystem.batch_size,
            size_max=2 * bench_subsystem.batch_size,
        )
    ]


@goal_rule
async def run_bench(
    console: Console,
    bench_subsystem: BenchmarkSubsystem,
    union_membership: UnionMembership,
    run_id: RunId,
    distdir: DistDir,
    workspace: Workspace,
    local_environment_name: ChosenLocalEnvironmentName,
) -> Benchmark:
    shard, num_shards = parse_shard_spec(bench_subsystem.shard, "the [bench].shard option")
    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            BenchmarkFieldSet,
            goal_description=f"the {bench_subsystem.name} goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.warn,
            shard=shard,
            num_shards=num_shards,
        ),
    )

    request_types = union_membership.get(BenchmarkRequest)
    bench_batches = await _get_benchmark_batches(
        request_types, targets_to_valid_field_sets, local_environment_name, bench_subsystem
    )

    environment_names = await MultiGet(
        Get(
            EnvironmentName,
            SingleEnvironmentNameRequest,
            SingleEnvironmentNameRequest.from_field_sets(batch.elements, batch.description),
        )
        for batch in bench_batches
    )

    results = await MultiGet(
        Get(BenchmarkResult, {batch: BenchmarkRequest.Batch, environment_name: EnvironmentName})
        for batch, environment_name in zip(bench_batches, environment_names)
    )

    exit_code = 0
    if results:
        console.print_stderr("")
    for result in sorted(results):
        if result.exit_code != 0:
            exit_code = cast(int, result.exit_code)

        console.print_stderr(_format_bench_summary(result, run_id, console))

    if bench_subsystem.report:
        report_dir = bench_subsystem.report_dir(distdir)
        merged_reports = await Get(
            Digest, MergeDigests(result.reports.digest for result in results if result.reports)
        )
        workspace.write_digest(merged_reports, path_prefix=str(report_dir))
        console.print_stderr(f"\nWrote benchmark reports to {report_dir}")

    return Benchmark(exit_code)


def _format_bench_summary(result: BenchmarkResult, run_id: RunId, console: Console) -> str:
    """Format the benchmark summary printed to the console."""

    if result.result_metadata:
        if result.exit_code == 0:
            sigil = console.sigil_succeeded()
            status = "succeeded"
        else:
            sigil = console.sigil_failed()
            status = "failed"

        source = _SOURCE_MAP.get(result.result_metadata.source(run_id))
        source_print = f"({source})" if source else ""

        elapsed_print = ""
        total_elapsed_ms = result.result_metadata.total_elapsed_ms
        if total_elapsed_ms is not None:
            elapsed_secs = total_elapsed_ms / 1000
            elapsed_print = f"in {elapsed_secs:.2f}s"

        suffix = f"{elapsed_print} {source_print}"
    else:
        sigil = console.sigil_skipped()
        status = "skipped"
        suffix = ""

    return f"{sigil} {result.address} {status} {suffix}"


@dataclass(frozen=True)
class BenchmarkExtraEnv:
    env: EnvironmentVars


@rule
async def get_filtered_environment(
    test_env_aware: BenchmarkSubsystem.EnvironmentAware,
) -> BenchmarkExtraEnv:
    return BenchmarkExtraEnv(
        await Get(EnvironmentVars, EnvironmentVarsRequest(test_env_aware.extra_env_vars))
    )


def rules():
    return collect_rules()
