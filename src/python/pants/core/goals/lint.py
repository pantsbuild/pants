# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, TypeVar, cast, final

from pants.base.specs import Specs
from pants.core.environments.rules import _warn_on_non_local_environments
from pants.core.goals.multi_tool_goal_helper import (
    BatchSizeOption,
    OnlyOption,
    SkippableSubsystem,
    determine_specified_tool_ids,
)
from pants.core.util_rules.partitions import PartitionElementT, PartitionerType, PartitionMetadataT
from pants.core.util_rules.partitions import Partitions as Partitions  # re-export
from pants.core.util_rules.partitions import (
    _BatchBase,
    _PartitionFieldSetsRequestBase,
    _PartitionFilesRequestBase,
)
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.graph import filter_targets
from pants.engine.internals.specs_rules import resolve_specs_paths
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.option_types import BoolOption
from pants.util.docutil import bin_name, doc_url
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
    def noop(cls) -> "LintResult":
        """Return a LintResult representing a skipped/no-op run.

        This mirrors semantics used across other goals (e.g. fmt/fix) where a tool run is
        intentionally skipped or there are no applicable files. We suppress rendering in the
        console to avoid noisy empty output.
        """
        return cls(
            exit_code=0,
            stdout="",
            stderr="",
            linter_name="",
            partition_description=None,
            report=EMPTY_DIGEST,
            _render_message=False,
        )

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
    help = softwrap(
        f"""
        Run linters/formatters/fixers in check mode.

        This goal runs tools that check code quality/styling etc, without changing that code. This
        includes running formatters and fixers, but instead of writing changes back to the
        workspace, Pants treats any changes they would make as a linting failure.

        See also:

        - [The `fmt` goal]({doc_url("reference/goals/fix")} will save the the result of formatters
          (code-editing tools that make only "syntactic" changes) back to the workspace.

        - [The `fmt` goal]({doc_url("reference/goals/fix")} will save the the result of fixers
          (code-editing tools that may make "semantic" changes too) back to the workspace.

        - Documentation about linters for various ecosystems, such as:
          [Python]({doc_url("docs/python/overview/linters-and-formatters")}), [Go]({doc_url("docs/go")}),
          [JVM]({doc_url("jvm/java-and-scala#lint-and-format")}), [Shell]({doc_url("docs/shell")}),
          [Docker]({doc_url("docs/docker#linting-dockerfiles-with-hadolint")}).

        """
    )

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


_CoreRequestType = TypeVar("_CoreRequestType", bound=AbstractLintRequest)
_TargetPartitioner = TypeVar("_TargetPartitioner", bound=LintTargetsRequest.PartitionRequest)
_FilePartitioner = TypeVar("_FilePartitioner", bound=LintFilesRequest.PartitionRequest)


class _MultiToolGoalSubsystem(Protocol):
    name: str
    only: OnlyOption


async def get_partitions_by_request_type(
    core_request_types: Iterable[type[_CoreRequestType]],
    target_partitioners: Iterable[type[_TargetPartitioner]],
    file_partitioners: Iterable[type[_FilePartitioner]],
    subsystem: _MultiToolGoalSubsystem,
    specs: Specs,
    # NB: Because the rule parser code will collect rule calls from caller's scope, these allow the
    # caller to customize the specific rule.
    make_targets_partition_request: Callable[[_TargetPartitioner], Coroutine[Any, Any, Partitions]],
    make_files_partition_request: Callable[[_FilePartitioner], Coroutine[Any, Any, Partitions]],
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

    _get_targets = filter_targets(
        **implicitly({(specs if target_partitioners else Specs.empty()): Specs})
    )
    _get_specs_paths = resolve_specs_paths(specs if file_partitioners else Specs.empty())

    targets, specs_paths = await concurrently(_get_targets, _get_specs_paths)

    await _warn_on_non_local_environments(targets, f"the {subsystem.name} goal")

    def partition_request_get(
        request_type: type[AbstractLintRequest],
    ) -> Coroutine[Any, Any, Partitions]:
        partition_request_type: type = getattr(request_type, "PartitionRequest")
        if partition_request_type in target_partitioners:
            partition_targets_type = cast(LintTargetsRequest, request_type)
            field_set_type = partition_targets_type.field_set_type
            field_sets = tuple(
                field_set_type.create(target)
                for target in targets
                if field_set_type.is_applicable(target)
            )
            return make_targets_partition_request(
                partition_targets_type.PartitionRequest(field_sets)  # type: ignore[arg-type]
            )
        else:
            assert partition_request_type in file_partitioners
            partition_files_type = cast(LintFilesRequest, request_type)
            return make_files_partition_request(
                partition_files_type.PartitionRequest(specs_paths.files)  # type: ignore[arg-type]
            )

    all_partitions = await concurrently(
        partition_request_get(request_type) for request_type in filtered_core_request_types
    )
    partitions_by_request_type = defaultdict(list)
    for request_type, partition in zip(filtered_core_request_types, all_partitions):
        partitions_by_request_type[request_type].append(partition)

    return partitions_by_request_type


@rule(polymorphic=True)
async def partition_targets(req: LintTargetsRequest.PartitionRequest) -> Partitions:
    raise NotImplementedError()


@rule(polymorphic=True)
async def partition_files(req: LintFilesRequest.PartitionRequest) -> Partitions:
    raise NotImplementedError()


@rule(polymorphic=True)
async def lint_batch(batch: AbstractLintRequest.Batch) -> LintResult:
    raise NotImplementedError()


def rules():
    return collect_rules()
