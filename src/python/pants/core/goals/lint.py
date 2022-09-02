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
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import EMPTY_DIGEST, Digest, PathGlobs, Snapshot, SpecsPaths, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import FilespecMatcher
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, FilteredTargets, SourcesField
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.option_types import BoolOption, IntOption, StrListOption
from pants.util.collections import partition_sequentially
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.memo import memoized_classproperty
from pants.util.meta import runtime_subscriptable
from pants.util.strutil import softwrap, strip_v2_chroot_path

logger = logging.getLogger(__name__)

_SR = TypeVar("_SR", bound=StyleRequest)
_T = TypeVar("_T")


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
            f"The same name `{ambiguous_name}` is used by multiple requests, "
            f"which causes ambiguity: {request_names}\n\n"
            f"To fix, please update these requests so that `{ambiguous_name}` "
            f"is not used more than once."
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


_PartitionElementT = TypeVar("_PartitionElementT", FieldSet, str)
_MetadataT = TypeVar("_MetadataT")
_FieldSetT = TypeVar("_FieldSetT", bound=FieldSet)


class _PartitionsBase(
    Generic[_PartitionElementT, _MetadataT],
    Collection[Tuple[Tuple[_PartitionElementT, ...], _MetadataT]],
):
    """A collection containing pairs of (tuple(<elements>), arbitrary metadata).

    When implementing a linter, one of your rules will return a subclass of this type, taking in a
    `PartitionRequest` specific to your linter. The specific return type will either be
    `TargetsPartition` or `FilesPartition`.

    The return likely will fit into one of:
        - Returning an empty partition: E.g. if your tool is being skipped.
        - Returning one partition (with optional metadata). The return value may contain all of
            the inputs (as will likely be the case for target linters) or a subset (which will likely
            be the case for targetless linters).
        - Returning >1 partition (with optional metadata). This might be the case if you can't run
            the tool on all the inputs at once. E.g. having to run a Python tool on XYZ with Py3,
            and files ABC with Py2.

    The "arbitrary metadata" in the pair solely exists to pass information from your "partition" rule
    to your "runner" rule. It can be `None` (no metadata), or any other object the engine allows in
    a rule input/output (i.e. hashable+equatable+immutable types).
    NOTE: The partition may be divided further into multiple batches, with each batch getting the same
        metadata object. Therefore your metadata should be applicable to possible sub-slices of the
        partition.
    """


@union
class LintRequest:
    """Base class for plugin types wanting to be run as part of `lint`.

    Plugins should define a new type which subclasses either `LintTargetsRequest` (to lint targets)
    or `LintFilesRequest` (to lint arbitrary files), and set the approrpiate class variables.
    E.g.
        class DryCleaningRequest(LintTargetsRequest):
            name = DryCleaningSubsystem.options_scope
            field_set_type = DryCleaningFieldSet

    Then, define 2 `@rule`s:
        1. A rule which takes an instance of your request type's `PartitionRequest` class property,
            and returns a `TargetPartitions`/`FilePartitions` instance.
            E.g.
                @rule
                async def partition(
                    request: DryCleaningRequest.PartitionRequest[DryCleaningFieldSet]
                    # or `request: DryCleaningRequest.PartitionRequest` if file linter
                    subsystem: DryCleaningSubsystem,
                ) -> TargetPartitions:
                    if subsystem.skip:
                        return TargetPartitions()

                    # One possible implementation
                    return TargetPartitions.from_field_set_partitions([request.field_sets])

        2. A rule which takes an instance of your request type's `Batch` class property, and
            returns a `LintResult instance.
            E.g.
                @rule
                async def dry_clean(
                    request: DryCleaningRequest.Batch,
                ) -> LintResult:
                    ...

    Lastly, register the rules which tells Pants about your plugin.
    E.g.
        def rules():
            return [
                *collect_rules(),
                *DryCleaningRequest.registration_rules()
            ]

    NOTE: For more information about the `PartitionRequest` and `Batch` types, see
        `LintTargetsRequest.PartitionRequest`/`LintFilesRequest.PartitionRequest` and
        `LintTargetsRequest.Batch`/`LintFilesRequest.Batch` respectively.
    """

    name: ClassVar[str]

    def debug_hint(self) -> str:
        return self.name

    @memoized_classproperty
    def Batch(cls) -> type:
        @union
        class Batch:
            # NB: Fields declared for exposition, actual fields may vary in name but should contain
            # their first 2 members of these types. See subclass implementations for field info.
            inputs: tuple
            metadata: Any = None

        return Batch

    @final
    @classmethod
    def registration_rules(cls) -> Iterable[UnionRule]:
        yield from cls._get_registration_rules()

    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield UnionRule(LintRequest, cls)
        yield UnionRule(LintRequest.Batch, cls.Batch)


@union
class LintTargetsRequest(LintRequest, StyleRequest):
    """The entry point for linters that operate on targets."""

    if TYPE_CHECKING:

        @dataclass(frozen=True)
        class PartitionRequest(Generic[_FieldSetT]):
            field_sets: tuple[_FieldSetT, ...]

        @dataclass(frozen=True)
        class Batch(Generic[_FieldSetT, _MetadataT]):
            field_sets: tuple[_FieldSetT, ...]
            metadata: _MetadataT

    else:

        @memoized_classproperty
        def PartitionRequest(cls):
            """Returns a unique `PartitionRequest` type per calling type.

            This serves us 2 purposes:
                1. `LintTargetsRequest.PartitionRequest` is the unique type used as a union base for plugin registration.
                2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
            """

            @union
            @dataclass(frozen=True)
            @runtime_subscriptable
            class PartitionRequest:
                field_sets: tuple

            return PartitionRequest

        @memoized_classproperty
        def Batch(cls):
            @union
            @dataclass(frozen=True)
            @runtime_subscriptable
            class Batch:
                field_sets: tuple
                metadata: Any

            return Batch

    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_registration_rules()
        yield UnionRule(LintTargetsRequest.PartitionRequest, cls.PartitionRequest)


@runtime_subscriptable
class TargetPartitions(Generic[_MetadataT], _PartitionsBase[FieldSet, _MetadataT]):
    @classmethod
    def from_field_set_partitions(
        cls: type[TargetPartitions], field_set_partitions: Iterable[Iterable[FieldSet]]
    ) -> TargetPartitions[None]:
        """Helper for instantiating without any metadata."""
        return cls((tuple(partition), None) for partition in field_set_partitions)


@union
@dataclass(frozen=True)
class LintFilesRequest(LintRequest, EngineAwareParameter):
    """The entry point for linters that do not use targets."""

    if TYPE_CHECKING:

        @dataclass(frozen=True)
        class PartitionRequest:
            file_paths: tuple[str, ...]

        @dataclass(frozen=True)
        class Batch:
            file_paths: tuple[str, ...]
            metadata: Any

    else:

        @memoized_classproperty
        def PartitionRequest(cls):
            """Returns a unique `PartitionRequest` type per calling type.

            This serves us 2 purposes:
                1. `LintFilesRequest.PartitionRequest` is the unique type used as a union base for plugin registration.
                2. `<Plugin Defined Subclass>.PartitionRequest` is the unique type used as the union member.
            """

            @union
            @dataclass(frozen=True)
            class PartitionRequest:
                file_paths: tuple

            return PartitionRequest

        @memoized_classproperty
        def Batch(cls):
            @union
            class Batch:
                file_paths: tuple[str, ...]
                metadata: Any

            return Batch

    @classmethod
    def _get_registration_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_registration_rules()
        yield UnionRule(LintFilesRequest.PartitionRequest, cls.PartitionRequest)


class FilePartitions(Generic[_MetadataT], _PartitionsBase[str, _MetadataT]):
    @classmethod
    def from_file_partitions(
        cls: type[FilePartitions], file_path_partitions: Iterable[Iterable[str]]
    ) -> FilePartitions[None]:
        """Helper for instantiating without any metadata."""
        return cls((tuple(partition), None) for partition in file_path_partitions)


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


_LintTargetsPartitionRequest = LintTargetsRequest.PartitionRequest
_LintFilesPartitionRequest = LintFilesRequest.PartitionRequest
_LintBatch = LintRequest.Batch


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

    def partition_request_get(request_type: type[LintRequest]) -> Get[_PartitionsBase]:
        partition_request_type: type = getattr(request_type, "PartitionRequest")
        if partition_request_type in target_partitioners:
            lint_targets_request_type = cast("type[LintTargetsRequest]", request_type)
            return Get(
                TargetPartitions,
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
                FilePartitions,
                _LintFilesPartitionRequest,
                cast("type[LintFilesRequest]", request_type).PartitionRequest(specs_paths.files),
            )

    all_partitions = await MultiGet(
        partition_request_get(request_type) for request_type in lint_request_types
    )
    lint_partitions_by_rt = defaultdict(list)
    for request_type, lint_partition in zip(lint_request_types, all_partitions):
        lint_partitions_by_rt[request_type].append(lint_partition)

    lint_batches_by_rt = {
        rt: [
            (input_batch, metadata)
            for partition in lint_partitions
            for inputs, metadata in partition
            for input_batch in batch(inputs)
        ]
        for rt, lint_partitions in lint_partitions_by_rt.items()
    }

    lint_batches = (
        rt.Batch(inputs, metadata)
        for rt, batch in lint_batches_by_rt.items()
        for inputs, metadata in batch
    )

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
        *(Get(LintResult, _LintBatch, request) for request in lint_batches),
        *(Get(FmtResult, FmtTargetsRequest, request) for request in fmt_target_requests),
        *(Get(FmtResult, _FmtBuildFilesRequest, request) for request in fmt_build_requests),
    ]
    all_batch_results = cast(
        "tuple[LintResult | FmtResult, ...]",
        await MultiGet(all_requests),  # type: ignore[arg-type]
    )

    def get_name(result: LintResult | FmtResult):
        if isinstance(result, FmtResult):
            return result.formatter_name
        return result.linter_name

    formatter_failed = False

    def coerce_to_lintresult(batch_result: LintResult | FmtResult) -> LintResult:
        if isinstance(batch_result, FmtResult):
            nonlocal formatter_failed
            formatter_failed = formatter_failed or batch_result.did_change
            return LintResult(
                1 if batch_result.did_change else 0,
                batch_result.stdout,
                batch_result.stderr,
                linter_name=batch_result.formatter_name,
            )
        return batch_result

    results_by_tool = defaultdict(list)
    for result in all_batch_results:
        results_by_tool[get_name(result)].append(coerce_to_lintresult(result))

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
    return Lint(_get_error_code([coerce_to_lintresult(r) for r in all_batch_results]))


def rules():
    return collect_rules()
