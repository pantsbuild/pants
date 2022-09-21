# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Generic,
    Iterable,
    Iterator,
    Sequence,
    Tuple,
    TypeVar,
    cast,
)

from typing_extensions import final

from pants.base.specs import Specs
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest, _FmtBuildFilesRequest
from pants.core.goals.style_request import (
    StyleRequest,
    determine_specified_tool_names,
    only_option_help,
    style_batch_size_help,
    write_reports,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, Digest, PathGlobs, Snapshot, SpecsPaths, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import FilespecMatcher
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import FieldSet, FilteredTargets, SourcesField
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.option_types import BoolOption, IntOption, StrListOption
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_classproperty
from pants.util.meta import runtime_ignore_subscripts
from pants.util.strutil import softwrap, strip_v2_chroot_path

logger = logging.getLogger(__name__)

_SR = TypeVar("_SR", bound=StyleRequest)
_T = TypeVar("_T")
_FieldSetT = TypeVar("_FieldSetT", bound=FieldSet)
_PartitionElementT = TypeVar("_PartitionElementT")


class AmbiguousRequestNamesError(Exception):
    def __init__(
        self,
        ambiguous_name: str,
        requests: set[type],
    ):
        request_names = {
            f"{request_target.__module__}.{request_target.__qualname__}"
            for request_target in requests
        }

        super().__init__(
            softwrap(
                f"""
                The same name `{ambiguous_name}` is used by multiple requests,
                which causes ambiguity: {request_names}

                To fix, please update these requests so that `{ambiguous_name}`
                is not used more than once.
                """
            )
        )


@dataclass(frozen=True)
class LintResult(EngineAwareReturnType):
    exit_code: int
    stdout: str
    stderr: str
    linter_name: str
    partition_description: str | None = None
    report: Digest = EMPTY_DIGEST

    @classmethod
    def from_fallible_process_result(
        cls,
        process_result: FallibleProcessResult,
        *,
        linter_name: str,
        partition_description: str | None = None,
        strip_chroot_path: bool = False,
        report: Digest = EMPTY_DIGEST,
    ) -> LintResult:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        return cls(
            exit_code=process_result.exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=prep_output(process_result.stderr),
            linter_name=linter_name,
            partition_description=partition_description,
            report=report,
        )

    def metadata(self) -> dict[str, Any]:
        return {"partition": self.partition_description}

    def level(self) -> LogLevel | None:
        return LogLevel.ERROR if self.exit_code != 0 else LogLevel.INFO

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


@runtime_ignore_subscripts
class Partitions(FrozenDict[Any, "tuple[_PartitionElementT, ...]"]):
    """A mapping from <partition key> to <partition>.

    When implementing a linter, one of your rules will return this type, taking in a
    `PartitionRequest` specific to your linter.

    The return likely will fit into one of:
        - Returning an empty partition: E.g. if your tool is being skipped.
        - Returning one partition. The partition may contain all of the inputs
            (as will likely be the case for target linters) or a subset (which will likely be the
            case for targetless linters).
        - Returning >1 partition. This might be the case if you can't run
            the tool on all the inputs at once. E.g. having to run a Python tool on XYZ with Py3,
            and files ABC with Py2.

    The partition key can be of any type able to cross a rule-boundary, and will be provided to the
    rule which "runs" your tool.

    NOTE: The partition may be divided further into multiple sub-partitions.
    """

    @classmethod
    def single_partition(
        cls, elements: Iterable[_PartitionElementT], key: Any = None
    ) -> Partitions[_PartitionElementT]:
        """Helper constructor for implementations that have only one partition."""
        return Partitions([(key, tuple(elements))])


@union
class LintRequest:
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
                ) -> Partitions[DryCleaningFieldSet]:
                    if subsystem.skip:
                        return Partitions()

                    # One possible implementation
                    return Partitions.single_partition(request.field_sets)

        2. A rule which takes an instance of your request type's `SubPartition` class property, and
            returns a `LintResult instance.
            E.g.
                @rule
                async def dry_clean(
                    request: DryCleaningRequest.SubPartition,
                ) -> LintResult:
                    ...

    Lastly, register the rules which tell Pants about your plugin.
    E.g.
        def rules():
            return [
                *collect_rules(),
                *DryCleaningRequest.registration_rules()
            ]

    NOTE: For more information about the `PartitionRequest` types, see
        `LintTargetsRequest.PartitionRequest`/`LintFilesRequest.PartitionRequest`.
    """

    name: ClassVar[str]

    def debug_hint(self) -> str:
        return self.name

    @dataclass(frozen=True)
    @runtime_ignore_subscripts
    class SubPartition(Generic[_PartitionElementT]):
        elements: Tuple[_PartitionElementT, ...]
        key: Any

    _SubPartitionBase = SubPartition

    if not TYPE_CHECKING:

        @memoized_classproperty
        def SubPartition(cls):
            @union(in_scope_types=[EnvironmentName])
            class SubPartition(cls._SubPartitionBase):
                pass

            return SubPartition

    @final
    @classmethod
    def registration_rules(cls) -> Iterable[UnionRule]:
        yield from cls._get_registration_rules()

    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield UnionRule(LintRequest, cls)
        yield UnionRule(LintRequest.SubPartition, cls.SubPartition)


class LintTargetsRequest(LintRequest, StyleRequest):
    """The entry point for linters that operate on targets."""

    @dataclass(frozen=True)
    @runtime_ignore_subscripts
    class PartitionRequest(Generic[_FieldSetT]):
        """Returns a unique `PartitionRequest` type per calling type.

        This serves us 2 purposes:
            1. `LintTargetsRequest.PartitionRequest` is the unique type used as a union base for plugin registration.
            2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
        """

        field_sets: tuple[_FieldSetT, ...]

    _PartitionRequestBase = PartitionRequest

    if not TYPE_CHECKING:

        @memoized_classproperty
        def PartitionRequest(cls):
            @union(in_scope_types=[EnvironmentName])
            class PartitionRequest(cls._PartitionRequestBase):
                pass

            return PartitionRequest

    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_registration_rules()
        yield UnionRule(LintTargetsRequest.PartitionRequest, cls.PartitionRequest)


@dataclass(frozen=True)
class LintFilesRequest(LintRequest, EngineAwareParameter):
    """The entry point for linters that do not use targets."""

    @dataclass(frozen=True)
    class PartitionRequest:
        """Returns a unique `PartitionRequest` type per calling type.

        This serves us 2 purposes:
            1. `LintFilesRequest.PartitionRequest` is the unique type used as a union base for plugin registration.
            2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
        """

        file_paths: tuple[str, ...]

    _PartitionRequestBase = PartitionRequest

    if not TYPE_CHECKING:

        @memoized_classproperty
        def PartitionRequest(cls):
            @union(in_scope_types=[EnvironmentName])
            class PartitionRequest(cls._PartitionRequestBase):
                pass

            return PartitionRequest

    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_registration_rules()
        yield UnionRule(LintFilesRequest.PartitionRequest, cls.PartitionRequest)


# If a user wants linter reports to show up in dist/ they must ensure that the reports
# are written under this directory. E.g.,
# ./pants --flake8-args="--output-file=reports/report.txt" lint <target>
REPORT_DIR = "reports"


class LintSubsystem(GoalSubsystem):
    name = "lint"
    help = "Run all linters and/or formatters in check mode."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return bool(
            {
                LintRequest,
                FmtTargetsRequest,
                _FmtBuildFilesRequest,
            }.intersection(union_membership.union_rules.keys())
        )

    only = StrListOption(
        help=only_option_help("lint", "linter", "flake8", "shellcheck"),
    )
    skip_formatters = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, skip running all formatters in check-only mode.

            FYI: when running `{bin_name()} fmt lint ::`, there should be little performance
            benefit to using this flag. Pants will reuse the results from `fmt` when running `lint`.
            """
        ),
    )
    batch_size = IntOption(
        advanced=True,
        default=128,
        help=style_batch_size_help(uppercase="Linter", lowercase="linter"),
    )


class Lint(Goal):
    subsystem_cls = LintSubsystem


def _check_ambiguous_request_names(
    *requests: type,
) -> None:
    def key(target: type) -> str:
        return target.name  # type: ignore[attr-defined,no-any-return]

    for name, request_group in itertools.groupby(requests, key=key):
        request_group_set = set(request_group)

        if len(request_group_set) > 1:
            raise AmbiguousRequestNamesError(name, request_group_set)


def _print_results(
    console: Console,
    results_by_tool: dict[str, list[LintResult]],
    formatter_failed: bool,
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

    if formatter_failed:
        console.print_stderr("")
        console.print_stderr(f"(One or more formatters failed. Run `{bin_name()} fmt` to fix.)")


def _get_error_code(results: Sequence[LintResult]) -> int:
    for result in reversed(results):
        if result.exit_code:
            return result.exit_code
    return 0


# TODO(16868): Rule parser requires arguments to be values in module scope
_LintTargetsPartitionRequest = LintTargetsRequest.PartitionRequest
_LintFilesPartitionRequest = LintFilesRequest.PartitionRequest
_LintSubPartition = LintRequest.SubPartition


@goal_rule
async def lint(
    console: Console,
    workspace: Workspace,
    specs: Specs,
    build_file_options: BuildFileOptions,
    lint_subsystem: LintSubsystem,
    union_membership: UnionMembership,
    dist_dir: DistDir,
) -> Lint:
    lint_request_types = cast("Iterable[type[LintRequest]]", union_membership.get(LintRequest))
    target_partitioners = union_membership.get(LintTargetsRequest.PartitionRequest)
    file_partitioners = union_membership.get(LintFilesRequest.PartitionRequest)

    fmt_target_request_types = cast(
        "Iterable[type[FmtTargetsRequest]]", union_membership.get(FmtTargetsRequest)
    )
    fmt_build_request_types = cast(
        "Iterable[type[_FmtBuildFilesRequest]]", union_membership.get(_FmtBuildFilesRequest)
    )

    # NB: Target formatters and build file formatters can share a name, so we can't check them both
    # for ambiguity at the same time.
    _check_ambiguous_request_names(
        *lint_request_types,
        *fmt_target_request_types,
    )

    _check_ambiguous_request_names(
        *lint_request_types,
        *fmt_build_request_types,
    )

    specified_names = determine_specified_tool_names(
        "lint",
        lint_subsystem.only,
        [*lint_request_types, *fmt_target_request_types],  # type: ignore[list-item]
        extra_valid_names={request.name for request in fmt_build_request_types},
    )

    def is_specified(request_type: type):
        return request_type.name in specified_names  # type: ignore[attr-defined]

    lint_request_types = list(filter(is_specified, lint_request_types))
    fmt_target_request_types = filter(is_specified, fmt_target_request_types)
    fmt_build_request_types = filter(is_specified, fmt_build_request_types)

    _get_targets = Get(
        FilteredTargets,
        Specs,
        specs if target_partitioners or fmt_target_request_types else Specs.empty(),
    )
    _get_specs_paths = Get(
        SpecsPaths, Specs, specs if file_partitioners or fmt_build_request_types else Specs.empty()
    )
    targets, specs_paths = await MultiGet(_get_targets, _get_specs_paths)

    specified_build_files = FilespecMatcher(
        includes=[os.path.join("**", p) for p in build_file_options.patterns],
        excludes=build_file_options.ignores,
    ).matches(specs_paths.files)

    def batch(
        iterable: Iterable[_T], key: Callable[[_T], str] = lambda x: str(x)
    ) -> Iterator[tuple[_T, ...]]:
        batches = partition_sequentially(
            iterable,
            key=key,
            size_target=lint_subsystem.batch_size,
            size_max=4 * lint_subsystem.batch_size,
        )
        for batch in batches:
            yield tuple(batch)

    def batch_by_type(
        request_types: Iterable[type[_SR]],
    ) -> tuple[tuple[type[_SR], tuple[FieldSet, ...]], ...]:
        def key(fs: FieldSet) -> str:
            return fs.address.spec

        return tuple(
            (request_type, field_set_batch)
            for request_type in request_types
            for field_set_batch in batch(
                (
                    request_type.field_set_type.create(target)
                    for target in targets
                    if request_type.field_set_type.is_applicable(target)
                ),
                key=key,
            )
        )

    def partition_request_get(
        request_type: type[LintRequest],
    ) -> Get[Partitions]:
        partition_request_type: type = getattr(request_type, "PartitionRequest")
        if partition_request_type in target_partitioners:
            lint_targets_request_type = cast("type[LintTargetsRequest]", request_type)
            return Get(
                Partitions,
                _LintTargetsPartitionRequest,
                lint_targets_request_type.PartitionRequest(
                    tuple(
                        lint_targets_request_type.field_set_type.create(target)
                        for target in targets
                        if lint_targets_request_type.field_set_type.is_applicable(target)
                    )
                ),
            )
        else:
            assert partition_request_type in file_partitioners
            return Get(
                Partitions,
                _LintFilesPartitionRequest,
                cast("type[LintFilesRequest]", request_type).PartitionRequest(specs_paths.files),
            )

    all_partitions = await MultiGet(
        partition_request_get(request_type) for request_type in lint_request_types
    )
    lint_partitions_by_request_type = defaultdict(list)
    for request_type, lint_partition in zip(lint_request_types, all_partitions):
        lint_partitions_by_request_type[request_type].append(lint_partition)

    lint_batches_by_request_type = {
        rt: [
            (subpartition, key)
            for partitions in lint_partitions
            for key, partition in partitions.items()
            for subpartition in batch(partition)
        ]
        for rt, lint_partitions in lint_partitions_by_request_type.items()
    }

    lint_batches = [
        rt.SubPartition(elements, key)
        for rt, batch in lint_batches_by_request_type.items()
        for elements, key in batch
    ]

    fmt_target_requests: Iterable[FmtTargetsRequest] = ()
    fmt_build_requests: Iterable[_FmtBuildFilesRequest] = ()
    if not lint_subsystem.skip_formatters:
        batched_fmt_target_request_pairs = batch_by_type(fmt_target_request_types)
        all_fmt_source_batches = await MultiGet(
            Get(
                SourceFiles,
                SourceFilesRequest(
                    cast(
                        SourcesField,
                        getattr(field_set, "sources", getattr(field_set, "source", None)),
                    )
                    for field_set in batch
                ),
            )
            for _, batch in batched_fmt_target_request_pairs
        )
        fmt_target_requests = (
            request_type(
                batch,
                snapshot=source_files_snapshot.snapshot,
            )
            for (request_type, batch), source_files_snapshot in zip(
                batched_fmt_target_request_pairs, all_fmt_source_batches
            )
        )

        build_file_batch_snapshots = await MultiGet(
            Get(Snapshot, PathGlobs(paths_batch)) for paths_batch in batch(specified_build_files)
        )
        fmt_build_requests = (
            fmt_build_request_type(snapshot)
            for fmt_build_request_type in fmt_build_request_types
            for snapshot in build_file_batch_snapshots
        )

    all_requests = [
        *(Get(LintResult, _LintSubPartition, request) for request in lint_batches),
        *(Get(LintResult, FmtTargetsRequest, request) for request in fmt_target_requests),
        *(Get(LintResult, _FmtBuildFilesRequest, request) for request in fmt_build_requests),
    ]
    all_batch_results = await MultiGet(all_requests)

    formatter_failed = any(result.exit_code for result in all_batch_results[len(lint_batches) :])

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
    )
    return Lint(_get_error_code(all_batch_results))


@rule
async def convert_fmt_result_to_lint_result(fmt_result: FmtResult) -> LintResult:
    return LintResult(
        1 if fmt_result.did_change else 0,
        fmt_result.stdout,
        fmt_result.stderr,
        linter_name=fmt_result.formatter_name,
    )


def rules():
    return collect_rules()
