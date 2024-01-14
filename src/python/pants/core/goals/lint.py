# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Iterable, Iterator, Protocol, Sequence, TypeVar, cast

from typing_extensions import final

from pants.base.specs import Specs
from pants.core.goals.multi_tool_goal_helper import (
    BatchSizeOption,
    OnlyOption,
    SkippableSubsystem,
    determine_specified_tool_ids,
    write_reports,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import _warn_on_non_local_environments
from pants.core.util_rules.partitions import PartitionElementT, PartitionerType, PartitionMetadataT
from pants.core.util_rules.partitions import Partitions as Partitions  # re-export
from pants.core.util_rules.partitions import (
    _BatchBase,
    _PartitionFieldSetsRequestBase,
    _PartitionFilesRequestBase,
)
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, Digest, PathGlobs, SpecsPaths, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, FilteredTargets
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.option_types import BoolOption
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import Simplifier, softwrap

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_FieldSetT = TypeVar("_FieldSetT", bound=FieldSet)


@dataclass(frozen=True)
class LintResult(EngineAwareReturnType):
    exit_code: int
    stdout: str
    stderr: str
    linter_name: str
    partition_description: str | None = None
    report: Digest = EMPTY_DIGEST
    _render_message: bool = True

    @classmethod
    def create(
        cls,
        request: AbstractLintRequest.Batch,
        process_result: FallibleProcessResult,
        *,
        output_simplifier: Simplifier = Simplifier(),
        report: Digest = EMPTY_DIGEST,
    ) -> LintResult:
        return cls(
            exit_code=process_result.exit_code,
            stdout=output_simplifier.simplify(process_result.stdout),
            stderr=output_simplifier.simplify(process_result.stderr),
            linter_name=request.tool_name,
            partition_description=request.partition_metadata.description,
            report=report,
        )

    def metadata(self) -> dict[str, Any]:
        return {"partition": self.partition_description}

    def level(self) -> LogLevel | None:
        if not self._render_message:
            return LogLevel.TRACE
        if self.exit_code != 0:
            return LogLevel.ERROR
        return LogLevel.INFO

    def message(self) -> str | None:
        message = self.linter_name
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )
        if self.partition_description:
            message += f"\nPartition: {self.partition_description}"
        if self.stdout:
            message += f"\n{self.stdout}"
        if self.stderr:
            message += f"\n{self.stderr}"
        if self.partition_description or self.stdout or self.stderr:
            message += "\n\n"

        return message

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


@union
class AbstractLintRequest:
    """Base class for plugin types wanting to be run as part of `lint`.

    Plugins should define a new type which subclasses either `LintTargetsRequest` (to lint targets)
    or `LintFilesRequest` (to lint arbitrary files), and set the appropriate class variables.
    E.g.
        class DryCleaningRequest(LintTargetsRequest):
            name = DryCleaningSubsystem.options_scope
            field_set_type = DryCleaningFieldSet

    Then, define 2 `@rule`s:
        1. A rule which takes an instance of your request type's `PartitionRequest` class property,
            and returns a `Partitions` instance.
            E.g.
                @rule
                async def partition(
                    request: DryCleaningRequest.PartitionRequest[DryCleaningFieldSet]
                    # or `request: DryCleaningRequest.PartitionRequest` if file linter
                    subsystem: DryCleaningSubsystem,
                ) -> Partitions[DryCleaningFieldSet, Any]:
                    if subsystem.skip:
                        return Partitions()

                    # One possible implementation
                    return Partitions.single_partition(request.field_sets)

        2. A rule which takes an instance of your request type's `Batch` class property, and
            returns a `LintResult instance.
            E.g.
                @rule
                async def dry_clean(
                    request: DryCleaningRequest.Batch,
                ) -> LintResult:
                    ...

    Lastly, register the rules which tell Pants about your plugin.
    E.g.
        def rules():
            return [
                *collect_rules(),
                *DryCleaningRequest.rules()
            ]
    """

    tool_subsystem: ClassVar[type[SkippableSubsystem]]
    partitioner_type: ClassVar[PartitionerType] = PartitionerType.CUSTOM

    is_formatter: ClassVar[bool] = False
    is_fixer: ClassVar[bool] = False

    # Enables lint rules which run the formatter/fixer and check if it made changes.
    # If it did make changes shows an error. This makes sure the user didn't forget
    # to run the formatter/fixer.
    enable_lint_rules: ClassVar[bool] = True

    @final
    @classproperty
    def _requires_snapshot(cls) -> bool:
        return cls.is_formatter or cls.is_fixer

    @classproperty
    def tool_name(cls) -> str:
        """The user-facing "name" of the tool."""
        return cls.tool_subsystem.options_scope

    @classproperty
    def tool_id(cls) -> str:
        """The "id" of the tool, used in tool selection (Eg --only=<id>)."""
        return cls.tool_subsystem.options_scope

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    class Batch(_BatchBase[PartitionElementT, PartitionMetadataT]):
        pass

    @final
    @classmethod
    def rules(cls) -> Iterable:
        yield from cls._get_rules()

    @classmethod
    def _get_rules(cls) -> Iterable:
        if cls.enable_lint_rules:
            yield UnionRule(AbstractLintRequest, cls)
            yield UnionRule(AbstractLintRequest.Batch, cls.Batch)


class LintTargetsRequest(AbstractLintRequest):
    """The entry point for linters that operate on targets."""

    field_set_type: ClassVar[type[FieldSet]]

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    class PartitionRequest(_PartitionFieldSetsRequestBase[_FieldSetT]):
        pass

    @classmethod
    def _get_rules(cls) -> Iterable:
        yield from cls.partitioner_type.default_rules(cls, by_file=False)
        yield from super()._get_rules()
        yield UnionRule(LintTargetsRequest.PartitionRequest, cls.PartitionRequest)


class LintFilesRequest(AbstractLintRequest, EngineAwareParameter):
    """The entry point for linters that do not use targets."""

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    class PartitionRequest(_PartitionFilesRequestBase):
        pass

    @classmethod
    def _get_rules(cls) -> Iterable:
        if cls.partitioner_type is not PartitionerType.CUSTOM:
            raise ValueError(
                "Pants does not provide default partitioners for `LintFilesRequest`."
                + " You will need to provide your own partitioner rule."
            )

        yield from super()._get_rules()
        yield UnionRule(LintFilesRequest.PartitionRequest, cls.PartitionRequest)


# If a user wants linter reports to show up in dist/ they must ensure that the reports
# are written under this directory. E.g.,
# ./pants --flake8-args="--output-file=reports/report.txt" lint <target>
REPORT_DIR = "reports"


class LintSubsystem(GoalSubsystem):
    name = "lint"
    help = "Run linters/formatters/fixers in check mode."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return AbstractLintRequest in union_membership

    only = OnlyOption("linter", "flake8", "shellcheck")
    skip_formatters = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, skip running all formatters in check-only mode.

            FYI: when running `{bin_name()} fmt lint ::`, there should be diminishing performance
            benefit to using this flag. Pants attempts to reuse the results from `fmt` when running
            `lint` where possible.
            """
        ),
    )
    skip_fixers = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, skip running all fixers in check-only mode.

            FYI: when running `{bin_name()} fix lint ::`, there should be diminishing performance
            benefit to using this flag. Pants attempts to reuse the results from `fix` when running
            `lint` where possible.
            """
        ),
    )
    batch_size = BatchSizeOption(uppercase="Linter", lowercase="linter")


class Lint(Goal):
    subsystem_cls = LintSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


def _print_results(
    console: Console,
    results_by_tool: dict[str, list[LintResult]],
    formatter_failed: bool,
    fixer_failed: bool,
) -> None:
    if results_by_tool:
        console.print_stderr("")

    for tool_name in sorted(results_by_tool):
        results = results_by_tool[tool_name]
        if any(result.exit_code for result in results):
            sigil = console.sigil_failed()
            status = "failed"
        else:
            sigil = console.sigil_succeeded()
            status = "succeeded"
        console.print_stderr(f"{sigil} {tool_name} {status}.")

    if formatter_failed or fixer_failed:
        console.print_stderr("")

    if formatter_failed:
        console.print_stderr(f"(One or more formatters failed. Run `{bin_name()} fmt` to fix.)")

    if fixer_failed:
        console.print_stderr(f"(One or more fixers failed. Run `{bin_name()} fix` to fix.)")


def _get_error_code(results: Sequence[LintResult]) -> int:
    for result in reversed(results):
        if result.exit_code:
            return result.exit_code
    return 0


_CoreRequestType = TypeVar("_CoreRequestType", bound=AbstractLintRequest)
_TargetPartitioner = TypeVar("_TargetPartitioner", bound=LintTargetsRequest.PartitionRequest)
_FilePartitioner = TypeVar("_FilePartitioner", bound=LintFilesRequest.PartitionRequest)


class _MultiToolGoalSubsystem(Protocol):
    name: str
    only: OnlyOption


async def _get_partitions_by_request_type(
    core_request_types: Iterable[type[_CoreRequestType]],
    target_partitioners: Iterable[type[_TargetPartitioner]],
    file_partitioners: Iterable[type[_FilePartitioner]],
    subsystem: _MultiToolGoalSubsystem,
    specs: Specs,
    # NB: Because the rule parser code will collect `Get`s from caller's scope, these allows the
    # caller to customize the specific `Get`.
    make_targets_partition_request_get: Callable[[_TargetPartitioner], Get[Partitions]],
    make_files_partition_request_get: Callable[[_FilePartitioner], Get[Partitions]],
) -> dict[type[_CoreRequestType], list[Partitions]]:
    specified_ids = determine_specified_tool_ids(
        subsystem.name,
        subsystem.only,
        core_request_types,
    )

    filtered_core_request_types = [
        request_type for request_type in core_request_types if request_type.tool_id in specified_ids
    ]
    if not filtered_core_request_types:
        return {}

    core_partition_request_types = {
        getattr(request_type, "PartitionRequest") for request_type in filtered_core_request_types
    }
    target_partitioners = [
        target_partitioner
        for target_partitioner in target_partitioners
        if target_partitioner in core_partition_request_types
    ]
    file_partitioners = [
        file_partitioner
        for file_partitioner in file_partitioners
        if file_partitioner in core_partition_request_types
    ]

    _get_targets = Get(
        FilteredTargets,
        Specs,
        specs if target_partitioners else Specs.empty(),
    )
    _get_specs_paths = Get(SpecsPaths, Specs, specs if file_partitioners else Specs.empty())

    targets, specs_paths = await MultiGet(_get_targets, _get_specs_paths)

    await _warn_on_non_local_environments(targets, f"the {subsystem.name} goal")

    def partition_request_get(request_type: type[AbstractLintRequest]) -> Get[Partitions]:
        partition_request_type: type = getattr(request_type, "PartitionRequest")
        if partition_request_type in target_partitioners:
            partition_targets_type = cast(LintTargetsRequest, request_type)
            field_set_type = partition_targets_type.field_set_type
            field_sets = tuple(
                field_set_type.create(target)
                for target in targets
                if field_set_type.is_applicable(target)
            )
            return make_targets_partition_request_get(
                partition_targets_type.PartitionRequest(field_sets)  # type: ignore[arg-type]
            )
        else:
            assert partition_request_type in file_partitioners
            partition_files_type = cast(LintFilesRequest, request_type)
            return make_files_partition_request_get(
                partition_files_type.PartitionRequest(specs_paths.files)  # type: ignore[arg-type]
            )

    all_partitions = await MultiGet(
        partition_request_get(request_type) for request_type in filtered_core_request_types
    )
    partitions_by_request_type = defaultdict(list)
    for request_type, partition in zip(filtered_core_request_types, all_partitions):
        partitions_by_request_type[request_type].append(partition)

    return partitions_by_request_type


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    specs: Specs,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
    dist_dir: DistDir,
) -> Lint:
    lint_request_types = union_membership.get(AbstractLintRequest)
    target_partitioners = union_membership.get(LintTargetsRequest.PartitionRequest)
    file_partitioners = union_membership.get(LintFilesRequest.PartitionRequest)

    partitions_by_request_type = await _get_partitions_by_request_type(
        [
            request_type
            for request_type in lint_request_types
            if not (request_type.is_formatter and lint_subsystem.skip_formatters)
            and not (request_type.is_fixer and lint_subsystem.skip_fixers)
        ],
        target_partitioners,
        file_partitioners,
        lint_subsystem,
        specs,
        lambda request_type: Get(Partitions, LintTargetsRequest.PartitionRequest, request_type),
        lambda request_type: Get(Partitions, LintFilesRequest.PartitionRequest, request_type),
    )

    if not partitions_by_request_type:
        return Lint(exit_code=0)

    def batch_by_size(iterable: Iterable[_T]) -> Iterator[tuple[_T, ...]]:
        batches = partition_sequentially(
            iterable,
            key=lambda x: str(x.address) if isinstance(x, FieldSet) else str(x),
            size_target=lint_subsystem.batch_size,
            size_max=4 * lint_subsystem.batch_size,
        )
        for batch in batches:
            yield tuple(batch)

    lint_batches_by_request_type = {
        request_type: [
            (batch, partition.metadata)
            for partitions in partitions_list
            for partition in partitions
            for batch in batch_by_size(partition.elements)
        ]
        for request_type, partitions_list in partitions_by_request_type.items()
    }

    formatter_snapshots = await MultiGet(
        Get(Snapshot, PathGlobs(elements))
        for request_type, batch in lint_batches_by_request_type.items()
        for elements, _ in batch
        if request_type._requires_snapshot
    )
    snapshots_iter = iter(formatter_snapshots)

    batches: Iterable[AbstractLintRequest.Batch] = [
        request_type.Batch(
            request_type.tool_name,
            elements,
            key,
            **{"snapshot": next(snapshots_iter)} if request_type._requires_snapshot else {},
        )
        for request_type, batch in lint_batches_by_request_type.items()
        for elements, key in batch
    ]

    all_batch_results = await MultiGet(
        Get(LintResult, AbstractLintRequest.Batch, request) for request in batches
    )

    core_request_types_by_batch_type = {
        request_type.Batch: request_type for request_type in lint_request_types
    }

    formatter_failed = any(
        result.exit_code
        for batch, result in zip(batches, all_batch_results)
        if core_request_types_by_batch_type[type(batch)].is_formatter
    )

    fixer_failed = any(
        result.exit_code
        for batch, result in zip(batches, all_batch_results)
        if core_request_types_by_batch_type[type(batch)].is_fixer
    )

    results_by_tool = defaultdict(list)
    for result in all_batch_results:
        results_by_tool[result.linter_name].append(result)

    write_reports(
        results_by_tool,
        workspace,
        dist_dir,
        goal_name=LintSubsystem.name,
    )

    _print_results(
        console,
        results_by_tool,
        formatter_failed,
        fixer_failed,
    )
    return Lint(_get_error_code(all_batch_results))


def rules():
    return collect_rules()
