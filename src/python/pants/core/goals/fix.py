# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, NamedTuple, Protocol, TypeVar

from pants.base.specs import Specs
from pants.core.goals.lint import (
    AbstractLintRequest,
    LintFilesRequest,
    LintResult,
    LintTargetsRequest,
    _MultiToolGoalSubsystem,
    get_partitions_by_request_type,
)
from pants.core.goals.multi_tool_goal_helper import BatchSizeOption, OnlyOption
from pants.core.util_rules.partitions import PartitionerType, PartitionMetadataT
from pants.core.util_rules.partitions import Partitions as UntypedPartitions
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.fs import MergeDigests, PathGlobs, Snapshot, SnapshotDiff, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.intrinsics import digest_to_snapshot, merge_digests
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import collect_rules, concurrently, goal_rule, implicitly, rule
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass, union
from pants.option.option_types import BoolOption
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name, doc_url
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import Simplifier, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FixResult(EngineAwareReturnType):
    input: Snapshot
    output: Snapshot
    stdout: str
    stderr: str
    tool_name: str

    @staticmethod
    async def create(
        request: AbstractFixRequest.Batch,
        process_result: ProcessResult | FallibleProcessResult,
        *,
        output_simplifier: Simplifier = Simplifier(),
    ) -> FixResult:
        return FixResult(
            input=request.snapshot,
            output=await digest_to_snapshot(process_result.output_digest),
            stdout=output_simplifier.simplify(process_result.stdout),
            stderr=output_simplifier.simplify(process_result.stderr),
            tool_name=request.tool_name,
        )

    def __post_init__(self):
        # NB: We debug log stdout/stderr because `message` doesn't log it.
        log = f"Output from {self.tool_name}"
        if self.stdout:
            log += f"\n{self.stdout}"
        if self.stderr:
            log += f"\n{self.stderr}"
        logger.debug(log)

    @property
    def did_change(self) -> bool:
        return self.output != self.input

    def level(self) -> LogLevel | None:
        return LogLevel.WARN if self.did_change else LogLevel.INFO

    def message(self) -> str | None:
        message = "made changes." if self.did_change else "made no changes."

        # NB: Instead of printing out `stdout` and `stderr`, we just print a list of files which
        # were changed/added/removed. We do this for two reasons:
        #   1. This is run as part of both `fmt`/`fix` and `lint`, and we want consistent output between both
        #   2. Different tools have different stdout/stderr. This way is consistent across all tools.
        if self.did_change:
            snapshot_diff = SnapshotDiff.from_snapshots(self.input, self.output)
            output = "".join(
                f"\n  {file}"
                for file in itertools.chain(
                    snapshot_diff.changed_files,
                    snapshot_diff.their_unique_files,  # added files
                    snapshot_diff.our_unique_files,  # removed files
                    # NB: there is no rename detection, so a rename will list
                    # both the old filename (removed) and the new filename (added).
                )
            )
        else:
            output = ""

        return f"{self.tool_name} {message}{output}"

    def cacheable(self) -> bool:
        """Is marked uncacheable to ensure that it always renders."""
        return False


Partitions = UntypedPartitions[str, PartitionMetadataT]


@union
class AbstractFixRequest(AbstractLintRequest):
    is_fixer = True

    # Enable support for re-using this request's rule in `lint`, where the success/failure of the linter corresponds to
    # whether the rule's output matches the input (i.e. whether the tool made changes or not).
    #
    # If you set this to `False`, you'll need to provide the following `UnionRule` with a custom class,
    # as well as their corresponding implementation rules:
    #   - `UnionRule(AbstractLintRequest, cls)`
    #   - `UnionRule(AbstractLintRequest.Batch, cls)`
    #
    # !!! Setting this to `False` should be exceedingly rare, as the default implementation handles two important things:
    #   - Re-use of the exact same process in `fix` as in `lint`, so runs like `pants fix lint` use
    #     cached/memoized results in `lint`. This pattern is commonly used by developers locally.
    #   - Ensuring that `pants lint` is checking that the file(s) are actually fixed. It's easy to forget to provide the
    #     `lint` implementation (which is used usually in CI, as opposed to `fix`), which allows files to be merged
    #     into the default branch un-fixed. (Fun fact, this happened in the Pants codebase before this inheritance existed
    #     and was the catalysts for this design).
    # The case for disabling this is when the `fix` implementation fixes a strict subset of some `lint` implementation, where
    # the check for is-this-fixed in the `lint` implementation isn't possible.
    # As an example, let's say tool `cruft` has `cruft lint` which lints for A, B and C. It also has `cruft lint --fix` which fixes A.
    # Tthere's no way to not check for `A` in `cruft lint`. Since you're already going to provide a `lint` implementation
    # which corresponds to `cruft lint`, there's no point in running `cruft check --fix` in `lint` as it's already covered by
    # `cruft lint`.
    enable_lint_rules: ClassVar[bool] = True

    @distinct_union_type_per_subclass(in_scope_types=[EnvironmentName])
    @dataclass(frozen=True)
    class Batch(AbstractLintRequest.Batch):
        snapshot: Snapshot

        @property
        def files(self) -> tuple[str, ...]:
            return tuple(FrozenOrderedSet(self.elements))

    @classmethod
    def _get_rules(cls) -> Iterable[UnionRule]:
        if cls.enable_lint_rules:
            yield from super()._get_rules()
        yield UnionRule(AbstractFixRequest, cls)
        yield UnionRule(AbstractFixRequest.Batch, cls.Batch)


class FixTargetsRequest(AbstractFixRequest, LintTargetsRequest):
    @classmethod
    def _get_rules(cls) -> Iterable:
        yield from cls.partitioner_type.default_rules(cls, by_file=True)
        yield from (
            rule
            for rule in super()._get_rules()
            # NB: We don't want to yield `lint.py`'s default partitioner
            if isinstance(rule, UnionRule)
        )
        yield UnionRule(FixTargetsRequest.PartitionRequest, cls.PartitionRequest)


class FixFilesRequest(AbstractFixRequest, LintFilesRequest):
    @classmethod
    def _get_rules(cls) -> Iterable:
        if cls.partitioner_type is not PartitionerType.CUSTOM:
            raise ValueError(
                "Pants does not provide default partitioners for `FixFilesRequest`."
                + " You will need to provide your own partitioner rule."
            )

        yield from super()._get_rules()
        yield UnionRule(FixFilesRequest.PartitionRequest, cls.PartitionRequest)


class _FixBatchElement(NamedTuple):
    request_type: type[AbstractFixRequest.Batch]
    tool_name: str
    files: tuple[str, ...]
    key: Any


class _FixBatchRequest(Collection[_FixBatchElement]):
    """Request to sequentially fix all the elements in the given batch."""


@dataclass(frozen=True)
class _FixBatchResult:
    results: tuple[FixResult, ...]

    @property
    def did_change(self) -> bool:
        return any(result.did_change for result in self.results)


class FixSubsystem(GoalSubsystem):
    name = "fix"
    help = softwrap(
        f"""
        Autofix source code.

        This goal runs tools that make 'semantic' changes to source code, where the meaning of the
        code may change.

        See also:

        - [The `fmt` goal]({doc_url("reference/goals/fix")} will run code-editing tools that may make only
          syntactic changes, not semantic ones. The `fix` includes running these `fmt` tools by
          default (see [the `skip_formatters` option](#skip_formatters) to control this).

        - [The `lint` goal]({doc_url("reference/goals/lint")}) will validate code is formatted, by running these
          fixers and checking there's no change.

        - Documentation about formatters for various ecosystems, such as:
          [Python]({doc_url("docs/python/overview/linters-and-formatters")}), [JVM]({doc_url("jvm/java-and-scala#lint-and-format")}),
          [SQL]({doc_url("docs/sql#enable-sqlfluff-linter")})
        """
    )

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return AbstractFixRequest in union_membership

    only = OnlyOption("fixer", "autoflake", "pyupgrade")
    skip_formatters = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, skip running all formatters.

            FYI: when running `{bin_name()} fix fmt ::`, there should be diminishing performance
            benefit to using this flag. Pants attempts to reuse the results from `fmt` when running
            `fix` where possible.
            """
        ),
    )
    batch_size = BatchSizeOption(uppercase="Fixer", lowercase="fixer")


class Fix(Goal):
    subsystem_cls = FixSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


async def _write_files(workspace: Workspace, batched_results: Iterable[_FixBatchResult]):
    if any(batched_result.did_change for batched_result in batched_results):
        # NB: this will fail if there are any conflicting changes, which we want to happen rather
        # than silently having one result override the other. In practice, this should never
        # happen due to us grouping each file's tools into a single digest.
        merged_digest = await merge_digests(
            MergeDigests(
                batched_result.results[-1].output.digest for batched_result in batched_results
            )
        )
        workspace.write_digest(merged_digest)


def _print_results(
    console: Console,
    results: Iterable[FixResult],
):
    if results:
        console.print_stderr("")

    # We group all results for the same tool so that we can give one final status in the
    # summary. This is only relevant if there were multiple results because of
    # `--per-file-caching`.
    tool_to_results = defaultdict(set)
    for result in results:
        tool_to_results[result.tool_name].add(result)

    for tool, results in sorted(tool_to_results.items()):
        if any(result.did_change for result in results):
            sigil = console.sigil_succeeded_with_edits()
            status = "made changes"
        else:
            sigil = console.sigil_succeeded()
            status = "made no changes"
        console.print_stderr(f"{sigil} {tool} {status}.")


_CoreRequestType = TypeVar("_CoreRequestType", bound=AbstractFixRequest)
_TargetPartitioner = TypeVar("_TargetPartitioner", bound=FixTargetsRequest.PartitionRequest)
_FilePartitioner = TypeVar("_FilePartitioner", bound=FixFilesRequest.PartitionRequest)
_GoalT = TypeVar("_GoalT", bound=Goal)


class _BatchableMultiToolGoalSubsystem(_MultiToolGoalSubsystem, Protocol):
    batch_size: BatchSizeOption


@rule(polymorphic=True)
async def fix_batch(batch: AbstractFixRequest.Batch) -> FixResult:
    raise NotImplementedError()


@rule
async def fix_batch_sequential(
    request: _FixBatchRequest,
) -> _FixBatchResult:
    current_snapshot = await digest_to_snapshot(
        **implicitly({PathGlobs(request[0].files): PathGlobs})
    )

    results = []
    for request_type, tool_name, files, key in request:
        batch = request_type(tool_name, files, key, current_snapshot)
        result = await fix_batch(**implicitly({batch: AbstractFixRequest.Batch}))
        results.append(result)

        assert set(result.output.files) == set(batch.files), (
            f"Expected {result.output.files} to match {batch.files}"
        )
        current_snapshot = result.output
    return _FixBatchResult(tuple(results))


async def _do_fix(
    core_request_types: Iterable[type[_CoreRequestType]],
    target_partitioners: Iterable[type[_TargetPartitioner]],
    file_partitioners: Iterable[type[_FilePartitioner]],
    goal_cls: type[_GoalT],
    subsystem: _BatchableMultiToolGoalSubsystem,
    specs: Specs,
    workspace: Workspace,
    console: Console,
    make_targets_partition_request_get: Callable[
        [_TargetPartitioner], Coroutine[Any, Any, Partitions]
    ],
    make_files_partition_request_get: Callable[[_FilePartitioner], Coroutine[Any, Any, Partitions]],
) -> _GoalT:
    partitions_by_request_type = await get_partitions_by_request_type(
        core_request_types,
        target_partitioners,
        file_partitioners,
        subsystem,
        specs,
        make_targets_partition_request_get,
        make_files_partition_request_get,
    )

    if not partitions_by_request_type:
        return goal_cls(exit_code=0)

    def batch_by_size(files: Iterable[str]) -> Iterator[tuple[str, ...]]:
        batches = partition_sequentially(
            files,
            key=lambda x: str(x),
            size_target=subsystem.batch_size,  # type: ignore[arg-type]
            size_max=4 * subsystem.batch_size,  # type: ignore[operator]
        )
        for batch in batches:
            yield tuple(batch)

    def _make_disjoint_batch_requests() -> Iterable[_FixBatchRequest]:
        partition_infos: Iterable[tuple[type[AbstractFixRequest], Any]]
        files: Sequence[str]

        partition_infos_by_files = defaultdict(list)
        for request_type, partitions_list in partitions_by_request_type.items():
            for partitions in partitions_list:
                for partition in partitions:
                    for file in partition.elements:
                        partition_infos_by_files[file].append((request_type, partition.metadata))

        files_by_partition_info = defaultdict(list)
        for file, partition_infos in partition_infos_by_files.items():
            deduped_partition_infos = FrozenOrderedSet(partition_infos)
            files_by_partition_info[deduped_partition_infos].append(file)

        for partition_infos, files in files_by_partition_info.items():
            for batch in batch_by_size(files):
                yield _FixBatchRequest(
                    _FixBatchElement(
                        request_type.Batch,
                        request_type.tool_name,
                        batch,
                        partition_metadata,
                    )
                    for request_type, partition_metadata in partition_infos
                )

    all_results = await concurrently(
        fix_batch_sequential(request) for request in _make_disjoint_batch_requests()
    )

    individual_results = list(
        itertools.chain.from_iterable(result.results for result in all_results)
    )

    await _write_files(workspace, all_results)
    _print_results(console, individual_results)

    # Since the rules to produce FixResult should use ProcessResult, rather than
    # FallibleProcessResult, we assume that there were no failures.
    return goal_cls(exit_code=0)


@rule(polymorphic=True)
async def partition_targets(req: FixTargetsRequest.PartitionRequest) -> Partitions:
    raise NotImplementedError()


@rule(polymorphic=True)
async def partition_files(req: FixFilesRequest.PartitionRequest) -> Partitions:
    raise NotImplementedError()


@goal_rule
async def fix(
    console: Console,
    specs: Specs,
    fix_subsystem: FixSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fix:
    return await _do_fix(
        sorted(
            (
                request_type
                for request_type in union_membership.get(AbstractFixRequest)
                if not (request_type.is_formatter and fix_subsystem.skip_formatters)
            ),
            # NB: We sort the core request types so that fixers are first. This is to ensure that, between
            # fixers and formatters, re-running isn't necessary due to tool conflicts (re-running may
            # still be necessary within formatters). This is because fixers are expected to modify
            # code irrespective of formatting, and formatters aren't expected to be modifying the code
            # in a way that needs to be fixed.
            key=lambda request_type: request_type.is_fixer,
            reverse=True,
        ),
        union_membership.get(FixTargetsRequest.PartitionRequest),
        union_membership.get(FixFilesRequest.PartitionRequest),
        Fix,
        fix_subsystem,  # type: ignore[arg-type]
        specs,
        workspace,
        console,
        lambda request_type: partition_targets(
            **implicitly({request_type: FixTargetsRequest.PartitionRequest})
        ),
        lambda request_type: partition_files(
            **implicitly({request_type: FixFilesRequest.PartitionRequest})
        ),
    )


@rule(level=LogLevel.DEBUG)
async def convert_fix_result_to_lint_result(fix_result: FixResult) -> LintResult:
    return LintResult(
        1 if fix_result.did_change else 0,
        fix_result.stdout,
        fix_result.stderr,
        linter_name=fix_result.tool_name,
        _render_message=False,  # Don't re-render the message
    )


def rules():
    return collect_rules()
