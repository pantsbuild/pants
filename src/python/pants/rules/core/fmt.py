# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from abc import ABCMeta
from dataclasses import dataclass
from typing import ClassVar, Iterable, List, Optional, Tuple, Type, cast

from pants.engine.console import Console
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    DirectoryToMaterialize,
    Snapshot,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ProcessResult
from pants.engine.objects import Collection, union
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Field, Target, TargetsWithOrigins, TargetWithOrigin
from pants.rules.core.filter_empty_sources import TargetsWithSources, TargetsWithSourcesRequest
from pants.rules.core.lint import LinterConfiguration


@dataclass(frozen=True)
class FmtResult:
    digest: Digest
    stdout: str
    stderr: str

    @staticmethod
    def noop() -> "FmtResult":
        return FmtResult(digest=EMPTY_DIRECTORY_DIGEST, stdout="", stderr="")

    @staticmethod
    def from_process_result(process_result: ProcessResult) -> "FmtResult":
        return FmtResult(
            digest=process_result.output_directory_digest,
            stdout=process_result.stdout.decode(),
            stderr=process_result.stderr.decode(),
        )


@dataclass(frozen=True)
class FmtConfiguration(LinterConfiguration, metaclass=ABCMeta):
    """An ad hoc collection of the fields necessary for a particular auto-formatter to work with a
    target."""

    @classmethod
    def create(cls, target_with_origin: TargetWithOrigin) -> "FmtConfiguration":
        return cast(FmtConfiguration, super().create(target_with_origin))


class FmtConfigurations(Collection[FmtConfiguration]):
    """A collection of Configurations for a particular formatter, e.g. a collection of
    `IsortConfiguration`s."""

    config_type: ClassVar[Type[FmtConfiguration]]

    def __init__(
        self,
        configs: Iterable[FmtConfiguration],
        *,
        prior_formatter_result: Optional[Snapshot] = None
    ) -> None:
        super().__init__(configs)
        self.prior_formatter_result = prior_formatter_result


@union
@dataclass(frozen=True)
class LanguageFmtTargets:
    """All the targets that belong together as one language, e.g. all Python targets.

    This allows us to group distinct formatters by language as a performance optimization. Within a
    language, each formatter must run sequentially to not overwrite the previous formatter; but
    across languages, it is safe to run in parallel.
    """

    required_fields: ClassVar[Tuple[Type[Field], ...]]

    targets_with_origins: TargetsWithOrigins

    @classmethod
    def belongs_to_language(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields)


@dataclass(frozen=True)
class LanguageFmtResults:
    """This collection allows us to safely aggregate multiple `FmtResult`s for a language.

    The `combined_digest` is used to ensure that none of the formatters overwrite each other. The
    language implementation should run each formatter one at a time and pipe the resulting digest of
    one formatter into the next. The `combined_digest` must contain all files for the target,
    including any which were not re-formatted.
    """

    results: Tuple[FmtResult, ...]
    combined_digest: Digest


class FmtOptions(GoalSubsystem):
    """Autoformat source code."""

    name = "fmt"

    required_union_implementations = (LanguageFmtTargets,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--only",
            type=str,
            default=None,
            fingerprint=True,
            advanced=True,
            help=(
                "Only run the specified formatter. Currently the only accepted values are "
                "`scalafix` or not setting any value."
            ),
        )
        register(
            "--per-target-caching",
            advanced=True,
            type=bool,
            default=False,
            help=(
                "Rather than running all targets in a single batch, run each target as a "
                "separate process. Why do this? You'll get many more cache hits. Why not do this? "
                "Formatters both have substantial startup overhead and are cheap to add one "
                "additional file to the run. On a cold cache, it is much faster to use "
                "`--no-per-target-caching`. We only recommend using `--per-target-caching` if you "
                "are using a remote cache or if you have benchmarked that this option will be "
                "faster than `--no-per-target-caching` for your use case."
            ),
        )


class Fmt(Goal):
    subsystem_cls = FmtOptions


@goal_rule
async def fmt(
    console: Console,
    targets_with_origins: TargetsWithOrigins,
    options: FmtOptions,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    language_target_collection_types: Iterable[Type[LanguageFmtTargets]] = (
        union_membership.union_rules[LanguageFmtTargets]
    )

    language_target_collections: Iterable[LanguageFmtTargets] = tuple(
        language_target_collection_type(
            TargetsWithOrigins(
                target_with_origin
                for target_with_origin in targets_with_origins
                if language_target_collection_type.belongs_to_language(target_with_origin.target)
            )
        )
        for language_target_collection_type in language_target_collection_types
    )
    targets_with_sources: Iterable[TargetsWithSources] = await MultiGet(
        Get[TargetsWithSources](
            TargetsWithSourcesRequest(
                target_with_origin.target
                for target_with_origin in language_target_collection.targets_with_origins
            )
        )
        for language_target_collection in language_target_collections
    )
    # NB: We must convert back the generic TargetsWithSources objects back into their
    # corresponding LanguageFmtTargets, e.g. back to PythonFmtTargets, in order for the union
    # rule to work.
    valid_language_target_collections: Iterable[LanguageFmtTargets] = tuple(
        language_target_collection_cls(
            TargetsWithOrigins(
                target_with_origin
                for target_with_origin in language_target_collection.targets_with_origins
                if target_with_origin.target in language_targets_with_sources
            )
        )
        for language_target_collection_cls, language_target_collection, language_targets_with_sources in zip(
            language_target_collection_types, language_target_collections, targets_with_sources
        )
        if language_targets_with_sources
    )

    if options.values.per_target_caching:
        per_language_results = await MultiGet(
            Get[LanguageFmtResults](
                LanguageFmtTargets,
                language_target_collection.__class__(TargetsWithOrigins([target_with_origin])),
            )
            for language_target_collection in valid_language_target_collections
            for target_with_origin in language_target_collection.targets_with_origins
        )
    else:
        per_language_results = await MultiGet(
            Get[LanguageFmtResults](LanguageFmtTargets, language_target_collection)
            for language_target_collection in valid_language_target_collections
        )

    individual_results: List[FmtResult] = list(
        itertools.chain.from_iterable(
            language_result.results for language_result in per_language_results
        )
    )

    if not individual_results:
        return Fmt(exit_code=0)

    # NB: this will fail if there are any conflicting changes, which we want to happen rather than
    # silently having one result override the other. In practicality, this should never happen due
    # to us grouping each language's formatters into a single combined_digest.
    merged_formatted_digest = await Get[Digest](
        DirectoriesToMerge(
            tuple(language_result.combined_digest for language_result in per_language_results)
        )
    )
    workspace.materialize_directory(DirectoryToMaterialize(merged_formatted_digest))
    for result in individual_results:
        if result.stdout:
            console.print_stdout(result.stdout)
        if result.stderr:
            console.print_stderr(result.stderr)

    # Since the rules to produce FmtResult should use ExecuteRequest, rather than
    # FallibleProcess, we assume that there were no failures.
    return Fmt(exit_code=0)


def rules():
    return [fmt]
